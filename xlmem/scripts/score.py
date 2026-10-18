"""Offline scoring script: computes metrics from immutable run logs without GPU."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any
from xlmem.benchmark.facts import Fact, Memory, ProbeResult
from xlmem.scoring.duplication import compute_duplication_rate, compute_false_merge_rate
from xlmem.scoring.retrieval import (
    Entailer,
    compute_recall_at_k,
    compute_write_fidelity,
    compute_write_fidelity_lenient,
)
from xlmem.scoring.staleness import compute_staleness_rate

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("score")


def score_single_seed_dir(
    seed_dir: Path, facts: list[Fact], judge: Entailer | None = None
) -> dict[str, Any]:
    """Compute all metrics for a single seed directory from logs and snapshots.

    With a judge, also reports lenient (NLI) Write Fidelity next to strict WF.
    """
    store_plant_file = seed_dir / "store_after_plant.json"
    store_final_file = seed_dir / "store_final.json"
    run_log_file = seed_dir / "run_log.jsonl"

    if not run_log_file.exists():
        raise FileNotFoundError(f"Missing run log: {run_log_file}")

    # Load snapshots
    plant_memories: list[Memory] = []
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
    probe_results: list[ProbeResult] = []
    reprobe_results: list[ProbeResult] = []
    planted_ids: set[str] = set()
    with open(run_log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("record_type") == "probe_result":
                probe_results.append(ProbeResult.from_dict(record["data"]))
            elif record.get("record_type") == "reprobe_result":
                reprobe_results.append(ProbeResult.from_dict(record["data"]))
            elif record.get("record_type") == "turn_trace":
                trace = record.get("data", {})
                if trace.get("kind") == "plant" and trace.get("fact_id"):
                    planted_ids.add(trace["fact_id"])

    # WF is defined over facts that had a plant turn before the store_after_plant
    # snapshot. Distractors arrive later as filler and must not be in the
    # denominator (they would "pass" by sharing their base fact's value).
    planted_facts = [f for f in facts if f.id in planted_ids] if planted_ids else list(facts)

    # 1. WRITE FIDELITY (CHECKED FIRST!)
    wf, written_fact_ids = compute_write_fidelity(
        planted_facts=planted_facts, dumped_memories=plant_memories
    )
    written_set = set(written_fact_ids)

    # 2. RETRIEVAL RECALL (Evaluated on written facts to prevent conflation)
    recall_1_strict = compute_recall_at_k(facts=facts, probe_results=probe_results, k=1, mode="strict", eligible_fact_ids=written_set)
    recall_3_strict = compute_recall_at_k(facts=facts, probe_results=probe_results, k=3, mode="strict", eligible_fact_ids=written_set)
    recall_5_strict = compute_recall_at_k(facts=facts, probe_results=probe_results, k=5, mode="strict", eligible_fact_ids=written_set)

    recall_1_lenient = compute_recall_at_k(facts=facts, probe_results=probe_results, k=1, mode="lenient", eligible_fact_ids=written_set)
    recall_3_lenient = compute_recall_at_k(facts=facts, probe_results=probe_results, k=3, mode="lenient", eligible_fact_ids=written_set)
    recall_5_lenient = compute_recall_at_k(facts=facts, probe_results=probe_results, k=5, mode="lenient", eligible_fact_ids=written_set)

    # 3. CONSOLIDATION (DR and FMR)
    dr = compute_duplication_rate(planted_facts=facts, dumped_memories=final_memories or plant_memories)
    distractor_pairs = [(f, d) for f in facts for d in facts if d.distractor_of == f.id]
    fmr = compute_false_merge_rate(distractor_pairs=distractor_pairs, dumped_memories=final_memories or plant_memories)

    # 4. UPDATE (Staleness Rate) -- must use the post-correction reprobe_result
    # records, never probe_result (which predates the correction turn).
    corrected_facts = [f for f in facts if f.update_data is not None]
    invalid_metrics: dict[str, str] = {}
    sr: float | None
    if corrected_facts and not reprobe_results:
        # No re-probe was recorded, so SR is undefined -- report it as null rather
        # than a number (compute_staleness_rate would return 0.0, i.e. "every update
        # worked", for a phase that never ran).
        reason = (
            "no reprobe_result records in run_log.jsonl; log predates the re-probe "
            "phase fix. Re-run the experiment to measure SR."
        )
        logger.warning("%s: staleness_rate INVALID -- %s", seed_dir.name, reason)
        invalid_metrics["staleness_rate"] = reason
        sr = None
    else:
        sr = compute_staleness_rate(
            corrected_facts=corrected_facts, reprobe_results=reprobe_results
        )

    scores: dict[str, Any] = {
        "write_fidelity": wf,
        "recall_at_1_strict": recall_1_strict,
        "recall_at_3_strict": recall_3_strict,
        "recall_at_5_strict": recall_5_strict,
        "recall_at_1_lenient": recall_1_lenient,
        "recall_at_3_lenient": recall_3_lenient,
        "recall_at_5_lenient": recall_5_lenient,
        "duplication_rate": dr,
        "false_merge_rate": fmr,
        "staleness_rate": sr,
    }
    if judge is not None:
        scores["write_fidelity_lenient"], _ = compute_write_fidelity_lenient(
            planted_facts=planted_facts, dumped_memories=plant_memories, judge=judge
        )
    if invalid_metrics:
        scores["invalid_metrics"] = invalid_metrics

    # Save scores to seed_dir/scores.json without modifying run_log.jsonl
    scores_path = seed_dir / "scores.json"
    with open(scores_path, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2)

    logger.info("Scored %s -> WF: %.2f, Recall@1: %.2f (strict), DR: %.2f", seed_dir.name, wf, recall_1_strict, dr)
    return scores


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-score XLMem run logs offline without GPU.")
    parser.add_argument("--run", required=True, help="Path to experiment run directory (e.g. runs/mem0_qwen_hi2en).")
    parser.add_argument("--facts", default="data/facts_v1.yaml", help="Path to fact bank YAML.")
    parser.add_argument(
        "--nli",
        action="store_true",
        help="Also report lenient Write Fidelity using the multilingual NLI judge.",
    )
    args = parser.parse_args()

    run_path = Path(args.run)
    facts_path = Path(args.facts)

    if not run_path.exists():
        logger.error("Run path does not exist: %s", run_path)
        return 1

    # Load facts if available, otherwise construct dummy facts for smoke tests
    if facts_path.exists():
        from xlmem.benchmark.facts import load_facts
        facts = load_facts(facts_path)
    else:
        from xlmem.scripts.smoke import SMOKE_FACTS
        facts = SMOKE_FACTS

    # Check if this is a single seed dir or an experiment dir containing seed_*
    seed_dirs = [p for p in run_path.iterdir() if p.is_dir() and p.name.startswith("seed_")]
    if not seed_dirs:
        seed_dirs = [run_path]

    judge = None
    if args.nli:
        from xlmem.scoring.judge import NLIJudge

        judge = NLIJudge()
        if judge.mock_mode:
            # NLIJudge falls back to a token-overlap heuristic when the model fails
            # to load; never report that as NLI-based lenient WF.
            logger.error("NLI model unavailable; refusing to score lenient WF with the heuristic.")
            return 1

    for s_dir in seed_dirs:
        score_single_seed_dir(s_dir, facts=facts, judge=judge)

    return 0


if __name__ == "__main__":
    sys.exit(main())
