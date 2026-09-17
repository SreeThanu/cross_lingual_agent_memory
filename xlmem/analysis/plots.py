"""Plot generation utilities for paper figures."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import matplotlib.pyplot as plt
import pandas as pd


def plot_metric_comparison(
    data: pd.DataFrame,
    metric_col: str,
    group_col: str,
    output_path: str | Path,
    title: str = "Metric Comparison",
) -> None:
    """Generate a bar plot with error bars across frameworks and language conditions."""
    fig, ax = plt.subplots(figsize=(8, 5))

    groups = data[group_col].unique()
    x = range(len(groups))

    means = [data[data[group_col] == g]["Mean"].mean() for g in groups]
    stds = [data[data[group_col] == g]["Std"].mean() for g in groups]

    ax.bar(x, means, yerr=stds, capsize=5, color="steelblue", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(groups, rotation=15)
    ax.set_ylabel(metric_col)
    ax.set_title(title)
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    plt.tight_layout()
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(p, dpi=300)
    plt.close()
