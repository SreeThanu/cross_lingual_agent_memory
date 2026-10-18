"""Hindi matching proposal: normalization, value aliases, and lenient (NLI) Write Fidelity.

Fixture: the real store_after_plant.json from runs/phase0_pilot_mem0_hihi/seed_11
(Mem0 + Qwen2.5-7B, hi->hi, 2026-09-19). Expected values are hand-judged from that
dump, not produced by running the scorer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xlmem.benchmark.facts import Fact, Memory, load_facts
from xlmem.scoring.judge import normalize_text, strict_match
from xlmem.scoring.retrieval import compute_write_fidelity, compute_write_fidelity_lenient

FIXTURE = Path(__file__).parent / "fixtures" / "pilot_mem0_hihi_seed11_store_after_plant.json"
FACT_BANK = Path(__file__).parent.parent / "data" / "facts_v1.yaml"

# Hand-judged against the dump: was the planted fact stored with the correct value?
#   f_001: stored as "Has a serious allergy to moong dal" -- Mem0 mistranslated
#          मूंगफली (peanut) as moong dal. A genuine WRITE failure.
#   f_005: stored as "... गोल्डन रिट्रवर कुत्ता है" -- correct fact, but spelled
#          रिट्रवर where the authored surface has रिट्रीवर. Strict misses it.
#   All other 15 facts are stored with the correct value (12 in Hindi; f_003,
#   f_008, f_017 translated to English by Mem0).
TRULY_WRITTEN = {f"f_{i:03d}" for i in range(1, 18)} - {"f_001"}
STRICT_EXPECTED = TRULY_WRITTEN - {"f_005"}


@pytest.fixture(scope="module")
def planted_facts() -> list[Fact]:
    # The 17 base facts are the ones with a plant turn; distractors arrive as filler.
    return [f for f in load_facts(FACT_BANK) if f.distractor_of is None]


@pytest.fixture(scope="module")
def dump() -> list[Memory]:
    with open(FIXTURE, encoding="utf-8") as f:
        return [Memory.from_dict(m) for m in json.load(f)]


def test_normalize_keeps_devanagari_vowel_signs() -> None:
    assert normalize_text("वर्तमान में पुणे में रहता हूँ।") == "वर्तमान में पुणे में रहता हूँ"


def test_normalize_folds_nukta() -> None:
    assert normalize_text("फ़िल्टर कॉफ़ी") == normalize_text("फिल्टर कॉफी")


def test_strict_match_is_whole_token() -> None:
    assert strict_match("पुणे", "मैं पुणे में रहता हूँ")
    assert not strict_match("पुणे", "पुणेरी खाना")
    assert not strict_match("visa", "That is advisable")
    assert strict_match("peanuts", "User has a peanut allergy")  # plural handling kept


def test_strict_write_fidelity_on_real_hihi_dump(
    planted_facts: list[Fact], dump: list[Memory]
) -> None:
    wf, written = compute_write_fidelity(planted_facts, dump)
    assert set(written) == STRICT_EXPECTED
    assert wf == pytest.approx(15 / 17)


class _HandLabelledEntailer:
    """Stub NLI judge: entails only the pairs a human judged as entailment for this dump."""

    def __init__(self, pairs: set[tuple[str, str]]) -> None:
        self.pairs = pairs
        self.calls = 0

    def is_entailed(self, premise: str, hypothesis: str) -> bool:
        self.calls += 1
        return (premise, hypothesis) in self.pairs


def test_lenient_write_fidelity_recovers_spelling_variant_only(
    planted_facts: list[Fact], dump: list[Memory]
) -> None:
    f_005 = next(f for f in planted_facts if f.id == "f_005")
    variant = next(m.text for m in dump if "रिट्रवर" in m.text)
    judge = _HandLabelledEntailer({(variant, f_005.surface["hi"])})

    wf, written = compute_write_fidelity_lenient(planted_facts, dump, judge)

    assert set(written) == TRULY_WRITTEN
    assert "f_001" not in written  # moong dal does not entail a peanut allergy
    assert wf == pytest.approx(16 / 17)
    # NLI is only consulted for facts strict matching missed (f_001, f_005).
    n_surfaces = len(f_005.surface)
    assert judge.calls <= 2 * len(dump) * n_surfaces
