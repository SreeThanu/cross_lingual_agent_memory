"""Aggregates metrics across multiple seeds, computing mean +/- standard deviation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd


def aggregate_seed_metrics(seed_metrics: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Compute mean and sample standard deviation across seeds for all metrics.

    CRITICAL INVARIANT: Never report a single seed. Minimum 3 seeds required.
    """
    if not seed_metrics:
        return {}

    keys = seed_metrics[0].keys()
    aggregated: dict[str, dict[str, float]] = {}

    for k in keys:
        values = [m[k] for m in seed_metrics if k in m]
        if not values:
            continue
        arr = np.array(values, dtype=np.float64)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        aggregated[k] = {"mean": mean_val, "std": std_val, "n_seeds": len(arr)}

    return aggregated


def format_results_table(aggregated: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Format aggregated metrics into a presentation DataFrame with mean +/- std."""
    rows = []
    for metric, stats in aggregated.items():
        rows.append({
            "Metric": metric,
            "Mean": stats["mean"],
            "Std": stats["std"],
            "Reported": f"{stats['mean']:.3f} ± {stats['std']:.3f}",
            "N_Seeds": stats["n_seeds"],
        })
    return pd.DataFrame(rows)
