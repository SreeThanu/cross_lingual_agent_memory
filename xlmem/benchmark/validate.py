"""Fact bank schema validator.

Checks a fact bank YAML file against the schema in BENCHMARK_SPEC.md Section 2
(and the near-miss distractor rules in Section 4) before it reaches the session
generator or a live experiment run. Pure static analysis over the YAML: no model
calls, no network access, and it never mutates the fact bank file.

This exists as a P1 (benchmark construction) gate: as the fact bank grows from
the 20-fact pilot toward the ~250-fact target across 8 domains, authoring
mistakes (a missing translation, a malformed distractor pair, an empty probe
question) should be caught here, at construction time -- not discovered mid-run
or, worse, silently treated as a Write/Retrieval failure by the scorer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# BENCHMARK_SPEC.md Section 3: the 8 approved domains, as they appear in the
# `domain` field of data/facts_v1.yaml.
APPROVED_DOMAINS = {
    "health",  # Health & Medical
    "dining",  # Food & Dining
    "work",  # Professional & Work
    "travel",  # Travel & Geography
    "family",  # Family & Relationships
    "finance",  # Financial & Administrative
    "hobbies",  # Hobbies & Entertainment
    "tech",  # Technology & Devices
}

REQUIRED_SURFACE_LANGS = {"hi", "en", "hi-en"}
REQUIRED_PROBE_LANGS = {"hi", "en", "hi-en"}
# BENCHMARK_SPEC.md Section 2.1: update.probe_questions is documented with only
# hi/en entries (no hi-en) -- this is the spec's schema, not an omission here.
REQUIRED_UPDATE_PROBE_LANGS = {"hi", "en"}

BASE_ID_PATTERN = re.compile(r"^f_\d{3}$")
DISTRACTOR_ID_PATTERN = re.compile(r"^f_\d{3}_dist\d*$")

# BENCHMARK_SPEC.md Section 4: near-miss distractors are either an entity-shift
# (same relation+value, different entity) or a value-shift (same entity+relation,
# different value) pair relative to their base fact.
TARGET_DISTRACTOR_RATIO = 0.30


@dataclass
class ValidationIssue:
    fact_id: str
    severity: str  # "error" | "warning"
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    domain_counts: dict[str, int] = field(default_factory=dict)
    total_facts: int = 0
    total_distractors: int = 0
    total_updates: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        """True iff there are no schema ERRORS. Warnings (e.g. distractor ratio
        below target, a non-approved domain) do not fail validation -- a
        partially-built fact bank is expected to carry warnings until P1
        content authoring is complete."""
        return not self.errors


def _check_surface(
    fact_id: str, surface: Any, required: set[str], field_name: str, report: ValidationReport
) -> None:
    if not isinstance(surface, dict):
        report.issues.append(ValidationIssue(fact_id, "error", f"{field_name} is not a mapping"))
        return
    missing = required - set(surface.keys())
    if missing:
        report.issues.append(
            ValidationIssue(
                fact_id, "error", f"{field_name} missing language(s): {sorted(missing)}"
            )
        )
    for lang, text in surface.items():
        if lang in required and not str(text).strip():
            report.issues.append(
                ValidationIssue(fact_id, "error", f"{field_name}[{lang}] is empty")
            )


def validate_fact_bank(path: str | Path) -> ValidationReport:
    """Validate a fact bank YAML file against BENCHMARK_SPEC.md Section 2.

    Read-only: never writes to `path`.
    """
    p = Path(path)
    report = ValidationReport()
    if not p.exists():
        report.issues.append(ValidationIssue("<file>", "error", f"Fact bank not found: {p}"))
        return report

    with open(p, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)

    if not isinstance(payload, dict) or "facts" not in payload:
        report.issues.append(
            ValidationIssue("<file>", "error", "YAML missing top-level 'facts' key")
        )
        return report

    raw_facts = payload["facts"]
    report.total_facts = len(raw_facts)
    ids_by_fact: dict[str, dict] = {str(item.get("id", "")): item for item in raw_facts}
    seen_ids: set[str] = set()

    for item in raw_facts:
        fid = str(item.get("id", "<missing-id>"))

        if fid in seen_ids:
            report.issues.append(ValidationIssue(fid, "error", "duplicate id"))
        seen_ids.add(fid)

        is_distractor = item.get("distractor_of") is not None
        if is_distractor and not DISTRACTOR_ID_PATTERN.match(fid):
            report.issues.append(
                ValidationIssue(
                    fid, "warning", "distractor id does not match f_<3digit>_dist[N] pattern"
                )
            )
        elif not is_distractor and not BASE_ID_PATTERN.match(fid):
            report.issues.append(
                ValidationIssue(fid, "warning", "base fact id does not match f_<3digit> pattern")
            )

        for req_field in ("domain", "entity", "relation", "value"):
            if not str(item.get(req_field, "")).strip():
                report.issues.append(
                    ValidationIssue(fid, "error", f"missing/empty required field '{req_field}'")
                )

        domain = item.get("domain")
        if domain:
            report.domain_counts[domain] = report.domain_counts.get(domain, 0) + 1
            if domain not in APPROVED_DOMAINS:
                report.issues.append(
                    ValidationIssue(
                        fid,
                        "warning",
                        f"domain '{domain}' is not one of the 8 approved BENCHMARK_SPEC.md "
                        f"domains: {sorted(APPROVED_DOMAINS)}",
                    )
                )

        _check_surface(fid, item.get("surface", {}), REQUIRED_SURFACE_LANGS, "surface", report)
        _check_surface(
            fid, item.get("probe_questions", {}), REQUIRED_PROBE_LANGS, "probe_questions", report
        )

        if is_distractor:
            report.total_distractors += 1
            base_id = item.get("distractor_of")
            base_item = ids_by_fact.get(base_id)
            if base_item is None:
                report.issues.append(
                    ValidationIssue(
                        fid, "error", f"distractor_of references unknown fact id '{base_id}'"
                    )
                )
            else:
                same_relation = item.get("relation") == base_item.get("relation")
                same_entity = item.get("entity") == base_item.get("entity")
                same_value = item.get("value") == base_item.get("value")
                entity_shift = same_relation and same_value and not same_entity
                value_shift = same_relation and same_entity and not same_value
                if not (entity_shift or value_shift):
                    report.issues.append(
                        ValidationIssue(
                            fid,
                            "warning",
                            "distractor is not an entity-shift or value-shift pair relative to "
                            "its base fact per BENCHMARK_SPEC.md Section 4",
                        )
                    )

        update = item.get("update")
        if update is not None:
            report.total_updates += 1
            if not str(update.get("updated_value", "")).strip():
                report.issues.append(
                    ValidationIssue(fid, "error", "update.updated_value is missing/empty")
                )
            _check_surface(
                fid, update.get("surface", {}), REQUIRED_SURFACE_LANGS, "update.surface", report
            )
            _check_surface(
                fid,
                update.get("probe_questions", {}),
                REQUIRED_UPDATE_PROBE_LANGS,
                "update.probe_questions",
                report,
            )

    base_fact_count = report.total_facts - report.total_distractors
    if base_fact_count > 0:
        actual_ratio = report.total_distractors / base_fact_count
        if actual_ratio < TARGET_DISTRACTOR_RATIO:
            report.issues.append(
                ValidationIssue(
                    "<bank>",
                    "warning",
                    f"distractor ratio {actual_ratio:.0%} of base facts is below the "
                    f"BENCHMARK_SPEC.md Section 4 target of {TARGET_DISTRACTOR_RATIO:.0%}",
                )
            )

    return report


def format_report(report: ValidationReport) -> str:
    """Render a ValidationReport as human-readable text for CLI output."""
    base_fact_count = report.total_facts - report.total_distractors
    ratio_str = f"{report.total_distractors / base_fact_count:.0%}" if base_fact_count else "n/a"
    lines = [
        f"Fact bank: {report.total_facts} facts, {report.total_distractors} distractors "
        f"({ratio_str} of base facts)",
        f"Domains: {dict(sorted(report.domain_counts.items()))}",
        f"Facts with update blocks: {report.total_updates}",
    ]
    if report.errors:
        lines.append(f"\n{len(report.errors)} ERROR(S):")
        lines.extend(f"  [{i.fact_id}] {i.message}" for i in report.errors)
    if report.warnings:
        lines.append(f"\n{len(report.warnings)} WARNING(S):")
        lines.extend(f"  [{i.fact_id}] {i.message}" for i in report.warnings)
    if not report.errors and not report.warnings:
        lines.append("\nNo issues found.")
    return "\n".join(lines)
