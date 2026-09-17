"""Offline scoring script: computes metrics from immutable run logs without GPU."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from xlmem.benchmark.facts import Fact, Memory, ProbeResult
from xlmem.scoring.duplication import compute_duplication_rate, compute_false_merge_rate
from xlmem.scoring.retrieval import compute_recall_at_k, compute_write_fidelity
from xlmem.scoring.staleness import compute_staleness_rate

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("score")


def score_single_seed_dir(seed_dir: Path, facts: list[Fact]) -> dict[str, float]:
    """Compute all metrics for a single seed directory from logs and snapshots."""
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

    # Load probe results from run_log.jsonl
    probe_results: list[ProbeResult] = []
    with open(run_log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("record_type") == "probe_result":
                probe_results.append(ProbeResult.from_dict(record["data"]))

    # 1. WRITE FIDELITY (CHECKED FIRST!)
    wf, written_fact_ids = compute_write_fidelity(planted_facts=facts, dumped_memories=plant_memories)
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

    # 4. UPDATE (Staleness Rate)
    corrected_facts = [f for f in facts if f.update_data is not None]
    sr = compute_staleness_rate(corrected_facts=corrected_facts, reprobe_results=probe_results)

    scores = {
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

    for s_dir in seed_dirs:
        score_single_seed_dir(s_dir, facts=facts)

    return 0


if __name__ == "__main__":
    sys.exit(main())
