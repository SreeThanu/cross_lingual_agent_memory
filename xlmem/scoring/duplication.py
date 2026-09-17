"""Scoring logic for Duplication Rate (DR) and False Merge Rate (FMR)."""

from __future__ import annotations

from typing import Sequence
from xlmem.benchmark.facts import Fact, Memory
from xlmem.scoring.judge import strict_match


def compute_duplication_rate(
    planted_facts: Sequence[Fact],
    dumped_memories: Sequence[Memory],
) -> float:
    """Compute Duplication Rate (DR) on store snapshot.

    DR = (1 / |F|) * sum_{f in F} max(0, N_records(f) - 1).
    A score of 0.0 indicates no duplicate records.
    """
    if not planted_facts:
        return 0.0

    total_excess = 0
    dump_texts = [m.text for m in dumped_memories]

    for fact in planted_facts:
        aliases = list(fact.surface.values())
        matches = 0
        for text in dump_texts:
            if strict_match(fact.value, text, aliases=aliases):
                matches += 1

        if matches > 1:
            total_excess += matches - 1

    return total_excess / len(planted_facts)


def compute_false_merge_rate(
    distractor_pairs: Sequence[tuple[Fact, Fact]],
    dumped_memories: Sequence[Memory],
) -> float:
    """Compute False Merge Rate (FMR).

    FMR = (distractor pairs collapsed into one memory record) / (total pairs).
    Detects over-eager consolidation where distinct facts are merged.
    """
    if not distractor_pairs:
        return 0.0

    false_merges = 0
    dump_texts = [m.text for m in dumped_memories]

    for base_fact, dist_fact in distractor_pairs:
        collapsed = False

        # Case 1: Value-shift near miss (different values, e.g. peanuts vs walnuts)
        if base_fact.value != dist_fact.value:
            for text in dump_texts:
                has_base = strict_match(base_fact.value, text, aliases=list(base_fact.surface.values()))
                has_dist = strict_match(dist_fact.value, text, aliases=list(dist_fact.surface.values()))
                if has_base and has_dist:
                    collapsed = True
                    break

        # Case 2: Entity-shift near miss (same value, different entities, e.g. user vs user_sister)
        else:
            base_ent = base_fact.entity.replace("user_", "")
            dist_ent = dist_fact.entity.replace("user_", "")
            for text in dump_texts:
                has_val = strict_match(base_fact.value, text, aliases=list(base_fact.surface.values()))
                if has_val:
                    has_base_ent = strict_match(base_ent, text)
                    has_dist_ent = strict_match(dist_ent, text)
                    if has_base_ent and has_dist_ent:
                        collapsed = True
                        break

        if collapsed:
            false_merges += 1

    return false_merges / len(distractor_pairs)
