"""Aggregate run results across seeds into publication tables in results/."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from xlmem.analysis.aggregate import aggregate_seed_metrics, format_results_table

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("aggregate")


def aggregate_runs(runs_dir: Path, out_dir: Path) -> int:
    """Read scores from all run subdirectories and emit aggregated tables."""
    if not runs_dir.exists():
        logger.error("Runs directory does not exist: %s", runs_dir)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    exp_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]

    summary_rows = []

    for exp_dir in exp_dirs:
        seed_dirs = [s for s in exp_dir.iterdir() if s.is_dir() and s.name.startswith("seed_")]
        if not seed_dirs:
            # Check if this dir directly contains scores.json
            if (exp_dir / "scores.json").exists():
                seed_dirs = [exp_dir]
            else:
                continue

        seed_scores: list[dict[str, float]] = []
        for s_dir in seed_dirs:
            score_file = s_dir / "scores.json"
            if score_file.exists():
                with open(score_file, "r", encoding="utf-8") as f:
                    seed_scores.append(json.load(f))

        if not seed_scores:
            continue

        aggregated = aggregate_seed_metrics(seed_scores)
        df = format_results_table(aggregated)
        df["Experiment"] = exp_dir.name

        csv_path = out_dir / f"{exp_dir.name}_aggregated.csv"
        df.to_csv(csv_path, index=False)
        logger.info("Saved aggregated results for %s to %s", exp_dir.name, csv_path)
        summary_rows.append(df)

    logger.info("Aggregation completed for %d experiment(s).", len(summary_rows))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate XLMem experiment results over seeds.")
    parser.add_argument("--runs", default="runs", help="Directory containing run logs.")
    parser.add_argument("--out", default="results", help="Directory to save aggregated tables.")
    args = parser.parse_args()

    return aggregate_runs(Path(args.runs), Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
