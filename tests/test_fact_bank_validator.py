"""Unit tests for the fact-bank schema validator (xlmem/benchmark/validate.py).

All fixtures are hand-constructed minimal YAML, not the production fact bank --
these test the validator's own logic against known-good/known-bad inputs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from xlmem.benchmark.validate import validate_fact_bank

VALID_BASE_FACT = {
    "id": "f_001",
    "domain": "health",
    "entity": "user",
    "relation": "allergic_to",
    "value": "peanuts",
    "distractor_of": None,
    "surface": {"hi": "hi text", "en": "en text", "hi-en": "hi-en text"},
    "probe_questions": {"hi": "hi q", "en": "en q", "hi-en": "hi-en q"},
}


def _write_bank(tmp_path: Path, facts: list[dict]) -> Path:
    p = tmp_path / "bank.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "1.0", "facts": facts}, f, allow_unicode=True)
    return p


def test_valid_minimal_bank_has_no_errors(tmp_path: Path) -> None:
    path = _write_bank(tmp_path, [VALID_BASE_FACT])
    report = validate_fact_bank(path)
    assert report.is_valid
    assert report.errors == []
    assert report.total_facts == 1


def test_missing_surface_language_is_an_error(tmp_path: Path) -> None:
    bad = dict(VALID_BASE_FACT, surface={"hi": "hi text", "en": "en text"})  # missing hi-en
    path = _write_bank(tmp_path, [bad])
    report = validate_fact_bank(path)
    assert not report.is_valid
    assert any("surface missing language" in i.message for i in report.errors)


def test_empty_probe_question_is_an_error(tmp_path: Path) -> None:
    bad = dict(VALID_BASE_FACT, probe_questions={"hi": "hi q", "en": "", "hi-en": "hi-en q"})
    path = _write_bank(tmp_path, [bad])
    report = validate_fact_bank(path)
    assert not report.is_valid
    assert any("probe_questions[en] is empty" in i.message for i in report.errors)


def test_missing_required_field_is_an_error(tmp_path: Path) -> None:
    bad = dict(VALID_BASE_FACT)
    del bad["relation"]
    path = _write_bank(tmp_path, [bad])
    report = validate_fact_bank(path)
    assert not report.is_valid
    assert any("relation" in i.message for i in report.errors)


def test_duplicate_id_is_an_error(tmp_path: Path) -> None:
    path = _write_bank(tmp_path, [dict(VALID_BASE_FACT), dict(VALID_BASE_FACT)])
    report = validate_fact_bank(path)
    assert not report.is_valid
    assert any(i.message == "duplicate id" for i in report.errors)


def test_non_approved_domain_is_a_warning_not_an_error(tmp_path: Path) -> None:
    odd_domain = dict(VALID_BASE_FACT, domain="languages")
    path = _write_bank(tmp_path, [odd_domain])
    report = validate_fact_bank(path)
    assert report.is_valid, "a non-approved domain must not fail validation, only warn"
    assert any("not one of the 8 approved" in i.message for i in report.warnings)


def test_distractor_referencing_unknown_base_is_an_error(tmp_path: Path) -> None:
    orphan_distractor = {
        "id": "f_999_dist",
        "domain": "health",
        "entity": "user_sister",
        "relation": "allergic_to",
        "value": "peanuts",
        "distractor_of": "f_does_not_exist",
        "surface": {"hi": "x", "en": "x", "hi-en": "x"},
        "probe_questions": {"hi": "x", "en": "x", "hi-en": "x"},
    }
    path = _write_bank(tmp_path, [orphan_distractor])
    report = validate_fact_bank(path)
    assert not report.is_valid
    assert any("unknown fact id" in i.message for i in report.errors)


def test_distractor_not_matching_near_miss_rule_is_a_warning(tmp_path: Path) -> None:
    base = dict(VALID_BASE_FACT)
    # Differs in BOTH entity and value from the base -- neither entity-shift nor
    # value-shift per BENCHMARK_SPEC.md Section 4.
    malformed_distractor = {
        "id": "f_001_dist",
        "domain": "health",
        "entity": "user_sister",
        "relation": "allergic_to",
        "value": "walnuts",
        "distractor_of": "f_001",
        "surface": {"hi": "x", "en": "x", "hi-en": "x"},
        "probe_questions": {"hi": "x", "en": "x", "hi-en": "x"},
    }
    path = _write_bank(tmp_path, [base, malformed_distractor])
    report = validate_fact_bank(path)
    assert report.is_valid, "a malformed near-miss pair should warn, not hard-fail"
    assert any("entity-shift or value-shift" in i.message for i in report.warnings)


def test_valid_entity_shift_distractor_has_no_warning(tmp_path: Path) -> None:
    base = dict(VALID_BASE_FACT)
    entity_shift_distractor = {
        "id": "f_001_dist",
        "domain": "health",
        "entity": "user_sister",
        "relation": "allergic_to",
        "value": "peanuts",  # same relation + value, different entity
        "distractor_of": "f_001",
        "surface": {"hi": "x", "en": "x", "hi-en": "x"},
        "probe_questions": {"hi": "x", "en": "x", "hi-en": "x"},
    }
    path = _write_bank(tmp_path, [base, entity_shift_distractor])
    report = validate_fact_bank(path)
    assert report.is_valid
    assert not any("entity-shift or value-shift" in i.message for i in report.warnings)


def test_update_block_missing_updated_value_is_an_error(tmp_path: Path) -> None:
    bad = dict(
        VALID_BASE_FACT,
        update={
            "updated_value": "",
            "surface": {"hi": "x", "en": "x", "hi-en": "x"},
            "probe_questions": {"hi": "x", "en": "x"},
        },
    )
    path = _write_bank(tmp_path, [bad])
    report = validate_fact_bank(path)
    assert not report.is_valid
    assert any("update.updated_value" in i.message for i in report.errors)


def test_update_probe_questions_does_not_require_hi_en(tmp_path: Path) -> None:
    # BENCHMARK_SPEC.md Section 2.1: update.probe_questions is documented with
    # only hi/en -- a missing hi-en key here must NOT be flagged as an error.
    ok = dict(
        VALID_BASE_FACT,
        update={
            "updated_value": "cashews",
            "surface": {"hi": "x", "en": "x", "hi-en": "x"},
            "probe_questions": {"hi": "x", "en": "x"},
        },
    )
    path = _write_bank(tmp_path, [ok])
    report = validate_fact_bank(path)
    assert report.is_valid
    assert not any("update.probe_questions" in i.message for i in report.issues)


def test_missing_file_is_an_error() -> None:
    report = validate_fact_bank("data/does_not_exist.yaml")
    assert not report.is_valid
    assert any("not found" in i.message for i in report.errors)


def test_production_fact_bank_has_zero_schema_errors() -> None:
    """Regression guard: the real pilot fact bank must stay schema-valid.

    Warnings are expected and informational (e.g. the 'languages' domain isn't
    one of the 8 approved domains, and the distractor ratio is below the 30%
    target for a 20-fact pilot bank) -- this only asserts there are no ERRORS.
    """
    report = validate_fact_bank("data/facts_v1.yaml")
    assert report.is_valid, f"data/facts_v1.yaml has schema errors: {report.errors}"
    assert report.total_facts == 20
