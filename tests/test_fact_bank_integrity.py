"""Integrity of the whole candidate bank: data/facts_v1.yaml plus every data/candidates batch.

These are the facts that will be merged into one bank and planted for one user, so the
checks run across files: per-file validation cannot see a question shared by two facts.
"""

from __future__ import annotations

import collections
import unicodedata
from pathlib import Path
from typing import Any

import pytest
import yaml

from xlmem.benchmark.templates import load_and_render

ROOT = Path(__file__).parent.parent
BANK_FILES = [
    ROOT / "data" / "facts_v1.yaml",
    *sorted((ROOT / "data" / "candidates").glob("*.yaml")),
]
# The 8 approved domains (BENCHMARK_SPEC §3), by the names the fact bank uses.
APPROVED_DOMAINS = {"health", "dining", "work", "travel", "family", "finance", "hobbies", "tech"}
# Every domain template in the repository. Health has no template: its facts are
# hand-written (data/candidates/health_batch_01.yaml) and are covered by the bank-wide
# tests below, not by the rendering tests.
TEMPLATES = sorted(
    p for p in (ROOT / "data" / "templates").glob("*.yaml") if p.name != "entities.yaml"
)
ENTITIES = ROOT / "data" / "templates" / "entities.yaml"

# PROPOSED INVARIANT, pending approval (not a BENCHMARK_SPEC requirement). The spec
# requires open-ended, answer-free probes (§7.3) and one canonical tuple per fact (§1.1,
# §7.1), but never states that two facts' questions must differ. The tests marked
# PROPOSED below check that, as a diagnostic: two probed facts sharing one question
# cannot both be answered correctly. A failure means "needs review", not "spec violated".
#
# Scope: only BASE facts, because the session generator probes every
# base fact and never a distractor (xlmem/benchmark/generator.py, "Probe all base facts";
# distractors are injected as filler turns). A value-shift distractor shares its base
# fact's entity and relation, so BENCHMARK_SPEC §4 rule 2 implies a shared question
# (e.g. f_104 / f_104_dist); that reuse is permitted and not checked here.
#
# Textual uniqueness cannot catch two differently worded questions with the same answer
# set. Known case, awaiting a decision (docs/review/FACT_BANK_DECISIONS.md, item A):
# f_104 "What kind of diet do I follow?" is also answered by f_012 (vegetarian).


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("़", "").lower()
    kept = "".join(
        c if c.isalnum() or unicodedata.category(c).startswith("M") else " " for c in text
    )
    return " ".join(kept.split())


def _load_bank() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for path in BANK_FILES:
        with open(path, encoding="utf-8") as f:
            facts.extend(yaml.safe_load(f)["facts"])
    return facts


def test_fact_ids_are_unique_across_all_bank_files() -> None:
    ids = [f["id"] for f in _load_bank()]
    assert [i for i, n in collections.Counter(ids).items() if n > 1] == []


@pytest.fixture(scope="module")
def bank() -> dict[str, dict[str, Any]]:
    return {f["id"]: f for f in _load_bank()}


def _collisions(questions: dict[str, str]) -> set[frozenset[str]]:
    by_text: dict[str, set[str]] = collections.defaultdict(set)
    for fid, q in questions.items():
        by_text[_norm(q)].add(fid)
    return {frozenset(ids) for ids in by_text.values() if len(ids) > 1}


@pytest.mark.parametrize("lang", ["en", "hi", "hi-en"])
def test_probed_facts_have_distinct_questions(bank: dict[str, dict[str, Any]], lang: str) -> None:
    """PROPOSED invariant (pending approval; see the note above _norm)."""
    probed = {
        fid: f["probe_questions"][lang] for fid, f in bank.items() if not f.get("distractor_of")
    }
    assert _collisions(probed) == set(), "PROPOSED invariant: probed facts share a question"


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_reprobe_questions_identify_one_fact(bank: dict[str, dict[str, Any]], lang: str) -> None:
    """PROPOSED invariant (pending approval; see the note above _norm)."""
    questions = {
        fid: f["update"]["probe_questions"][lang] for fid, f in bank.items() if f.get("update")
    }
    assert _collisions(questions) == set(), "PROPOSED invariant: re-probes share a question"


def test_every_required_text_is_present(bank: dict[str, dict[str, Any]]) -> None:
    missing = []
    for fid, f in bank.items():
        for block in ("surface", "probe_questions"):
            missing += [
                f"{fid} {block}.{lang}"
                for lang in ("en", "hi", "hi-en")
                if not (f.get(block) or {}).get(lang, "").strip()
            ]
        update = f.get("update")
        if update:
            missing += [
                f"{fid} update.surface.{lang}"
                for lang in ("en", "hi", "hi-en")
                if not update["surface"].get(lang, "").strip()
            ]
            missing += [
                f"{fid} update.probe_questions.{lang}"
                for lang in ("en", "hi")
                if not update["probe_questions"].get(lang, "").strip()
            ]
    assert missing == []


def test_distractors_are_entity_or_value_shifts_of_a_base_fact(
    bank: dict[str, dict[str, Any]],
) -> None:
    """BENCHMARK_SPEC §4. A distractor is never corrected and never has its own distractor."""
    for fid, f in bank.items():
        base_id = f.get("distractor_of")
        if not base_id:
            continue
        assert base_id in bank, f"{fid}: distractor_of {base_id!r} is not a fact in the bank"
        base = bank[base_id]
        assert not base.get("distractor_of"), fid
        assert f.get("update") is None, fid
        assert f["relation"] == base["relation"], fid
        entity_shift = f["value"] == base["value"] and f["entity"] != base["entity"]
        value_shift = f["entity"] == base["entity"] and f["value"] != base["value"]
        assert entity_shift or value_shift, fid


def test_corrections_change_the_value(bank: dict[str, dict[str, Any]]) -> None:
    for fid, f in bank.items():
        if f.get("update"):
            assert f["update"]["updated_value"] != f["value"], fid


def test_every_template_is_an_approved_domain() -> None:
    assert TEMPLATES, "no domain templates found"
    for path in TEMPLATES:
        with open(path, encoding="utf-8") as f:
            domain = yaml.safe_load(f)["domain"]
        assert domain == path.stem, f"{path.name} declares domain {domain!r}"
        assert domain in APPROVED_DOMAINS, f"{path.name}: {domain!r} is not an approved domain"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.stem)
def test_rendering_is_deterministic(template: Path) -> None:
    first = load_and_render(template, ENTITIES)
    assert first == load_and_render(template, ENTITIES)
    assert {f["domain"] for f in first} == {template.stem}


def test_hindi_cuisine_and_dish_questions_stay_distinct(bank: dict[str, dict[str, Any]]) -> None:
    """Regression for the PROPOSED distinct-question invariant (pending approval):
    'पसंदीदा खाना' (cuisine) was near-synonymous with 'पसंदीदा पकवान' (dish), and the user,
    mother and brother have both facts. Asserts the current, unreviewed wording avoids both
    words; update it if bilingual review chooses another distinct term."""
    for f in bank.values():
        if f["relation"] == "favorite_cuisine":
            assert "पकवान" not in f["probe_questions"]["hi"]
            assert "खाना" not in f["probe_questions"]["hi"]


# Expected text written by hand from Hindi agreement rules, not copied from renderer
# output: शैली is f (मेरी ... कौन सी), निवेश is m (मेरा), and an honorific person takes
# plural agreement (के मैनेजर ... हैं / ke manager ... hain).
EXPECTED_RENDERS = {
    "f_231": {
        "surface": {
            "en": "My favorite cuisine is South Indian.",
            "hi": "मेरी पसंदीदा भोजन शैली दक्षिण भारतीय है।",
            "hi-en": "Meri favorite cuisine South Indian hai.",
        },
        "probe_questions": {
            "en": "What is my favorite cuisine?",
            "hi": "मेरी पसंदीदा भोजन शैली कौन सी है?",
            "hi-en": "Meri favorite cuisine kaun si hai?",
        },
    },
    "f_231_dist": {
        "surface": {
            "en": "My sister's favorite cuisine is South Indian.",
            "hi": "मेरी बहन की पसंदीदा भोजन शैली दक्षिण भारतीय है।",
            "hi-en": "Meri sister ki favorite cuisine South Indian hai.",
        },
    },
    "f_622": {
        "probe_questions": {
            "en": "What is my main investment in?",
            "hi": "मेरा मुख्य निवेश किसमें है?",
            "hi-en": "Mera main investment kismein hai?",
        },
    },
    "f_324": {
        "surface": {
            "en": "My wife's manager is Anjali Mehta.",
            "hi": "मेरी पत्नी के मैनेजर अंजलि मेहता हैं।",
            "hi-en": "Meri wife ke manager Anjali Mehta hain.",
        },
    },
}


@pytest.mark.parametrize("fid", sorted(EXPECTED_RENDERS))
def test_rendering_matches_hand_checked_text(bank: dict[str, dict[str, Any]], fid: str) -> None:
    for block, expected in EXPECTED_RENDERS[fid].items():
        assert bank[fid][block] == expected, (fid, block)


@pytest.mark.skip(
    reason="Depends on decision D1 (which aliases are authorized for strict "
    "matching, METRICS_SPEC §3.1); enable once D1 is recorded as approved."
)
def test_every_fact_has_a_value_form_in_its_own_sentences(
    bank: dict[str, dict[str, Any]],
) -> None:
    """Under the D1 proposal, strict matching uses the value and its value_aliases, and every
    such form must occur in the fact's own authored sentences. f_105, f_109 and f_110 have
    abstract value keys and no aliases, so today only a verbatim copy of a whole sentence
    can match them."""
    for fid, f in bank.items():
        forms = [f["value"].replace("_", " ")]
        for alias_list in (f.get("value_aliases") or {}).values():
            forms += alias_list
        sentences = " ".join(f["surface"].values())
        assert any(_norm(form) in _norm(sentences) for form in forms), fid
