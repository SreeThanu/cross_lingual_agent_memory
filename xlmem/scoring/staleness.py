"""Scoring logic for Staleness Rate (SR) following memory updates.

v2 (METRICS_SPEC.md §2.4, §3.3, §3.4; decision D6) is the official definition.
v1 (`compute_staleness_rate`) is kept only so the superseded numbers can be reproduced.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from xlmem.benchmark.facts import Fact, ProbeResult
from xlmem.scoring.aliases import ValueAliases
from xlmem.scoring.judge import strict_match

UPDATED = "UPDATED"
STALE = "STALE"
MISS = "MISS"
WRITE_INELIGIBLE = "write_ineligible"
MISSING_OR_INVALID = "missing_or_invalid"

ASSERTED = "ASSERTED"
AFFIRMED = "AFFIRMED"
NEGATED = "NEGATED"
AMBIGUOUS = "AMBIGUOUS"

# METRICS_SPEC §3.3 item 5. Changing any of these changes SR: bump the metrics version.
_SENTENCE_BREAK = re.compile(r"[.!?।॥;\n]")
_NEGATION_TOKENS = frozenset({"not", "no", "never", "नहीं", "न", "मत"})
_EN_NEG_BEFORE_3 = frozenset({"not", "no", "never"})
_EN_INSTEAD_BEFORE = (("instead", "of"), ("rather", "than"))
_EN_PAST_BEFORE_4 = frozenset({"previously", "earlier", "formerly"})
_EN_PAST_BEFORE_3 = frozenset({"was", "were"})
_HI_NEG_AFTER_2 = frozenset({"नहीं"})
_HI_NA_KI_BEFORE = ("न", "कि")
_HI_BAJAY_AFTER_2 = frozenset({"बजाय"})
_HI_PAST_BEFORE_4 = frozenset({"पहले"})
_HI_PAST_AFTER_3 = frozenset({"था", "थी", "थे"})
_CONTRAST_BEFORE_2 = frozenset({"but", "बल्कि"})
_CUE_LEXICON = frozenset(
    {
        "not", "no", "never", "nor", "neither", "instead", "rather", "but", "however",
        "although", "though", "longer", "t", "was", "were", "previously", "earlier",
        "formerly", "used",
        "नहीं", "न", "मत", "बजाय", "लेकिन", "परंतु", "किंतु", "बल्कि", "पहले", "था", "थी", "थे",
    }
)  # fmt: skip


def _is_token_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "M") or cat == "Nd"


def tokenize(text: str) -> list[str]:
    """Split text into NFC-casefolded tokens of letters, marks and digits (keeps vowel signs)."""
    text = unicodedata.normalize("NFC", text).casefold().replace("_", " ")
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        if _is_token_char(ch):
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def split_sentences(text: str) -> list[list[str]]:
    """Tokenized sentences of an answer; sentence breaks are . ! ? । ॥ ; and newline."""
    return [toks for part in _SENTENCE_BREAK.split(text) if (toks := tokenize(part))]


def _target_variants(target: str) -> list[tuple[str, ...]]:
    toks = tokenize(target)
    if not toks:
        return []
    variants = [tuple(toks)]
    last = toks[-1]
    if last.isascii() and last.isalpha():
        if last.endswith("s") and len(last) > 3:
            variants.append(tuple(toks[:-1] + [last[:-1]]))
        elif len(last) > 2:
            variants.append(tuple(toks[:-1] + [last + "s"]))
    return variants


@dataclass(frozen=True)
class Mention:
    """One whole-token occurrence of a target in a sentence, with its frame."""

    target: str
    sentence: int
    start: int
    end: int
    frame: str


def _frame(tokens: list[str], start: int, end: int) -> str:
    before2 = tokens[max(0, start - 2) : start]
    before3 = tokens[max(0, start - 3) : start]
    before4 = tokens[max(0, start - 4) : start]
    after2 = tokens[end : end + 2]
    after3 = tokens[end : end + 3]
    pair_before = tuple(tokens[start - 2 : start]) if start >= 2 else ()

    for k in range(len(before2) - 1, -1, -1):
        if before2[k] in _CONTRAST_BEFORE_2:
            between = before2[k + 1 :]
            if not any(t in _NEGATION_TOKENS for t in between):
                return AFFIRMED
            break
    if end < len(tokens) and tokens[end] in ("instead", "not"):
        return AFFIRMED
    for k in range(end, min(end + 4, len(tokens) - 1)):
        if tokens[k] in _NEGATION_TOKENS and (tokens[k], tokens[k + 1]) != _HI_NA_KI_BEFORE:
            break
        if (tokens[k], tokens[k + 1]) == _HI_NA_KI_BEFORE:
            return AFFIRMED

    if (
        any(t in _EN_NEG_BEFORE_3 for t in before3)
        or pair_before in _EN_INSTEAD_BEFORE
        or any(t in _EN_PAST_BEFORE_4 for t in before4)
        or any(tokens[k : k + 2] == ["used", "to"] for k in range(max(0, start - 6), start))
        or any(t in _EN_PAST_BEFORE_3 for t in before3)
        or any(t in _HI_NEG_AFTER_2 for t in after2)
        or pair_before == _HI_NA_KI_BEFORE
        or any(t in _HI_BAJAY_AFTER_2 for t in after2)
        or any(t in _HI_PAST_BEFORE_4 for t in before4)
        or any(t in _HI_PAST_AFTER_3 for t in after3)
    ):
        return NEGATED

    if any(t in _CUE_LEXICON for t in tokens):
        return AMBIGUOUS
    return ASSERTED


def find_mentions(response: str, targets: Sequence[str]) -> list[Mention]:
    """All whole-token mentions of any target in the response, each with its frame."""
    found: dict[tuple[int, int, int], Mention] = {}
    for s_idx, tokens in enumerate(split_sentences(response)):
        for target in targets:
            for variant in _target_variants(target):
                n = len(variant)
                for i in range(len(tokens) - n + 1):
                    if tuple(tokens[i : i + n]) == variant and (s_idx, i, i + n) not in found:
                        found[(s_idx, i, i + n)] = Mention(
                            target=target,
                            sentence=s_idx,
                            start=i,
                            end=i + n,
                            frame=_frame(tokens, i, i + n),
                        )
    return [found[k] for k in sorted(found)]


def sr_targets(
    fact: Fact, probe_lang: str, aliases: ValueAliases | None
) -> tuple[list[str], list[str]] | None:
    """Old and new targets for a fact (§3.3 item 4); None if a non-English probe lacks aliases."""
    if fact.update_data is None:
        return None
    updated_value = str(fact.update_data.get("updated_value") or "")
    old = [fact.value]
    new = [updated_value] if updated_value else []
    if probe_lang != "en":
        entry = aliases.for_fact(fact.id) if aliases is not None else None
        if entry is None:
            return None
        if not entry.value.get(probe_lang) or not entry.updated_value.get(probe_lang):
            return None
        old += list(entry.value[probe_lang])
        new += list(entry.updated_value[probe_lang])
    if not new:
        return None
    return old, new


@dataclass(frozen=True)
class ReprobeClassification:
    """Outcome of one eligible re-probe, with the evidence that decided it."""

    fact_id: str
    outcome: str
    old_mentions: tuple[Mention, ...]
    new_mentions: tuple[Mention, ...]


def classify_reprobe(
    fact_id: str, response: str, old: Sequence[str], new: Sequence[str]
) -> ReprobeClassification:
    """Classify a re-probe answer as UPDATED, STALE or MISS (METRICS_SPEC §3.3 item 6)."""
    old_m = tuple(find_mentions(response, old))
    new_m = tuple(find_mentions(response, new))
    if any(m.frame in (ASSERTED, AFFIRMED) for m in old_m):
        outcome = STALE
    elif any(m.frame == AMBIGUOUS for m in old_m):
        outcome = MISS
    elif any(m.frame in (ASSERTED, AFFIRMED) for m in new_m):
        outcome = UPDATED
    else:
        outcome = MISS
    return ReprobeClassification(fact_id, outcome, old_m, new_m)


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


@dataclass(frozen=True)
class InvalidReprobe:
    """A raw reprobe_result record that is not well-formed (METRICS_SPEC §2.4, v2.1).

    Kept, not dropped, so it still counts toward the exactly-one-record rule.
    `fact_id` is None when the record can't be attributed to a fact.
    """

    fact_id: str | None
    reason: str


def parse_reprobe_record(data: Any) -> ProbeResult | InvalidReprobe:
    """Validate one raw reprobe_result `data` payload; never coerces a bad field to text."""
    if not isinstance(data, dict):
        return InvalidReprobe(None, f"data is {type(data).__name__}, not a mapping")
    fact_id = data.get("fact_id")
    if not isinstance(fact_id, str) or not fact_id:
        return InvalidReprobe(None, "missing or non-string fact_id")
    for key in ("probe_lang", "store_lang"):
        if key not in data:
            return InvalidReprobe(fact_id, f"missing {key}")
        if not isinstance(data[key], str) or (key == "probe_lang" and not data[key]):
            return InvalidReprobe(fact_id, f"invalid {key}: {data[key]!r}")
    if "response" not in data:
        return InvalidReprobe(fact_id, "missing response")
    if not isinstance(data["response"], str):
        return InvalidReprobe(fact_id, f"response is {type(data['response']).__name__}, not str")
    retrieved = data.get("retrieved", [])
    if not isinstance(retrieved, list) or not all(
        isinstance(m, dict) and isinstance(m.get("metadata", {}), dict) for m in retrieved
    ):
        return InvalidReprobe(fact_id, "retrieved is not a list of memory records")
    return ProbeResult.from_dict(data)


def compute_staleness_v2(
    facts: Sequence[Fact],
    corrected_fact_ids: Sequence[str],
    written_fact_ids: set[str] | None,
    reprobe_results: Sequence[ProbeResult | InvalidReprobe],
    aliases: ValueAliases | None,
) -> dict[str, Any]:
    """Compute SR v2, Miss Rate and the eligibility counts for one seed (METRICS_SPEC §2.4).

    `written_fact_ids` is None when Snapshot A is missing (the write gate can't be applied).
    `reprobe_results` holds every raw reprobe_result record, malformed ones as InvalidReprobe
    (see parse_reprobe_record), so a malformed record can never hide a duplicate.
    """
    facts_by_id = {f.id: f for f in facts}
    corrected = list(dict.fromkeys(corrected_fact_ids))
    reprobes: dict[str, list[ProbeResult | InvalidReprobe]] = {}
    unattributed = [
        r for r in reprobe_results if isinstance(r, InvalidReprobe) and r.fact_id is None
    ]
    for r in reprobe_results:
        if r.fact_id is not None:
            reprobes.setdefault(r.fact_id, []).append(r)

    per_fact: list[dict[str, Any]] = []
    bad_references = 0  # corrections whose fact is unknown or has no update block
    counts = {UPDATED: 0, STALE: 0, MISS: 0, WRITE_INELIGIBLE: 0, MISSING_OR_INVALID: 0}

    for fid in corrected:
        entry: dict[str, Any] = {"fact_id": fid}
        fact = facts_by_id.get(fid)
        rows = reprobes.get(fid, [])
        if written_fact_ids is None:
            entry["status"] = None
            entry["reason"] = "Snapshot A missing; write gate not applicable"
        elif fact is None or fact.update_data is None:
            entry["status"] = MISSING_OR_INVALID
            entry["reason"] = (
                "correction for a fact_id not in the fact bank"
                if fact is None
                else "correction for a fact with no update block in the fact bank"
            )
            bad_references += 1
        elif fid not in written_fact_ids:
            entry["status"] = WRITE_INELIGIBLE
            entry["reason"] = "original value not written (WF, Snapshot A)"
        elif len(rows) != 1:
            entry["status"] = MISSING_OR_INVALID
            entry["reason"] = f"{len(rows)} reprobe_result records (need exactly 1)"
            entry["malformed"] = [r.reason for r in rows if isinstance(r, InvalidReprobe)]
        elif isinstance(rows[0], InvalidReprobe):
            entry["status"] = MISSING_OR_INVALID
            entry["reason"] = f"malformed reprobe_result: {rows[0].reason}"
        else:
            probe = rows[0]
            targets = sr_targets(fact, probe.probe_lang, aliases)
            if targets is None:
                entry["status"] = MISSING_OR_INVALID
                entry["reason"] = f"no authored aliases for probe_lang {probe.probe_lang!r}"
            else:
                cls = classify_reprobe(fid, probe.response, targets[0], targets[1])
                entry["status"] = cls.outcome
                entry["probe_lang"] = probe.probe_lang
                entry["old_targets"] = targets[0]
                entry["new_targets"] = targets[1]
                entry["old_mentions"] = [asdict(m) for m in cls.old_mentions]
                entry["new_mentions"] = [asdict(m) for m in cls.new_mentions]
        if entry["status"] is not None:
            counts[entry["status"]] += 1
        per_fact.append(entry)

    eligible = counts[UPDATED] + counts[STALE] + counts[MISS]
    report: dict[str, Any] = {
        "corrected_count": len(corrected),
        "eligible_corrections": eligible,
        "updated_count": counts[UPDATED],
        "stale_count": counts[STALE],
        "miss_count": counts[MISS],
        "write_ineligible_count": counts[WRITE_INELIGIBLE],
        "missing_or_invalid_reprobe_count": counts[MISSING_OR_INVALID],
        "staleness_rate": None,
        "miss_rate": None,
        "write_ineligible_rate": None,
        "invalid_reason": None,
        "unattributed_invalid_reprobes": [r.reason for r in unattributed],
        "per_fact": per_fact,
    }

    if not corrected:
        report["invalid_reason"] = "no correction turn in run_log.jsonl"
        return report
    if written_fact_ids is None:
        report["invalid_reason"] = "store_after_plant.json missing; write gate not applicable"
        return report

    if len(corrected) != counts[WRITE_INELIGIBLE] + counts[MISSING_OR_INVALID] + eligible:
        raise RuntimeError(f"SR counts do not reconcile: {counts} vs {len(corrected)} corrected")
    report["write_ineligible_rate"] = _rate(counts[WRITE_INELIGIBLE], len(corrected))
    if counts[MISSING_OR_INVALID]:
        reprobe_defects = counts[MISSING_OR_INVALID] - bad_references
        parts = []
        if reprobe_defects:
            parts.append(f"{reprobe_defects} write-eligible correction(s) without a valid re-probe")
        if bad_references:
            parts.append(
                f"{bad_references} correction(s) for an unknown fact or a fact with no update block"
            )
        report["invalid_reason"] = "; ".join(parts)
        return report
    if unattributed:
        report["invalid_reason"] = (
            f"{len(unattributed)} malformed reprobe_result record(s) with no usable fact_id"
        )
        return report
    if eligible == 0:
        report["invalid_reason"] = "no eligible corrections (all corrected facts write-ineligible)"
        return report
    report["staleness_rate"] = _rate(counts[STALE], eligible)
    report["miss_rate"] = _rate(counts[MISS], eligible)
    return report


def compute_staleness_rate(
    corrected_facts: Sequence[Fact],
    reprobe_results: Sequence[ProbeResult],
) -> float:
    """SUPERSEDED (metrics v1). Use compute_staleness_v2.

    Kept to reproduce v1 numbers and the staged D6 diagnostics. Its defects are listed in
    METRICS_SPEC §6: any answer without the new value counts as stale, English-only matching.
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
