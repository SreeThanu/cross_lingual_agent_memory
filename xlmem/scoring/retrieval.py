"""Scoring logic for Write Fidelity, XL-Recall@k, LTG, and Encoding Asymmetry."""

from __future__ import annotations

from typing import Sequence
from xlmem.benchmark.facts import Fact, Memory, ProbeResult
from xlmem.scoring.judge import strict_match


def compute_write_fidelity(
    planted_facts: Sequence[Fact],
    dumped_memories: Sequence[Memory],
) -> tuple[float, list[str]]:
    """Compute Write Fidelity (WF).

    WF = (facts represented in dump) / (total planted facts).
    Returns the fidelity score and the list of fact IDs successfully written.

    CRITICAL RULE: Check Write Fidelity FIRST. A fact missing from dump()
    is a WRITE failure, not a retrieval failure.
    """
    if not planted_facts:
        return 0.0, []

    written_fact_ids: list[str] = []
    dump_texts = [m.text for m in dumped_memories]

    for fact in planted_facts:
        # Check if fact's canonical value appears in any memory
        found = False
        aliases = list(fact.surface.values())
        for text in dump_texts:
            if strict_match(fact.value, text, aliases=aliases):
                found = True
                break
        if found:
            written_fact_ids.append(fact.id)

    score = len(written_fact_ids) / len(planted_facts)
    return score, written_fact_ids


def compute_recall_at_k(
    facts: Sequence[Fact],
    probe_results: Sequence[ProbeResult],
    k: int = 5,
    mode: str = "strict",
    eligible_fact_ids: set[str] | None = None,
) -> float:
    """Compute Recall@k.

    Args:
        facts: Ground truth facts.
        probe_results: Probe results recorded by the runner.
        k: Maximum retrieved candidates to consider.
        mode: "strict" or "lenient".
        eligible_fact_ids: If provided, only evaluate facts in this set
            (e.g., facts that passed Write Fidelity).

    Returns:
        Recall@k fraction between 0.0 and 1.0.
    """
    if eligible_fact_ids is not None:
        eval_facts = [f for f in facts if f.id in eligible_fact_ids]
    else:
        eval_facts = list(facts)

    if not eval_facts:
        return 0.0

    probes_by_id = {p.fact_id: p for p in probe_results}
    hits = 0

    for fact in eval_facts:
        probe = probes_by_id.get(fact.id)
        if not probe:
            continue

        # Check top-k retrieved memories
        top_k = probe.retrieved[:k]
        aliases = list(fact.surface.values())
        hit = False

        for mem in top_k:
            if mode == "strict":
                if strict_match(fact.value, mem.text, aliases=aliases):
                    hit = True
                    break
            else:
                # Lenient hit flag from probe result or text matching
                if probe.hit_lenient or strict_match(fact.value, mem.text, aliases=aliases):
                    hit = True
                    break

        if not hit and (probe.hit_strict if mode == "strict" else probe.hit_lenient):
            hit = True

        if hit:
            hits += 1

    return hits / len(eval_facts)


def compute_ltg(
    same_lang_recalls: Sequence[float],
    cross_lang_recalls: Sequence[float],
) -> float:
    """Compute Language Transfer Gap (LTG).

    LTG = mean(same_lang_recalls) - mean(cross_lang_recalls).
    Positive value indicates performance degradation under language switching.
    """
    if not same_lang_recalls or not cross_lang_recalls:
        return 0.0

    mean_same = sum(same_lang_recalls) / len(same_lang_recalls)
    mean_cross = sum(cross_lang_recalls) / len(cross_lang_recalls)
    return mean_same - mean_cross


def compute_encoding_asymmetry(
    recall_stored_hi: float,
    recall_stored_en: float,
) -> float:
    """Compute Encoding Asymmetry (EA).

    EA = recall(stored-hi) - recall(stored-en).
    """
    return recall_stored_hi - recall_stored_en
