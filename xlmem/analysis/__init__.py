"""Analysis and aggregation modules for XLMem."""

from xlmem.analysis.aggregate import aggregate_seed_metrics, format_results_table
from xlmem.analysis.plots import plot_metric_comparison

__all__ = ["aggregate_seed_metrics", "format_results_table", "plot_metric_comparison"]
