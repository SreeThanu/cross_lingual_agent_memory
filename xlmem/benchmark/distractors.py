"""Logic for near-miss distractor pairs used to evaluate False Merge Rate (FMR)."""

from __future__ import annotations

from typing import Iterable
from xlmem.benchmark.facts import Fact


def find_distractor_pairs(facts: Iterable[Fact]) -> list[tuple[Fact, Fact]]:
    """Identify base fact and distractor fact pairs from a collection of facts.

    Args:
        facts: Collection of facts.

    Returns:
        A list of (base_fact, distractor_fact) tuples.
    """
    facts_by_id: dict[str, Fact] = {f.id: f for f in facts}
    pairs: list[tuple[Fact, Fact]] = []

    for fact in facts:
        if fact.distractor_of is not None:
            base_id = fact.distractor_of
            if base_id in facts_by_id:
                pairs.append((facts_by_id[base_id], fact))

    return pairs
