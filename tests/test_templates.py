"""Template-rendered fact construction (xlmem/benchmark/templates.py) and cross-bank checks."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from xlmem.benchmark.templates import TemplateError, load_and_render, render_domain
from xlmem.benchmark.validate import (
    check_cross_bank_collisions,
    check_value_overlap,
    validate_fact_bank,
)

ROOT = Path(__file__).parent.parent
ENTITIES = ROOT / "data" / "templates" / "entities.yaml"
DINING = ROOT / "data" / "templates" / "dining.yaml"
DINING_BATCH = ROOT / "data" / "candidates" / "dining_batch_01.yaml"
DOMAINS = ["dining", "work", "travel", "family", "finance", "hobbies", "tech"]


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def dining_facts() -> list[dict[str, Any]]:
    return load_and_render(DINING, ENTITIES)


def _by_id(facts: list[dict[str, Any]], fid: str) -> dict[str, Any]:
    return next(f for f in facts if f["id"] == fid)


def test_hand_checked_rendering_with_gender_agreement(dining_facts: list[dict[str, Any]]) -> None:
    # Expected strings written by hand. पकवान is masculine (का), but "dish" is
    # feminine in Hinglish (ki), so the possessor agrees differently per language.
    f = _by_id(dining_facts, "f_201_dist")
    assert f["surface"] == {
        "en": "My brother's favorite dish is paneer tikka.",
        "hi": "मेरे भाई का पसंदीदा पकवान पनीर टिक्का है।",
        "hi-en": "Mere brother ki favorite dish paneer tikka hai.",
    }
    assert f["distractor_of"] == "f_201" and f["update"] is None

    # Feminine head noun (सब्ज़ी), user possessor, and a Hinglish value that differs
    # from the English one (karela vs bitter gourd).
    g = _by_id(dining_facts, "f_207")
    assert g["surface"]["hi"] == "मेरी सबसे नापसंद सब्ज़ी करेला है।"
    assert g["surface"]["hi-en"] == "Meri sabse naapasand vegetable karela hai."
    assert g["value_aliases"] == {"hi": ["करेला"], "translit": ["karela"]}
    assert g["update"]["surface"]["hi"] == "एक सुधार है: मेरी सबसे नापसंद सब्ज़ी करेला नहीं, बल्कि भिंडी है।"
    assert g["update"]["probe_questions"]["en"] == "What is my least favorite vegetable now?"


@pytest.fixture(scope="module", params=DOMAINS)
def domain_facts(request: pytest.FixtureRequest) -> tuple[str, list[dict[str, Any]]]:
    template = ROOT / "data" / "templates" / f"{request.param}.yaml"
    return request.param, load_and_render(template, ENTITIES)


def test_every_value_form_occurs_in_its_surface(domain_facts: tuple[str, list]) -> None:
    for f in domain_facts[1]:
        assert f["value"].replace("_", " ") in f["surface"]["en"].lower(), f["id"]
        for alias in f["value_aliases"]["hi"]:
            assert alias in f["surface"]["hi"], f["id"]
        for alias in f["value_aliases"].get("translit", []):
            assert alias in f["surface"]["hi-en"], f["id"]


def test_probes_do_not_leak_the_answer(domain_facts: tuple[str, list]) -> None:
    for f in domain_facts[1]:
        forms = [f["value"].replace("_", " ")] + f["value_aliases"]["hi"]
        forms += f["value_aliases"].get("translit", [])
        for question in f["probe_questions"].values():
            assert not any(v.lower() in question.lower() for v in forms), f["id"]


def test_rendered_batch_passes_schema_validation(
    tmp_path: Path, domain_facts: tuple[str, list]
) -> None:
    out = tmp_path / "batch.yaml"
    out.write_text(yaml.safe_dump({"version": "1.0", "facts": domain_facts[1]}, allow_unicode=True))
    report = validate_fact_bank(out)
    assert report.is_valid and not report.warnings
    assert report.total_distractors / (report.total_facts - report.total_distractors) >= 0.30


def test_checked_in_candidate_batch_matches_template(domain_facts: tuple[str, list]) -> None:
    """data/candidates/<domain>_batch_01.yaml must be a pure render of its template."""
    domain, facts = domain_facts
    assert _load(ROOT / "data" / "candidates" / f"{domain}_batch_01.yaml")["facts"] == facts


def test_all_candidate_batches_are_mutually_consistent() -> None:
    """No collisions or cross-fact value overlaps among the template-rendered batches
    and data/facts_v1.yaml (the pre-existing health batch is reviewed separately)."""
    paths = [ROOT / "data" / "facts_v1.yaml"]
    paths += [ROOT / "data" / "candidates" / f"{d}_batch_01.yaml" for d in DOMAINS]
    assert check_cross_bank_collisions(paths) == []
    assert check_value_overlap(paths) == []


def test_value_overlap_is_detected(tmp_path: Path) -> None:
    bank = _bank(tmp_path, "c.yaml", [
        {"id": "f_001", "entity": "user", "relation": "office_city", "value": "chennai",
         "value_aliases": {"hi": ["चेन्नई"]},
         "surface": {"en": "My office is in Chennai.", "hi": "मेरा ऑफिस चेन्नई में है।"}},
        {"id": "f_002", "entity": "user", "relation": "cricket_team",
         "value": "chennai_super_kings",
         "surface": {"en": "My team is Chennai Super Kings.", "hi": "मेरी टीम चेन्नई सुपर किंग्स है।"}},
        {"id": "f_003", "entity": "user", "relation": "vehicle", "value": "car",
         "surface": {"en": "I drive a car.", "hi": "मेरे पास कार है।"}},
        {"id": "f_004", "entity": "user", "relation": "card", "value": "debit_card",
         "surface": {"en": "I use a debit card.", "hi": "मैं डेबिट कार्ड इस्तेमाल करता हूँ।"}},
    ])
    flagged = {i.fact_id for i in check_value_overlap([bank])}
    # "chennai" sits inside f_002's sentence; "car" does not match the token "card".
    assert flagged == {"f_001"}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.append({"id": "f_299", "relation": "favorite_dish", "entity": "user",
                             "value": "pav_bhaji"}), "duplicate"),
        (lambda p: p.append({"id": "f_299", "relation": "favorite_dish", "entity": "user_wife",
                             "value": "masala_dosa"}), "already planted"),
        (lambda p: p.append({"id": "f_202_dist", "distractor_of": "f_202",
                             "entity": "user_wife", "value": "biryani"}), "inherits"),
        (lambda p: p.append({"id": "f_299", "relation": "favorite_dish", "entity": "user_wife",
                             "value": "chole_bhature"}), "also planted"),
    ],
)
def test_plan_rule_violations_are_rejected(mutate: Any, message: str) -> None:
    template = copy.deepcopy(_load(DINING))
    mutate(template["facts"])
    with pytest.raises(TemplateError, match=message):
        render_domain(template, _load(ENTITIES)["entities"])


def _bank(tmp_path: Path, name: str, facts: list[dict[str, str]]) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"version": "1.0", "facts": facts}, allow_unicode=True))
    return path


def test_cross_bank_collisions(tmp_path: Path) -> None:
    a = _bank(tmp_path, "a.yaml", [
        {"id": "f_001", "entity": "user", "relation": "lives_in", "value": "pune"},
        {"id": "f_002", "entity": "user", "relation": "dietary_preference", "value": "vegetarian"},
    ])
    b = _bank(tmp_path, "b.yaml", [
        {"id": "f_001", "entity": "user_mother", "relation": "lives_in", "value": "goa"},
        {"id": "f_101", "entity": "user", "relation": "lives_in", "value": "pune"},
        {"id": "f_102", "entity": "user", "relation": "lives_in", "value": "delhi"},
        {"id": "f_103", "entity": "user", "relation": "dietary_restriction", "value": "vegetarian"},
    ])
    issues = check_cross_bank_collisions([a, b])
    found = {(i.fact_id, i.severity) for i in issues}
    assert found == {
        ("f_001", "error"),    # id reused across files
        ("f_101", "error"),    # identical (entity, relation, value)
        ("f_102", "warning"),  # same slot, contradicting value
        ("f_103", "warning"),  # same (entity, value) under another relation name
    }
