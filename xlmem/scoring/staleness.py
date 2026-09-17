"""Scoring logic for Staleness Rate (SR) following memory updates."""

from __future__ import annotations

from typing import Sequence
from xlmem.benchmark.facts import Fact, ProbeResult
from xlmem.scoring.judge import strict_match


def compute_staleness_rate(
    corrected_facts: Sequence[Fact],
    reprobe_results: Sequence[ProbeResult],
) -> float:
    """Compute Staleness Rate (SR).

    SR = (corrected facts whose reprobe returns superseded value) / (total corrected facts).
    Operation tested: UPDATE.
    """
    if not corrected_facts:
        return 0.0

    reprobes_by_id = {r.fact_id: r for r in reprobe_results}
    stale_count = 0

    for fact in corrected_facts:
        if fact.update_data is None:
            continue

        probe = reprobes_by_id.get(fact.id)
        if not probe:
            continue

        old_value = fact.value
        updated_value = fact.update_data.get("updated_value", "")
        response = probe.response

        # Check if old value is still present in response
        has_old = strict_match(old_value, response)
        has_new = strict_match(updated_value, response) if updated_value else False

        # If it returns old value (even alongside new value), it is stale / contradictory
        if has_old or (not has_new and not probe.hit_strict):
            stale_count += 1

    return stale_count / len(corrected_facts)
