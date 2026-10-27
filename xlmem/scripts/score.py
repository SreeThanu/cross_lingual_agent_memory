"""Offline scoring script: computes metrics from immutable run logs without GPU."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any
from xlmem.benchmark.facts import Fact, Memory, ProbeResult
from xlmem.scoring.alias_bank import AliasBankV2, default_alias_bank_path, load_alias_bank_v2
from xlmem.scoring.aliases import ValueAliases, default_alias_path, load_value_aliases
from xlmem.scoring.matching import split_sentences
from xlmem.scoring.metrics_v3 import (
    false_merge_v3,
    plant_duplication_v3,
    recall_v3,
    staleness_v3,
    validation_report,
    write_fidelity_v3,
)
from xlmem.scoring.duplication import compute_false_merge_rate, compute_plant_duplication_rate
from xlmem.scoring.retrieval import compute_recall_at_k, compute_write_fidelity
from xlmem.scoring.staleness import InvalidReprobe, compute_staleness_v2, parse_reprobe_record
from xlmem.scoring.support import MatchBank

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("score")

# METRICS_SPEC.md §6. Bump whenever a metric's definition changes.
METRICS_VERSION = "2.1"
# Matching contract MC-1 (METRICS_SPEC §3.5). v2.1 stays reproducible via compute_seed_scores.
METRICS_VERSION_V3 = "3"


def compute_seed_scores(
    seed_dir: Path, facts: list[Fact], aliases: ValueAliases | None = None
) -> dict[str, Any]:
    """Compute all metrics for one seed directory from its logs and snapshots; writes nothing.

    Pure with respect to the run directory, so historical runs can be rescored into a
    separate location without touching their original scores.json.
    """
    store_plant_file = seed_dir / "store_after_plant.json"
    store_final_file = seed_dir / "store_final.json"
    run_log_file = seed_dir / "run_log.jsonl"

    if not run_log_file.exists():
        raise FileNotFoundError(f"Missing run log: {run_log_file}")

    # Load snapshots. Snapshot A missing is distinguished from an empty Snapshot A.
    plant_memories: list[Memory] | None = None
    if store_plant_file.exists():
        with open(store_plant_file, "r", encoding="utf-8") as f:
            plant_memories = [Memory.from_dict(m) for m in json.load(f)]

    final_memories: list[Memory] = []
    if store_final_file.exists():
        with open(store_final_file, "r", encoding="utf-8") as f:
            final_memories = [Memory.from_dict(m) for m in json.load(f)]

    # Load probe results from run_log.jsonl. probe_result is the pre-correction
    # (Session K) probe; reprobe_result is the post-correction (Session K+2)
    # re-probe -- these are DISTINCT phases and must not be conflated (see
    # BENCHMARK_SPEC.md Section 5). Staleness Rate is defined over the re-probe.
    # Every raw reprobe_result is kept: a malformed one becomes an InvalidReprobe rather
    # than being dropped, so it still counts toward SR v2's exactly-one-record rule.
    probe_results: list[ProbeResult] = []
    reprobe_results: list[ProbeResult | InvalidReprobe] = []
    planted_ids: list[str] = []
    corrected_ids: list[str] = []
    with open(run_log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rtype = record.get("record_type")
            if rtype == "reprobe_result":
                reprobe_results.append(parse_reprobe_record(record.get("data")))
                continue
            data = record.get("data") or {}
            if rtype == "probe_result":
                probe_results.append(ProbeResult.from_dict(data))
            elif rtype == "turn_trace" and data.get("fact_id"):
                if data.get("kind") == "plant":
                    planted_ids.append(str(data["fact_id"]))
                elif data.get("kind") == "correction":
                    corrected_ids.append(str(data["fact_id"]))

    # 1. WRITE FIDELITY (CHECKED FIRST!)
    wf, written_fact_ids = compute_write_fidelity(
        planted_facts=facts, dumped_memories=plant_memories or []
    )
    written_set = set(written_fact_ids)

    # 2. RETRIEVAL RECALL (Evaluated on written facts to prevent conflation)
    recall_1_strict = compute_recall_at_k(facts=facts, probe_results=probe_results, k=1, mode="strict", eligible_fact_ids=written_set)
    recall_3_strict = compute_recall_at_k(facts=facts, probe_results=probe_results, k=3, mode="strict", eligible_fact_ids=written_set)
    recall_5_strict = compute_recall_at_k(facts=facts, probe_results=probe_results, k=5, mode="strict", eligible_fact_ids=written_set)

    recall_1_lenient = compute_recall_at_k(facts=facts, probe_results=probe_results, k=1, mode="lenient", eligible_fact_ids=written_set)
    recall_3_lenient = compute_recall_at_k(facts=facts, probe_results=probe_results, k=3, mode="lenient", eligible_fact_ids=written_set)
    recall_5_lenient = compute_recall_at_k(facts=facts, probe_results=probe_results, k=5, mode="lenient", eligible_fact_ids=written_set)

    # 3. CONSOLIDATION: primary DR on Snapshot A over planted base facts (v2, D7); FMR unchanged.
    plant_dr, plant_dr_detail = compute_plant_duplication_rate(
        facts=facts, planted_fact_ids=planted_ids, plant_memories=plant_memories
    )
    distractor_pairs = [(f, d) for f in facts for d in facts if d.distractor_of == f.id]
    fmr = compute_false_merge_rate(
        distractor_pairs=distractor_pairs, dumped_memories=final_memories or plant_memories or []
    )

    # 4. UPDATE: SR v2 (D6) -- corrected (from the log) ∩ written ∩ valid re-probe.
    sr = compute_staleness_v2(
        facts=facts,
        corrected_fact_ids=corrected_ids,
        written_fact_ids=written_set if plant_memories is not None else None,
        reprobe_results=reprobe_results,
        aliases=aliases,
    )

    invalid_metrics: dict[str, str] = {}
    if plant_dr is None:
        invalid_metrics["plant_duplication_rate"] = str(plant_dr_detail["invalid_reason"])
    if sr["staleness_rate"] is None:
        invalid_metrics["staleness_rate"] = str(sr["invalid_reason"])
        invalid_metrics["miss_rate"] = str(sr["invalid_reason"])
        logger.warning("%s: staleness_rate INVALID -- %s", seed_dir.name, sr["invalid_reason"])

    scores: dict[str, Any] = {
        "metrics_version": METRICS_VERSION,
        "write_fidelity": wf,
        "recall_at_1_strict": recall_1_strict,
        "recall_at_3_strict": recall_3_strict,
        "recall_at_5_strict": recall_5_strict,
        "recall_at_1_lenient": recall_1_lenient,
        "recall_at_3_lenient": recall_3_lenient,
        "recall_at_5_lenient": recall_5_lenient,
        "plant_duplication_rate": plant_dr,
        "false_merge_rate": fmr,
        "staleness_rate": sr["staleness_rate"],
        "miss_rate": sr["miss_rate"],
        "write_ineligible_rate": sr["write_ineligible_rate"],
        "eligible_corrections": sr["eligible_corrections"],
        "updated_count": sr["updated_count"],
        "stale_count": sr["stale_count"],
        "miss_count": sr["miss_count"],
        "write_ineligible_count": sr["write_ineligible_count"],
        "missing_or_invalid_reprobe_count": sr["missing_or_invalid_reprobe_count"],
        "staleness_detail": {
            "corrected_count": sr["corrected_count"],
            "unattributed_invalid_reprobes": sr["unattributed_invalid_reprobes"],
            "per_fact": sr["per_fact"],
        },
        "plant_duplication_detail": plant_dr_detail,
    }
    if invalid_metrics:
        scores["invalid_metrics"] = invalid_metrics
    return scores


def _read_seed_inputs(seed_dir: Path) -> dict[str, Any]:
    """Raw inputs of one seed dir for v3: snapshots as texts, log records by kind."""
    run_log_file = seed_dir / "run_log.jsonl"
    if not run_log_file.exists():
        raise FileNotFoundError(f"Missing run log: {run_log_file}")

    def texts(name: str) -> list[str] | None:
        path = seed_dir / name
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return [Memory.from_dict(m).text for m in json.load(f)]

    out: dict[str, Any] = {
        "plant": texts("store_after_plant.json"), "final": texts("store_final.json") or [],
        "metadata": {}, "planted": [], "corrected": [], "distractors": [],
        "probes": [], "reprobes": [],
    }  # fmt: skip
    with open(run_log_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            rtype = record.get("record_type")
            if rtype == "metadata":
                out["metadata"] = record
            elif rtype == "reprobe_result":
                out["reprobes"].append(parse_reprobe_record(record.get("data")))
            elif rtype == "probe_result":
                out["probes"].append(ProbeResult.from_dict(record.get("data") or {}))
            elif rtype == "turn_trace":
                data = record.get("data") or {}
                fid, kind = data.get("fact_id"), data.get("kind")
                if fid and kind == "plant":
                    out["planted"].append(str(fid))
                elif fid and kind == "correction":
                    out["corrected"].append(str(fid))
                elif fid and kind == "filler":
                    out["distractors"].append(str(fid))
    return out


def compute_seed_scores_v3(
    seed_dir: Path, facts: list[Fact], alias_bank: AliasBankV2 | None = None
) -> dict[str, Any]:
    """Metrics v3 (matching contract MC-1) for one seed dir; writes nothing."""
    inp = _read_seed_inputs(seed_dir)
    meta = inp["metadata"]
    store_lang = str(meta.get("store_lang") or "en")
    bank = MatchBank(facts, alias_bank)
    plant = inp["plant"]
    snap = {tuple(s) for t in plant or [] for s in split_sentences(t)}

    wf = write_fidelity_v3(bank, inp["planted"], plant, store_lang)
    dr = plant_duplication_v3(bank, inp["planted"], plant, store_lang)
    recall = recall_v3(bank, wf["written"], inp["probes"], store_lang, snap)
    written = set(wf["written"]) if plant is not None else None
    sr = staleness_v3(bank, inp["corrected"], written, set(wf["provisional"]), inp["reprobes"])
    fmr = false_merge_v3(bank, inp["distractors"], plant, inp["final"], store_lang)
    validation = validation_report(wf, dr, recall, sr, fmr)

    invalid: dict[str, str] = {}
    for key, rep in (("write_fidelity", wf), ("plant_duplication_rate", dr),
                     ("false_merge_rate", fmr)):  # fmt: skip
        if rep[key] is None:
            invalid[key] = str(rep["invalid_reason"])
    if sr["staleness_rate"] is None:
        invalid["staleness_rate"] = invalid["miss_rate"] = str(sr["invalid_reason"])

    scores: dict[str, Any] = {
        "metrics_version": METRICS_VERSION_V3,
        "write_fidelity": wf["write_fidelity"],
        "wf_confirmed": wf["wf_confirmed"],
        "plant_duplication_rate": dr["plant_duplication_rate"],
        "false_merge_rate": fmr["false_merge_rate"],
        "staleness_rate": sr["staleness_rate"],
        "miss_rate": sr["miss_rate"],
        "write_ineligible_rate": sr["write_ineligible_rate"],
    }
    for k in (1, 3, 5):
        scores[f"recall_at_{k}_strict"] = recall[f"recall_at_{k}"]
        scores[f"distractor_retrieval_at_{k}"] = recall[f"distractor_retrieval_at_{k}"]
    sr_counts = (
        "eligible_corrections",
        "updated_count",
        "stale_count",
        "miss_count",
        "write_ineligible_count",
        "missing_or_invalid_reprobe_count",
        "unresolved_count",
    )
    for key in sr_counts:
        scores[key] = sr[key]
    scores["validation"] = validation
    scores["detail"] = {
        "store_lang": store_lang,
        "write_fidelity": wf,
        "plant_duplication": dr,
        "recall": recall,
        "staleness": sr,
        "false_merge": fmr,
        "alias_bank": {
            "path": getattr(alias_bank, "path", None),
            "sha256": getattr(alias_bank, "sha256", None),
        },
    }
    if invalid:
        scores["invalid_metrics"] = invalid
    return scores


def _refusal(path: Path) -> str:
    return f"Refusing to overwrite existing {path}; pass overwrite=True (CLI: --overwrite)"


def score_single_seed_dir(
    seed_dir: Path,
    facts: list[Fact],
    aliases: ValueAliases | None = None,
    overwrite: bool = False,
    metrics_version: str = METRICS_VERSION,
    alias_bank: AliasBankV2 | None = None,
) -> dict[str, Any]:
    """Compute all metrics for a single seed directory and write seed_dir/scores.json.

    Refuses (FileExistsError) if scores.json already exists, unless overwrite=True, so the
    original scores of a historical run can't be replaced by accident. `metrics_version`
    selects the v2.1 path (default, for reproducing existing results) or "3".
    """
    scores_path = seed_dir / "scores.json"
    if scores_path.exists() and not overwrite:
        raise FileExistsError(_refusal(scores_path))
    if metrics_version == METRICS_VERSION_V3:
        scores = compute_seed_scores_v3(seed_dir, facts=facts, alias_bank=alias_bank)
    elif metrics_version == METRICS_VERSION:
        scores = compute_seed_scores(seed_dir, facts=facts, aliases=aliases)
    else:
        raise ValueError(f"unknown metrics_version {metrics_version!r}")

    # Save scores to seed_dir/scores.json without modifying run_log.jsonl
    with open(scores_path, "w" if overwrite else "x", encoding="utf-8") as f:
        json.dump(scores, f, indent=2, ensure_ascii=False)

    logger.info(
        "Scored %s (metrics v%s) -> WF: %s, Recall@1: %s (strict), plant DR: %s, SR: %s",
        seed_dir.name, scores["metrics_version"], scores["write_fidelity"],
        scores["recall_at_1_strict"], scores["plant_duplication_rate"], scores["staleness_rate"],
    )  # fmt: skip
    return scores


def load_aliases_for(
    facts: list[Fact], facts_path: Path, aliases_arg: str | None
) -> ValueAliases | None:
    """Load the alias sidecar given on the CLI, or the default one next to the fact bank."""
    alias_path = Path(aliases_arg) if aliases_arg else default_alias_path(facts_path)
    if not alias_path.exists():
        if aliases_arg:
            raise FileNotFoundError(f"Alias file not found: {alias_path}")
        logger.warning(
            "No alias file at %s: non-English re-probes will be invalid for SR", alias_path
        )
        return None
    return load_value_aliases(alias_path, facts, facts_path)


def load_alias_bank_for(
    facts: list[Fact], facts_path: Path, alias_bank_arg: str | None
) -> AliasBankV2 | None:
    """Load the v3 alias bank given on the CLI, or the default one next to the fact bank."""
    path = Path(alias_bank_arg) if alias_bank_arg else default_alias_bank_path(facts_path)
    if not path.exists():
        if alias_bank_arg:
            raise FileNotFoundError(f"Alias bank not found: {path}")
        logger.warning("No v3 alias bank at %s: only English canonical values will match", path)
        return None
    return load_alias_bank_v2(path, facts, facts_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-score XLMem run logs offline without GPU.")
    parser.add_argument("--run", required=True, help="Path to experiment run directory (e.g. runs/mem0_qwen_hi2en).")
    parser.add_argument("--facts", default="data/facts_v1.yaml", help="Path to fact bank YAML.")
    parser.add_argument(
        "--aliases",
        default=None,
        help="SR alias sidecar (default: data/aliases/<facts stem>.aliases.yaml).",
    )
    parser.add_argument(
        "--metrics-version",
        choices=[METRICS_VERSION_V3, METRICS_VERSION],
        default=METRICS_VERSION_V3,
        help="Metric definitions to apply (default: 3; 2.1 reproduces earlier results).",
    )
    parser.add_argument(
        "--alias-bank",
        default=None,
        help="v3 alias bank (default: data/aliases/<facts stem>.aliases.v2.yaml).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing scores.json files (default: refuse and write nothing).",
    )
    args = parser.parse_args()

    run_path = Path(args.run)
    facts_path = Path(args.facts)

    if not run_path.exists():
        logger.error("Run path does not exist: %s", run_path)
        return 1

    # Load facts if available, otherwise construct dummy facts for smoke tests
    aliases: ValueAliases | None = None
    alias_bank: AliasBankV2 | None = None
    if facts_path.exists():
        from xlmem.benchmark.facts import load_facts
        facts = load_facts(facts_path)
        if args.metrics_version == METRICS_VERSION_V3:
            alias_bank = load_alias_bank_for(facts, facts_path, args.alias_bank)
        else:
            aliases = load_aliases_for(facts, facts_path, args.aliases)
    else:
        from xlmem.scripts.smoke import SMOKE_FACTS
        facts = SMOKE_FACTS

    # Check if this is a single seed dir or an experiment dir containing seed_*
    seed_dirs = sorted(p for p in run_path.iterdir() if p.is_dir() and p.name.startswith("seed_"))
    if not seed_dirs:
        seed_dirs = [run_path]

    # Refuse before scoring anything, so a refusal never leaves a run half re-scored.
    existing = [s / "scores.json" for s in seed_dirs if (s / "scores.json").exists()]
    if existing and not args.overwrite:
        for path in existing:
            logger.error(_refusal(path))
        return 2

    for s_dir in seed_dirs:
        score_single_seed_dir(
            s_dir,
            facts=facts,
            aliases=aliases,
            overwrite=args.overwrite,
            metrics_version=args.metrics_version,
            alias_bank=alias_bank,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
