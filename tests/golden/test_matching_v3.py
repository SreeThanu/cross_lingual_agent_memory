# ruff: noqa: E501  (golden rows are kept one per line so they read as the proposal's tables)
"""Golden tests for metrics v3 (matching contract MC-1, docs/proposals/D1_MATCHING_CONTRACT.md
revision 3). Expected values are hand-computed from the contract; never model-generated.

Every test that corresponds to a row of the proposal also asserts the *old* (v2.1) result
recorded in the proposal, so the test documents why v3 differs and fails if v3 regresses to it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from xlmem.benchmark.facts import Fact, Memory, ProbeResult, load_facts
from xlmem.benchmark.generator import DEFAULT_FILLER_TURNS
from xlmem.scoring.alias_bank import (
    alias_bank_from_mapping,
    authored_text,
    load_alias_bank_v2,
    locate_span,
    validate_contract_bank,
)
from xlmem.scoring.duplication import compute_false_merge_rate, compute_plant_duplication_rate
from xlmem.scoring.judge import strict_match
from xlmem.scoring.matching import (
    AMBIGUOUS,
    PAST,
    TOKENIZER_VERSION,
    analyze,
    lexicon_for,
    make_target,
    normalize,
    tokenize,
)
from xlmem.scoring.metrics_v3 import (
    BASE_LOST,
    JOINT,
    LOST,
    OVERWRITTEN,
    SEPARATED,
    WRONG_PERSON,
    classify_pair_v3,
    classify_reprobe_v3,
    false_merge_v3,
    plant_duplication_v3,
    recall_v3,
    staleness_v3,
    validation_report,
    write_fidelity_v3,
)
from xlmem.scoring.retrieval import compute_recall_at_k, compute_write_fidelity
from xlmem.scoring.staleness import classify_reprobe as classify_v21
from xlmem.scoring.staleness import compute_staleness_v2
from xlmem.scoring.support import (
    DISTRACTOR,
    LATER,
    NONE,
    NOT_SUPPORTED,
    SNAPSHOT_A,
    SUPPORTED,
    UNRESOLVED,
    USER,
    MatchBank,
    attribute_subject,
    support,
)

REPO = Path(__file__).resolve().parents[2]
FACTS_V1 = REPO / "data" / "facts_v1.yaml"
ALIASES_V2 = REPO / "data" / "aliases" / "facts_v1.aliases.v2.yaml"
L3 = ("en", "hi", "hi-en")


def _fact(
    fid: str, entity: str, relation: str, value: str, surface: dict[str, str], **kw: Any
) -> Fact:
    return Fact(
        id=fid, domain="d", entity=entity, relation=relation, value=value, surface=surface, **kw
    )


def _bank_mapping(
    facts: list[Fact], spec: dict[str, list[tuple[str, str, str, str]]]
) -> dict[str, Any]:
    """Tier-A spans located mechanically (locate_span) in each fact's authored text."""
    by_id = {f.id: f for f in facts}
    out: dict[str, Any] = {
        "alias_bank_version": 2,
        "tokenizer_version": TOKENIZER_VERSION,
        "facts": {},
    }
    for fid, rows in spec.items():
        refs = []
        for field, lang, role, expect in rows:
            s, e = locate_span(authored_text(by_id[fid], field, lang) or "", expect)
            refs.append(
                {"field": field, "lang": lang, "role": role, "start": s, "end": e, "expect": expect}
            )
        out["facts"][fid] = {"tier_a": refs}
    return out


def _tri(
    role: str, en: str, hi: str, hien: str, field: str = "surface"
) -> list[tuple[str, str, str, str]]:
    return [(field, lang, role, e) for lang, e in zip(L3, (en, hi, hien))]


# --- Bank G (proposal §7) ------------------------------------------------------------------

G1 = _fact(
    "g1", "user", "allergic_to", "peanuts",
    {"en": "I have a severe allergy to peanuts.", "hi": "मुझे मूंगफली से गंभीर एलर्जी है।",
     "hi-en": "Mujhe peanuts se severe allergy hai."},
    update_data={"updated_value": "cashews", "surface": {
        "en": "Correction: I am not allergic to peanuts, but to cashews.",
        "hi": "एक सुधार है: मुझे मूंगफली से नहीं, बल्कि काजू से एलर्जी है।",
        "hi-en": "Ek update hai: mujhe peanuts se nahi, cashews se allergy hai."}},
)  # fmt: skip
G1D = _fact(
    "g1d", "user_sister", "allergic_to", "peanuts",
    {"en": "My sister has an allergy to peanuts.", "hi": "मेरी बहन को मूंगफली से एलर्जी है।",
     "hi-en": "Meri sister ko peanuts se allergy hai."},
    distractor_of="g1",
)  # fmt: skip
G2 = _fact(
    "g2", "user", "lives_in", "pune",
    {"en": "I currently live in Pune.", "hi": "मैं वर्तमान में पुणे में रहता हूँ।",
     "hi-en": "Main abhi Pune me rehta hoon."},
    update_data={"updated_value": "mumbai", "surface": {
        "en": "I have moved to Mumbai.", "hi": "मैं मुंबई शिफ्ट हो गया हूँ।",
        "hi-en": "Main Mumbai shift ho gaya hoon."}},
)  # fmt: skip
G3 = _fact(
    "g3", "user", "hometown", "jaipur",
    {"en": "My hometown is Jaipur.", "hi": "मेरा गृहनगर जयपुर है।", "hi-en": "Mera hometown Jaipur hai."},
)  # fmt: skip
G4 = _fact(
    "g4", "user", "works_at", "infosys",
    {"en": "I work at Infosys.", "hi": "मैं इंफोसिस में काम करता हूँ।",
     "hi-en": "Main Infosys me kaam karta hoon."},
    update_data={"updated_value": "tcs", "surface": {
        "en": "I left Infosys and now work at TCS.", "hi": "अब मैं टीसीएस में काम करता हूँ।",
        "hi-en": "Ab main TCS me kaam karta hoon."}},
)  # fmt: skip
V1 = _fact("v1", "user", "diet", "vegetarian", {"en": "I follow a vegetarian diet."})
V1D = _fact(
    "v1d",
    "user",
    "diet",
    "gluten_free",
    {"en": "I also follow a gluten free diet."},
    distractor_of="v1",
)
G_FACTS = [G1, G1D, G2, G3, G4, V1, V1D]
G_SPEC = {
    "g1": _tri("value", "peanuts", "मूंगफली", "peanuts") + _tri("relation_cue", "allergy", "एलर्जी", "allergy")
    + _tri("updated_value", "cashews", "काजू", "cashews", "update.surface"),
    "g1d": _tri("value", "peanuts", "मूंगफली", "peanuts") + _tri("relation_cue", "allergy", "एलर्जी", "allergy")
    + _tri("subject_cue", "sister", "बहन", "sister"),
    "g2": _tri("value", "Pune", "पुणे", "Pune") + _tri("relation_cue", "live", "रहता", "rehta")
    + _tri("updated_value", "Mumbai", "मुंबई", "Mumbai", "update.surface"),
    "g3": _tri("value", "Jaipur", "जयपुर", "Jaipur") + _tri("relation_cue", "hometown", "गृहनगर", "hometown"),
    "g4": _tri("value", "Infosys", "इंफोसिस", "Infosys") + _tri("relation_cue", "work", "काम", "kaam")
    + _tri("updated_value", "TCS", "टीसीएस", "TCS", "update.surface"),
    "v1": [("surface", "en", "value", "vegetarian"), ("surface", "en", "relation_cue", "diet")],
    "v1d": [("surface", "en", "value", "gluten free"), ("surface", "en", "relation_cue", "diet")],
}  # fmt: skip


@pytest.fixture(scope="module")
def G() -> MatchBank:
    return MatchBank(G_FACTS, alias_bank_from_mapping(_bank_mapping(G_FACTS, G_SPEC), G_FACTS))


@pytest.fixture(scope="module")
def REAL() -> MatchBank:
    facts = load_facts(FACTS_V1)
    return MatchBank(facts, load_alias_bank_v2(ALIASES_V2, facts, FACTS_V1))


def _old_wf_match(fact: Fact, text: str) -> bool:
    return strict_match(fact.value, text, aliases=list(fact.surface.values()))


# --- Foundation ----------------------------------------------------------------------------


def test_tokenizer_keeps_vowel_signs_and_folds_nukta() -> None:
    assert tokenize("काजू") == ["काजू"]
    assert normalize("फ़िल्टर कॉफ़ी") == normalize("फिल्टर कॉफी")
    assert tokenize("don't") == ["don", "t"]
    assert tokenize("कashews") == ["कashews"]


def test_lexicons_are_language_scoped() -> None:
    """`main` is a Hinglish user cue but an ordinary English word."""
    toks = tokenize("The main office is in Pune")
    assert attribute_subject(toks, [], lexicon_for("en"), "record", guarantee=False).label != USER
    toks = tokenize("Main abhi Pune me rehta hoon")
    subj = attribute_subject(toks, [], lexicon_for("hi-en"), "record", guarantee=False)
    assert subj.label == USER and subj.explicit_user


@pytest.mark.parametrize("text", ["Pehle peanuts se allergy thi.", "Peanuts se allergy tha."])
def test_pehle_tha_thi_are_past_never_negation(text: str) -> None:
    """O4: PAST cues alone never negate; without a NOW cue the mention is AMBIGUOUS."""
    t = make_target("peanuts", "g1", "value")
    raw = analyze(text, [t], lexicon_for("hi-en"))
    assert [m.frame for m in raw] == [PAST]
    out = classify_reprobe_v3(text, "g1", MatchBank(G_FACTS, None), "hi-en")
    assert out["outcome"] == "MISS" and out["unresolved"] and out["old_frames"] == [AMBIGUOUS]


def test_real_alias_bank_loads_and_satisfies_contract() -> None:
    facts = load_facts(FACTS_V1)
    bank = load_alias_bank_v2(ALIASES_V2, facts, FACTS_V1)
    assert sum(len(v) for v in bank.entries.values()) == 138
    assert validate_contract_bank(facts, bank, DEFAULT_FILLER_TURNS) == []


# --- Proposal §3 cases (real facts_v1 + real alias bank where possible) --------------------


@pytest.mark.parametrize(
    "case, fid, text, lang, phase, expect_status, expect_provisional, old",
    [
        ("1 case/punct", "f_002", "LIVES IN PUNE!!", "en", SNAPSHOT_A, SUPPORTED, False, True),
        ("2 plural", "f_001", "Allergic to peanut", "en", SNAPSHOT_A, SUPPORTED, True, True),
        ("3 paraphrase", "f_002", "Resides in the city of Pune", "en", SNAPSHOT_A, SUPPORTED, True, True),
        ("4 Punekar", "f_002", "He is a proud Punekar", "en", SNAPSHOT_A, NONE, False, True),
        ("5 advisable", "f_016", "It is advisable to apply early", "en", SNAPSHOT_A, NONE, False, True),
        ("6 negated write", "f_002", "Does not live in Pune", "en", SNAPSHOT_A, NOT_SUPPORTED, False, True),
        ("7 Mem0 Hindi", "f_002", "वर्तमान में पुणे में रहता हूँ", "hi", SNAPSHOT_A, SUPPORTED, False, False),
        ("11 Hinglish", "f_001", "mujhe peanuts se allergy hai", "hi-en", SNAPSHOT_A, SUPPORTED, False, True),
        ("13 hometown->residence", "f_014", "Currently lives in Jaipur", "en", SNAPSHOT_A, NOT_SUPPORTED, False, True),
        ("13b unverifiable", "f_014", "Jaipur is where I stay now", "en", SNAPSHOT_A, SUPPORTED, True, True),
        ("14 office->residence", "f_002", "Works at the Infosys Pune office", "en", SNAPSHOT_A, NOT_SUPPORTED, False, True),
        ("14b unverifiable", "f_002", "Pune office, near home", "en", SNAPSHOT_A, SUPPORTED, True, True),
        ("15 sister record", "f_001", "My sister has an allergy to peanuts", "en", LATER, NOT_SUPPORTED, False, True),
        ("16 joint subjects", "f_001", "My sister and I are both allergic to peanuts", "en", LATER, UNRESOLVED, False, True),
        ("17 pronoun", "f_001", "She is allergic to peanuts", "en", LATER, UNRESOLVED, False, True),
        ("18 new subjectless", "f_001", "Allergic to peanuts", "en", LATER, UNRESOLVED, False, True),
        ("21 nukta", "f_006", "मेरी पसंदीदा ड्रिंक फिल्टर कॉफी है", "hi", SNAPSHOT_A, SUPPORTED, False, False),
        ("22 verbatim turn", "f_001", "मुझे मूंगफली से गंभीर एलर्जी है।", "hi", SNAPSHOT_A, SUPPORTED, False, True),
    ],
)  # fmt: skip
def test_section3_cases(
    REAL: MatchBank, case: str, fid: str, text: str, lang: str, phase: str,
    expect_status: str, expect_provisional: bool, old: bool,
) -> None:  # fmt: skip
    s = support(text, fid, REAL, lang, phase)
    assert (s.status, s.provisional) == (expect_status, expect_provisional), case
    assert _old_wf_match(REAL.facts[fid], text) is old, f"{case}: old strict_match result"


def test_case18_subjectless_sentence_seen_in_snapshot_a_keeps_guarantee(REAL: MatchBank) -> None:
    keys = {tuple(tokenize("Allergic to peanuts"))}
    assert support("Allergic to peanuts", "f_001", REAL, "en", LATER, keys).status == SUPPORTED


def test_case22_full_sentences_are_not_targets(REAL: MatchBank) -> None:
    longest = max(len(t.tokens) for t in REAL.value_targets("f_001", "hi"))
    assert longest == 1  # "मूंगफली"; the 6-token authored sentence is not a target


def test_case5_tea_vs_team() -> None:
    tea = _fact("t1", "user", "favorite_beverage", "tea", {"en": "I drink tea."})
    bank = MatchBank([tea], None)
    assert support("Joined the team lunch", "t1", bank, "en", SNAPSHOT_A).status == NONE
    assert strict_match("tea", "Joined the team lunch") is True


def test_case8_kaju_vs_kajri() -> None:
    raw = analyze(
        "मुझे कजरी से एलर्जी है", [make_target("काजू", "f_001", "updated_value")], lexicon_for("hi")
    )
    assert raw == []


def test_case9_spelling_variant_needs_frozen_tier_b(REAL: MatchBank) -> None:
    facts = load_facts(FACTS_V1)
    payload = yaml.safe_load(ALIASES_V2.read_text(encoding="utf-8"))
    text = "गोल्डन रिट्रवर कुत्ता है"
    assert support(text, "f_005", REAL, "hi", SNAPSHOT_A).status == NONE
    payload["facts"]["f_005"]["tier_b"] = [
        {"lang": "hi", "role": "value", "text": "गोल्डन रिट्रवर", "annotators": ["a1", "a2"],
         "date": "2026-11-01", "frozen": True}
    ]  # fmt: skip
    with_b = MatchBank(facts, alias_bank_from_mapping(payload, facts))
    assert support(text, "f_005", with_b, "hi", SNAPSHOT_A).status == SUPPORTED
    assert _old_wf_match(REAL.facts["f_005"], text) is False


def test_case10_tier_c_is_sensitivity_only(G: MatchBank) -> None:
    payload = _bank_mapping(G_FACTS, G_SPEC)
    payload["facts"]["g1"]["tier_c"] = [
        {"lang": "hi", "role": "updated_value", "text": "कैश्वर", "added_by": "x",
         "date": "2026-10-27", "reason": "seen in pilot output"}
    ]  # fmt: skip
    ab = alias_bank_from_mapping(payload, G_FACTS)
    answer = "आपको कैश्वर से एलर्जी है।"
    assert classify_reprobe_v3(answer, "g1", MatchBank(G_FACTS, ab), "hi")["outcome"] == "MISS"
    sens = MatchBank(G_FACTS, ab, tiers=("A", "B", "C"))
    assert classify_reprobe_v3(answer, "g1", sens, "hi")["outcome"] == "UPDATED"


def test_case12_romanized_value_from_hinglish_surface() -> None:
    f = _fact(
        "k1",
        "user",
        "allergic_to",
        "cashews",
        {"en": "I am allergic to cashews.", "hi-en": "Mujhe kaju se allergy hai."},
    )
    ab = alias_bank_from_mapping(
        _bank_mapping([f], {"k1": [("surface", "hi-en", "value", "kaju")]}), [f]
    )
    assert (
        support("kaju se allergy hai", "k1", MatchBank([f], ab), "hi-en", SNAPSHOT_A).status
        == SUPPORTED
    )


def test_case20_longest_match_wins() -> None:
    veg = _fact(
        "d1",
        "user",
        "diet",
        "vegetarian",
        {"en": "I am vegetarian."},
        update_data={
            "updated_value": "non_vegetarian",
            "surface": {"en": "Now I am non-vegetarian."},
        },
    )
    bank = MatchBank([veg], None)
    assert support("Follows a non-vegetarian diet", "d1", bank, "en", SNAPSHOT_A).status == NONE
    assert strict_match("vegetarian", "Follows a non-vegetarian diet") is True


def test_case23_abstract_value_via_tier_a() -> None:
    f = _fact(
        "h1", "user", "vaccination", "flu_shot_pending", {"en": "My flu shot is still pending."}
    )
    bank = MatchBank(
        [f],
        alias_bank_from_mapping(
            _bank_mapping([f], {"h1": [("surface", "en", "value", "flu shot")]}), [f]
        ),
    )
    assert support("Flu shot not yet taken", "h1", bank, "en", SNAPSHOT_A).status in (
        SUPPORTED,
        UNRESOLVED,
        NOT_SUPPORTED,
    )
    assert support("Needs to get a flu shot", "h1", bank, "en", SNAPSHOT_A).status == SUPPORTED
    assert _old_wf_match(f, "Needs to get a flu shot") is False


# --- Subject false-positive tests (§4.5) ---------------------------------------------------


@pytest.mark.parametrize(
    "text, lang, expected",
    [
        ("My sister has an allergy to peanuts", "en", DISTRACTOR),
        ("मेरी बहन को मूंगफली से एलर्जी है", "hi", DISTRACTOR),
        ("User's sister is allergic to peanuts", "en", DISTRACTOR),
        ("Meri sister ko peanuts se allergy hai", "hi-en", DISTRACTOR),
    ],
)
def test_possessives_are_not_user_cues(G: MatchBank, text: str, lang: str, expected: str) -> None:
    cues = G.subject_cues("g1d", lang)
    assert (
        attribute_subject(tokenize(text), cues, lexicon_for(lang), "record", False).label
        == expected
    )


def test_semicolon_separates_subjects(G: MatchBank) -> None:
    s = support("Sister visited me; I am allergic to peanuts", "g1", G, "en", LATER)
    assert s.status == SUPPORTED and s.explicit_user


def test_sister_cue_ignored_for_fact_without_entity_shift_distractor(G: MatchBank) -> None:
    assert (
        support("My sister visited Jaipur, my hometown", "g3", G, "en", LATER).status == SUPPORTED
    )


def test_validator_rejects_filler_with_value_and_other_contract_breaks() -> None:
    ab = alias_bank_from_mapping(_bank_mapping(G_FACTS, G_SPEC), G_FACTS)
    errs = validate_contract_bank(G_FACTS, ab, [{"en": "Let's talk about Pune today."}])
    assert any("filler turn 0 [en] contains value of g2" in e for e in errs)
    clash = _fact("g9", "user", "office_city", "pune", {"en": "My office is in Pune."})
    errs = validate_contract_bank(G_FACTS + [clash], ab, [])
    assert any("share value target 'pune'" in e for e in errs)
    assert any("g9: no tier-A value span for en" in e for e in errs)


def test_validator_rejects_relation_cue_reuse_across_relations() -> None:
    a = _fact("a", "user", "lives_in", "pune", {"en": "I live in Pune."})
    b = _fact("b", "user", "hometown", "jaipur", {"en": "I live for Jaipur."})
    spec = {
        "a": [("surface", "en", "value", "Pune"), ("surface", "en", "relation_cue", "live")],
        "b": [("surface", "en", "value", "Jaipur"), ("surface", "en", "relation_cue", "live")],
    }
    errs = validate_contract_bank(
        [a, b], alias_bank_from_mapping(_bank_mapping([a, b], spec), [a, b]), []
    )
    assert any("relation cue 'live' used for both" in e for e in errs)


# --- O7 loader refusals --------------------------------------------------------------------


def _mapping_one(**ref: Any) -> dict[str, Any]:
    base = {
        "field": "surface",
        "lang": "en",
        "role": "value",
        "start": 6,
        "end": 7,
        "expect": "peanuts",
    }
    base.update(ref)
    return {
        "alias_bank_version": 2,
        "tokenizer_version": TOKENIZER_VERSION,
        "facts": {"g1": {"tier_a": [base]}},
    }


@pytest.mark.parametrize(
    "ref, msg",
    [
        ({"expect": "allergy"}, "span extracts"),
        ({"start": 6, "end": 9}, "invalid for"),
        ({"field": "update.surface"}, "value spans must come from surface"),
        ({"role": "updated_value"}, "updated_value spans must come from update.surface"),
        ({"field": "nope"}, "bad field"),
    ],
)
def test_loader_refuses_bad_spans(ref: dict[str, Any], msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        alias_bank_from_mapping(_mapping_one(**ref), G_FACTS)


def test_loader_refuses_cross_sentence_span() -> None:
    f = _fact("x", "user", "r", "a", {"en": "Alpha beta. Gamma delta."})
    m = {
        "alias_bank_version": 2,
        "tokenizer_version": TOKENIZER_VERSION,
        "facts": {
            "x": {
                "tier_a": [
                    {
                        "field": "surface",
                        "lang": "en",
                        "role": "value",
                        "start": 1,
                        "end": 3,
                        "expect": "beta gamma",
                    }
                ]
            }
        },
    }
    with pytest.raises(ValueError, match="crosses a sentence boundary"):
        alias_bank_from_mapping(m, [f])


def test_loader_refuses_version_hash_and_provenance_problems(tmp_path: Path) -> None:
    m = _mapping_one()
    with pytest.raises(ValueError, match="tokenizer_version"):
        alias_bank_from_mapping({**m, "tokenizer_version": "old"}, G_FACTS)
    with pytest.raises(ValueError, match="written for fact bank"):
        alias_bank_from_mapping(
            {**m, "fact_bank_sha256": "0" * 64}, G_FACTS, fact_bank_sha256="1" * 64
        )
    bad_b = json.loads(json.dumps(m))
    bad_b["facts"]["g1"]["tier_b"] = [
        {
            "lang": "hi",
            "role": "value",
            "text": "x",
            "annotators": ["a1"],
            "date": "d",
            "frozen": True,
        }
    ]
    with pytest.raises(ValueError, match=">= 2 distinct annotators"):
        alias_bank_from_mapping(bad_b, G_FACTS)
    bad_b["facts"]["g1"]["tier_b"][0].update(annotators=["a1", "a2"], frozen=False)
    with pytest.raises(ValueError, match="frozen"):
        alias_bank_from_mapping(bad_b, G_FACTS)
    bad_c = json.loads(json.dumps(m))
    bad_c["facts"]["g1"]["tier_c"] = [
        {"lang": "hi", "role": "value", "text": "x", "added_by": "a", "date": "d"}
    ]
    with pytest.raises(ValueError, match="tier C needs"):
        alias_bank_from_mapping(bad_c, G_FACTS)
    bank_file = tmp_path / "facts.yaml"
    bank_file.write_text("facts: []\n", encoding="utf-8")
    side = tmp_path / "a.yaml"
    side.write_text(yaml.safe_dump({**m, "fact_bank_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="written for fact bank"):
        load_alias_bank_v2(side, G_FACTS, bank_file)
    side.write_text(
        yaml.safe_dump(
            {**m, "fact_bank_sha256": hashlib.sha256(bank_file.read_bytes()).hexdigest()}
        ),
        encoding="utf-8",
    )
    assert load_alias_bank_v2(side, G_FACTS, bank_file).entries["g1"][0].text == "peanuts"


# --- §7 G-WF / G-DR -----------------------------------------------------------------------

SNAP_A = ["Has a severe allergy to peanuts", "Allergic to peanuts", "Currently lives in Jaipur",
          "Works at the Infosys Pune office", "Does not live in Pune"]  # fmt: skip
PLANTED = ["g1", "g2", "g3", "g4"]


def test_golden_wf_and_dr(G: MatchBank) -> None:
    wf = write_fidelity_v3(G, PLANTED, SNAP_A, "en")
    assert wf["written"] == ["g1", "g4"] and wf["write_fidelity"] == pytest.approx(0.50)
    assert wf["confirmed"] == ["g1", "g4"] and wf["provisional"] == [] and wf["unresolved"] == []
    dr = plant_duplication_v3(G, PLANTED, SNAP_A, "en")
    assert dr["records_per_fact"] == {"g1": 2, "g2": 0, "g3": 0, "g4": 1}
    assert dr["plant_duplication_rate"] == pytest.approx(0.25) and dr["provisional_records"] == 1
    mems = [Memory(raw_id=str(i), text=t) for i, t in enumerate(SNAP_A)]
    old_wf, _ = compute_write_fidelity([G1, G2, G3, G4], mems)
    old_dr, _ = compute_plant_duplication_rate([G1, G2, G3, G4], PLANTED, mems)
    assert (old_wf, old_dr) == (pytest.approx(1.0), pytest.approx(0.5))


# --- §7 G-R ------------------------------------------------------------------------------


def _probe(fid: str, *texts: str) -> ProbeResult:
    return ProbeResult(
        fid, "en", "en", [Memory(raw_id=str(i), text=t) for i, t in enumerate(texts)], ""
    )


def test_golden_recall(G: MatchBank) -> None:
    snap = {tuple(tokenize(t)) for t in SNAP_A}
    probes = [_probe("g1", "My sister has an allergy to peanuts", "Has a severe allergy to peanuts", "Lives in Pune"),
              _probe("g4", "Works at the Infosys Pune office")]  # fmt: skip
    r = recall_v3(G, ["g1", "g4"], probes, "en", snap)
    assert r["recall_at_1"] == pytest.approx(0.5) and r["recall_at_3"] == pytest.approx(1.0)
    assert r["distractor_retrieval_at_1"] == pytest.approx(0.5)
    old_probes = probes + [
        _probe("g2", "Works at the Infosys Pune office"),
        _probe("g3", "Currently lives in Jaipur"),
    ]
    assert compute_recall_at_k(
        [G1, G2, G3, G4], old_probes, k=1, eligible_fact_ids=set(PLANTED)
    ) == pytest.approx(1.0)


def test_golden_recall_variant_unresolved_is_flagged_not_scored(G: MatchBank) -> None:
    snap = {tuple(tokenize(t)) for t in SNAP_A}
    probes = [_probe("g1", "Allergic to peanut, it seems"), _probe("g4", "Works at Infosys")]
    snap.discard(tuple(tokenize("Allergic to peanut, it seems")))
    r = recall_v3(G, ["g1", "g4"], probes, "en", snap)
    assert r["recall_at_1"] == pytest.approx(0.5) and r["recall_at_1_unresolved"] == 1
    wf = write_fidelity_v3(G, PLANTED, SNAP_A, "en")
    dr = plant_duplication_v3(G, PLANTED, SNAP_A, "en")
    sr = staleness_v3(G, [], set(wf["written"]), set(), [])
    fmr = false_merge_v3(G, [], SNAP_A, [], "en")
    rep = validation_report(wf, dr, r, sr, fmr)
    assert rep["unresolved"]["recall_at_1"] == {"count": 1, "denominator": 2, "share": 0.5}
    assert rep["insufficient_validation"]["recall_at_1"].startswith("0.50 unresolved")
    assert r["recall_at_1"] == pytest.approx(0.5)  # the flag never changes the score


# --- §7 G-SR -----------------------------------------------------------------------------

EN_T = (["peanuts"], ["cashews"])
HI_T = (["peanuts", "मूंगफली"], ["cashews", "काजू"])


@pytest.mark.parametrize(
    "row, lang, answer, expected, old",
    [
        ("1", "en", "You are allergic to cashews now.", "UPDATED", "UPDATED"),
        ("2", "en", "You are allergic to peanuts, not cashews.", "STALE", "STALE"),
        ("3", "en", "You used to be allergic to peanuts. Now you are allergic to cashews.", "UPDATED", "UPDATED"),
        ("3b", "en", "You used to be allergic to peanuts, but now it is cashews.", "MISS", "MISS"),
        ("4", "en", "You are allergic to carrots.", "MISS", "MISS"),
        ("5", "en", "Your sister is allergic to peanuts.", "MISS", "STALE"),
        ("6", "hi", "आपको मूंगफली से नहीं, बल्कि काजू से एलर्जी है।", "UPDATED", "UPDATED"),
        ("7", "hi", "आपको मूंगफली से एलर्जी है, न कि काजू से।", "STALE", "STALE"),
        ("8", "hi-en", "Aapko ab cashews se allergy hai, peanuts se nahi.", "UPDATED", "STALE"),
        ("9", "hi-en", "Aapko peanuts se allergy hai, cashews se nahi.", "STALE", "STALE"),
        ("10", "hi-en", "Peanuts nahi, balki cashews.", "UPDATED", "STALE"),
        ("11", "en", "Not peanuts — cashews.", "MISS", "MISS"),
        ("12", "en", "Not peanuts, but cashews.", "UPDATED", "UPDATED"),
        ("13", "en", "Not peanuts, but cashews are not confirmed either.", "MISS", "UPDATED"),
        ("14", "en", "I don't know, but cashews are not listed.", "MISS", "UPDATED"),
        ("15", "hi", "मूंगफली से नहीं, बल्कि काजू से एलर्जी है।", "UPDATED", "UPDATED"),
        ("16", "hi", "मूंगफली से नहीं, बल्कि काजू से भी नहीं है।", "MISS", "UPDATED"),
        ("17", "hi-en", "Peanuts nahi, balki cashews se allergy hai.", "UPDATED", "STALE"),
        ("17b", "hi-en", "Peanuts nahi, balki cashews se bhi nahi.", "MISS", "STALE"),
        ("18", "hi-en", "Pehle peanuts se allergy thi.", "MISS", "STALE"),
        ("19", "hi-en", "Pehle peanuts se allergy thi, ab cashews se hai.", "UPDATED", "STALE"),
        ("20", "en", "You were allergic to peanuts.", "MISS", "MISS"),
    ],
)  # fmt: skip
def test_golden_sr_rows(
    G: MatchBank, row: str, lang: str, answer: str, expected: str, old: str
) -> None:
    assert classify_reprobe_v3(answer, "g1", G, lang)["outcome"] == expected, f"row {row}"
    old_t = HI_T if lang == "hi" else EN_T
    assert classify_v21("g1", answer, *old_t).outcome == old, f"row {row}: v2.1 result"


@pytest.mark.parametrize(
    "answer, unresolved",
    [
        ("Not peanuts, but cashews are not confirmed either.", True),
        ("You are allergic to carrots.", False),
    ],
)
def test_sr_unresolved_flag_separates_ambiguity_from_absence(
    G: MatchBank, answer: str, unresolved: bool
) -> None:
    assert classify_reprobe_v3(answer, "g1", G, "en")["unresolved"] is unresolved


def test_golden_sr_aggregate(G: MatchBank) -> None:
    wf = write_fidelity_v3(G, PLANTED, SNAP_A, "en")
    rp = [ProbeResult("g1", "en", "en", [], "You are allergic to peanuts, not cashews."),
          ProbeResult("g4", "en", "en", [], "You now work at TCS."),
          ProbeResult("g2", "en", "en", [], "You live in Mumbai now.")]  # fmt: skip
    sr = staleness_v3(G, ["g1", "g2", "g4"], set(wf["written"]), set(wf["provisional"]), rp)
    assert (sr["eligible_corrections"], sr["write_ineligible_count"]) == (2, 1)
    assert sr["staleness_rate"] == pytest.approx(0.5) and sr["miss_rate"] == pytest.approx(0.0)
    assert sr["write_ineligible_rate"] == pytest.approx(1 / 3)
    old = compute_staleness_v2([G1, G2, G4], ["g1", "g2", "g4"], {"g1", "g2", "g4"}, rp, None)
    assert old["staleness_rate"] == pytest.approx(1 / 3)


# --- §7 G-FMR ----------------------------------------------------------------------------

A1 = "Has a severe allergy to peanuts"


@pytest.mark.parametrize(
    "row, fid, did, plant, final, category, event, old_fmr",
    [
        ("1", "g1", "g1d", [A1], [A1, "My sister has an allergy to peanuts"], SEPARATED, False, 0.0),
        ("2", "g1", "g1d", [A1], [A1, "User and sister are both allergic to peanuts"], JOINT, True, 1.0),
        ("3", "g1", "g1d", [A1], [A1, "I am allergic to peanuts"], WRONG_PERSON, True, 0.0),
        ("4", "g1", "g1d", [A1], [A1, "Allergic to peanuts"], "UNRESOLVED", False, 0.0),
        ("5", "g1", "g1d", [A1], [A1], LOST, False, 0.0),
        ("6", "v1", "v1d", ["Is vegetarian"], ["Follows a vegetarian, gluten-free diet"], JOINT, False, 1.0),
        ("7", "v1", "v1d", ["Is vegetarian"], ["Follows a gluten-free diet"], OVERWRITTEN, True, 0.0),
    ],
)  # fmt: skip
def test_golden_fmr(
    G: MatchBank, row: str, fid: str, did: str, plant: list[str], final: list[str],
    category: str, event: bool, old_fmr: float,
) -> None:  # fmt: skip
    snap = {tuple(s) for t in plant for s in [tokenize(t)]}
    assert classify_pair_v3(G, fid, did, plant, final, "en", snap) == (
        category,
        event,
    ), f"row {row}"
    rep = false_merge_v3(G, [did], plant, final, "en")
    assert rep["false_merge_rate"] == pytest.approx(1.0 if event else 0.0)
    pair = (G.facts[fid], G.facts[did])
    assert (
        compute_false_merge_rate(
            [pair], [Memory(raw_id=str(i), text=t) for i, t in enumerate(final)]
        )
        == old_fmr
    )


def test_fmr_population_is_injected_distractors_only(G: MatchBank) -> None:
    rep = false_merge_v3(G, [], [A1], [A1], "en")
    assert rep["pairs"] == 0 and rep["false_merge_rate"] is None
    assert classify_pair_v3(
        G, "g1", "g1d", [A1], ["My sister has an allergy to peanuts"], "en", set()
    ) == (BASE_LOST, False)


# --- End to end: compute_seed_scores_v3 on a synthetic seed dir ------------------------------


def test_compute_seed_scores_v3_end_to_end(tmp_path: Path) -> None:
    """G-WF snapshot, one correction (UPDATED), a correct sister fact in the final store.

    Hand-computed: WF 2/4, DR 1/4, R@1 = 1/2 (g1 hit, g4 has no probe), FMR 0 (SEPARATED),
    SR 0/1, MR 0/1, write-ineligible 0/1.
    """
    from xlmem.scripts.score import compute_seed_scores_v3

    seed = tmp_path / "seed_11"
    seed.mkdir()
    turns = [{"kind": "plant", "fact_id": f} for f in PLANTED]
    turns += [{"kind": "filler", "fact_id": "g1d"}, {"kind": "correction", "fact_id": "g1"}]
    lines: list[dict[str, Any]] = [
        {"record_type": "metadata", "store_lang": "en", "probe_lang": "en"}
    ]
    lines += [{"record_type": "turn_trace", "data": t} for t in turns]
    lines.append({"record_type": "probe_result", "data": _probe("g1", A1).to_dict()})
    lines.append({"record_type": "reprobe_result", "data": ProbeResult(
        "g1", "en", "en", [], "You are allergic to cashews now.").to_dict()})  # fmt: skip
    (seed / "run_log.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
    )
    dump = lambda ts: json.dumps([{"raw_id": str(i), "text": t} for i, t in enumerate(ts)])  # noqa: E731
    (seed / "store_after_plant.json").write_text(dump(SNAP_A), encoding="utf-8")
    (seed / "store_final.json").write_text(
        dump([A1, "My sister has an allergy to peanuts"]), encoding="utf-8"
    )

    ab = alias_bank_from_mapping(_bank_mapping(G_FACTS, G_SPEC), G_FACTS)
    s = compute_seed_scores_v3(seed, G_FACTS, ab)
    assert s["metrics_version"] == "3"
    assert s["write_fidelity"] == pytest.approx(0.5) and s[
        "plant_duplication_rate"
    ] == pytest.approx(0.25)
    assert s["recall_at_1_strict"] == pytest.approx(0.5)
    assert s["false_merge_rate"] == pytest.approx(0.0)
    assert s["detail"]["false_merge"]["categories"] == {"g1/g1d": SEPARATED}
    assert (s["staleness_rate"], s["miss_rate"], s["write_ineligible_rate"]) == (0.0, 0.0, 0.0)
    assert "validation" in s and "invalid_metrics" not in s
    assert not (seed / "scores.json").exists()
