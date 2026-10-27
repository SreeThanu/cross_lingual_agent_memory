"""Scoring modules for XLMem metrics."""

from xlmem.scoring.aliases import ValueAliases, load_value_aliases
from xlmem.scoring.duplication import (
    compute_duplication_rate,
    compute_false_merge_rate,
    compute_plant_duplication_rate,
)
from xlmem.scoring.judge import NLIJudge, normalize_text, strict_match
from xlmem.scoring.retrieval import (
    compute_encoding_asymmetry,
    compute_ltg,
    compute_recall_at_k,
    compute_write_fidelity,
)
from xlmem.scoring.staleness import classify_reprobe, compute_staleness_rate, compute_staleness_v2

__all__ = [
    "compute_write_fidelity",
    "compute_recall_at_k",
    "compute_ltg",
    "compute_encoding_asymmetry",
    "compute_plant_duplication_rate",
    "compute_duplication_rate",
    "compute_false_merge_rate",
    "compute_staleness_v2",
    "classify_reprobe",
    "compute_staleness_rate",
    "ValueAliases",
    "load_value_aliases",
    "strict_match",
    "normalize_text",
    "NLIJudge",
]
