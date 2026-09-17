"""Experiment runner: orchestrates full multi-seed bilingual memory experiments.

Hard Rules:
1. Logs are append-only and immutable.
2. The runner records raw outputs; it NEVER judges.
3. Every model call routes strictly through LLMClient.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
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

        run_dirs: list[Path] = []
        for seed in self.config.seeds:
            logger.info("Starting experiment %s with seed %d", self.config.experiment, seed)
            run_dir = self.run_single_seed(facts=facts, seed=seed)
            run_dirs.append(run_dir)

        return run_dirs

    def run_single_seed(self, facts: list[Fact], seed: int) -> Path:
        """Execute experiment for a single seed and write immutable run artifacts."""
        seed_dir = self.output_base / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)

        user_id = f"user_{self.config.experiment}_{seed}"
        adapter: MemoryAdapter = get_adapter(self.config.framework)
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

        # 2. Phase 1: Plant
        logger.info("Seed %d: Ingesting %d plant turns", seed, len(plant_turns))
        plant_records = session_runner.run_session(plant_turns)
        session_runner.consolidate()
        store_after_plant = session_runner.snapshot()

        with open(seed_dir / "store_after_plant.json", "w", encoding="utf-8") as f:
            json.dump([m.to_dict() for m in store_after_plant], f, ensure_ascii=False, indent=2)

        # 3. Phase 2: Filler / Distractors
        logger.info("Seed %d: Ingesting %d filler turns", seed, len(filler_turns))
        filler_records = session_runner.run_session(filler_turns)
        session_runner.consolidate()

        # 4. Phase 3: Probing
        logger.info("Seed %d: Probing memory (%d queries)", seed, len(probe_turns))
        probe_results: list[ProbeResult] = []
        facts_by_id = {f.id: f for f in facts}

        for p_turn in probe_turns:
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

        # 6. Final Snapshot
        store_final = session_runner.snapshot()
        with open(seed_dir / "store_final.json", "w", encoding="utf-8") as f:
            json.dump([m.to_dict() for m in store_final], f, ensure_ascii=False, indent=2)

        # 7. Write immutable JSONL run log
        run_log_path = seed_dir / "run_log.jsonl"
        with open(run_log_path, "w", encoding="utf-8") as f:
            meta = {
                "record_type": "metadata",
                "timestamp": time.time(),
                "experiment": self.config.experiment,
                "framework": self.config.framework,
                "seed": seed,
                "store_lang": self.config.languages.store,
                "probe_lang": self.config.languages.probe,
                "n_facts": len(facts),
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

        logger.info("Seed %d complete. Log written to %s", seed, run_log_path)
        return seed_dir
