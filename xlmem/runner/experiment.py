"""Experiment runner: orchestrates full multi-seed bilingual memory experiments.

Hard Rules:
1. Logs are append-only and immutable.
2. The runner records raw outputs; it NEVER judges.
3. Every model call routes strictly through LLMClient.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import logging
from pathlib import Path
import platform
import subprocess
import time
from typing import Any
from xlmem.adapters import get_adapter
from xlmem.adapters.base import MemoryAdapter
from xlmem.benchmark.facts import Fact, Memory, ProbeResult, load_facts
from xlmem.benchmark.generator import build_session_script
from xlmem.config import ExperimentConfig
from xlmem.llm.client import LLMClient
from xlmem.runner.probe import execute_probe
from xlmem.runner.session import SessionRunner

logger = logging.getLogger(__name__)


def adapter_settings(config: ExperimentConfig) -> dict[str, Any]:
    """The model settings every adapter is built with (adapters.base.ADAPTER_SETTINGS).

    Without these, adapters fall back to their own default model, so a config that
    names another backbone would silently run the default one.
    """
    if config.framework != "mock" and config.model.backend != "ollama":
        raise ValueError(
            f"Memory frameworks are driven through Ollama only; model.backend is "
            f"{config.model.backend!r}."
        )
    return {
        "llm_model": config.model.name,
        "embedder_model": config.embedder,
        "ollama_base_url": config.model.base_url,
        "temperature": config.model.temperature,
    }


# Packages whose versions can change what a run measures (AGENTS.md rule 10).
PROVENANCE_PACKAGES = (
    "mem0ai", "letta-client", "agentic-memory", "chromadb", "qdrant-client",
    "sentence-transformers", "transformers", "torch", "ollama", "litellm", "pydantic",
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str, cwd: Path = REPO_ROOT) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                             timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _vendored_git_sha(module: str) -> str | None:
    """Commit of a framework installed editable from a git checkout (A-MEM: 0.0.1 forever)."""
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    return _git("rev-parse", "HEAD", cwd=Path(spec.origin).resolve().parent)


def run_provenance(config: ExperimentConfig) -> dict[str, Any]:
    """What produced a run: code version, inputs and package versions (AGENTS.md §12).

    Recorded in every run log so a number can be traced back to the exact code and
    inputs without relying on an external manifest.
    """
    status = _git("status", "--porcelain", "--", "xlmem", "configs", "data")
    packages: dict[str, str | None] = {}
    for name in PROVENANCE_PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": None if status is None else bool(status),
        "config_sha256": hashlib.sha256(
            config.model_dump_json().encode("utf-8")
        ).hexdigest(),
        "fact_bank_sha256": _sha256(Path(config.benchmark.fact_bank)),
        "python": platform.python_version(),
        "packages": packages,
        "vendored_git_sha": {"agentic_memory": _vendored_git_sha("agentic_memory")},
    }


class ExperimentRunner:
    """Orchestrates an end-to-end XLMem experiment run across configured seeds."""

    def __init__(self, config: ExperimentConfig, llm_client: LLMClient | None = None) -> None:
        self.config = config
        self.llm_client = llm_client or LLMClient(
            base_url=config.model.base_url,
            backend=config.model.backend,
            default_model=config.model.name,
            mock_mode=(config.framework == "mock"),
        )
        self.output_base = Path(config.output_dir)
        self.output_base.mkdir(parents=True, exist_ok=True)

    def run_all_seeds(self) -> list[Path]:
        """Execute experiment across all configured seeds."""
        facts = load_facts(self.config.benchmark.fact_bank)
        if len(facts) > self.config.benchmark.n_facts:
            facts = facts[: self.config.benchmark.n_facts]

        # Refuse before any GPU work starts: a collision on the last seed must not
        # surface only after the earlier seeds have already run.
        existing = [self._seed_dir(s) for s in self.config.seeds if self._seed_dir(s).exists()]
        if existing:
            raise FileExistsError(
                "Refusing to overwrite existing run dir(s): "
                + ", ".join(str(p) for p in existing)
                + ". Run logs are immutable; use a new experiment name / output_dir."
            )

        run_dirs: list[Path] = []
        for seed in self.config.seeds:
            logger.info("Starting experiment %s with seed %d", self.config.experiment, seed)
            run_dir = self.run_single_seed(facts=facts, seed=seed)
            run_dirs.append(run_dir)

        return run_dirs

    def _seed_dir(self, seed: int) -> Path:
        return self.output_base / f"seed_{seed}"

    def run_single_seed(self, facts: list[Fact], seed: int) -> Path:
        """Execute experiment for a single seed and write immutable run artifacts.

        Raises FileExistsError if the seed dir already exists: one run = one dir,
        and logs are never rewritten (AGENTS.md Hard Rule 4).
        """
        seed_dir = self._seed_dir(seed)
        try:
            seed_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as e:
            raise FileExistsError(
                f"Refusing to overwrite existing run dir {seed_dir}. Run logs are "
                "immutable; use a new experiment name / output_dir."
            ) from e

        user_id = f"user_{self.config.experiment}_{seed}"
        adapter: MemoryAdapter = get_adapter(self.config.framework, **adapter_settings(self.config))
        adapter.reset(user_id=user_id)

        session_runner = SessionRunner(adapter=adapter, user_id=user_id)

        # 1. Build session script
        turns = build_session_script(
            facts=facts,
            store_lang=self.config.languages.store,
            probe_lang=self.config.languages.probe,
            filler_sessions=self.config.benchmark.filler_sessions,
            seed=seed,
        )

        plant_turns = [t for t in turns if t.kind == "plant"]
        filler_turns = [t for t in turns if t.kind == "filler"]
        probe_turns = [t for t in turns if t.kind == "probe"]
        correction_turns = [t for t in turns if t.kind == "correction"]

        # build_session_script emits two batches of kind == "probe" turns: the
        # Session-K probe (before any correction) and the Session-K+2 re-probe
        # (after correction, over the update-specific probe question). Both share
        # kind == "probe", so they must be split by session_id relative to the
        # correction session -- not treated as one undifferentiated batch -- or the
        # re-probe turns get answered before the correction they are meant to test
        # ever happens, which is the bug this split fixes.
        correction_session_id = correction_turns[0].session_id if correction_turns else None
        if correction_session_id is not None:
            pre_correction_probe_turns = [t for t in probe_turns if t.session_id < correction_session_id]
            reprobe_turns = [t for t in probe_turns if t.session_id > correction_session_id]
        else:
            pre_correction_probe_turns = probe_turns
            reprobe_turns = []

        # 2. Phase 1: Plant
        logger.info("Seed %d: Ingesting %d plant turns", seed, len(plant_turns))
        plant_records = session_runner.run_session(plant_turns)
        session_runner.consolidate()
        store_after_plant = session_runner.snapshot()

        with open(seed_dir / "store_after_plant.json", "x", encoding="utf-8") as f:
            json.dump([m.to_dict() for m in store_after_plant], f, ensure_ascii=False, indent=2)

        # 3. Phase 2: Filler / Distractors
        logger.info("Seed %d: Ingesting %d filler turns", seed, len(filler_turns))
        filler_records = session_runner.run_session(filler_turns)
        session_runner.consolidate()

        # 4. Phase 3: Probing (pre-correction only; see reprobe_turns split above)
        logger.info("Seed %d: Probing memory (%d queries)", seed, len(pre_correction_probe_turns))
        probe_results: list[ProbeResult] = []
        facts_by_id = {f.id: f for f in facts}

        for p_turn in pre_correction_probe_turns:
            fact = facts_by_id.get(p_turn.fact_id or "")
            if not fact:
                continue
            res = execute_probe(
                adapter=adapter,
                llm_client=self.llm_client,
                user_id=user_id,
                fact=fact,
                store_lang=self.config.languages.store,
                probe_lang=self.config.languages.probe,
            )
            probe_results.append(res)

        # 5. Phase 4: Corrections
        logger.info("Seed %d: Ingesting %d corrections", seed, len(correction_turns))
        correction_records = session_runner.run_session(correction_turns)
        session_runner.consolidate()

        # 6. Phase 5: Re-Probe (Session K+2 -- must run strictly after corrections,
        # so Staleness Rate scores the actual post-correction store, not a probe
        # taken before the correction was ever issued).
        logger.info("Seed %d: Re-probing corrected facts (%d queries)", seed, len(reprobe_turns))
        reprobe_results: list[ProbeResult] = []
        for p_turn in reprobe_turns:
            fact = facts_by_id.get(p_turn.fact_id or "")
            if not fact:
                continue
            res = execute_probe(
                adapter=adapter,
                llm_client=self.llm_client,
                user_id=user_id,
                fact=fact,
                store_lang=self.config.languages.store,
                probe_lang=self.config.languages.probe,
                query_text=p_turn.text,
            )
            reprobe_results.append(res)

        # 7. Final Snapshot (Snapshot B, taken after re-probe per BENCHMARK_SPEC.md Session K+2)
        store_final = session_runner.snapshot()
        with open(seed_dir / "store_final.json", "x", encoding="utf-8") as f:
            json.dump([m.to_dict() for m in store_final], f, ensure_ascii=False, indent=2)

        # 8. Write immutable JSONL run log
        run_log_path = seed_dir / "run_log.jsonl"
        with open(run_log_path, "x", encoding="utf-8") as f:
            meta = {
                "record_type": "metadata",
                "timestamp": time.time(),
                "experiment": self.config.experiment,
                "framework": self.config.framework,
                "seed": seed,
                "store_lang": self.config.languages.store,
                "probe_lang": self.config.languages.probe,
                "n_facts": len(facts),
                "adapter_settings": adapter_settings(self.config),
                "provenance": run_provenance(self.config),
            }
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")

            for r in plant_records + filler_records + correction_records:
                f.write(
                    json.dumps(
                        {"record_type": "turn_trace", "data": r},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            for pr in probe_results:
                f.write(
                    json.dumps(
                        {"record_type": "probe_result", "data": pr.to_dict()},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            for rpr in reprobe_results:
                f.write(
                    json.dumps(
                        {"record_type": "reprobe_result", "data": rpr.to_dict()},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        logger.info("Seed %d complete. Log written to %s", seed, run_log_path)
        return seed_dir
