"""Metric policies for metrics v3 (METRICS_SPEC §3.5.8-§3.5.9; decisions D1.6-D1.10, O3, O6).

Each policy states which support statuses count. UNRESOLVED evidence never counts as a write,
hit, duplicate, merge or staleness event; it is counted and reported, and an unresolved share
above UNRESOLVED_THRESHOLD sets an insufficient-validation flag without changing any score.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from xlmem.benchmark.facts import ProbeResult
from xlmem.scoring.matching import AFFIRMED, AMBIGUOUS, ASSERTED, split_sentences
from xlmem.scoring.staleness import (
    MISS,
    MISSING_OR_INVALID,
    STALE,
    UPDATED,
    WRITE_INELIGIBLE,
    InvalidReprobe,
)
from xlmem.scoring.support import (
    DISTRACTOR,
    LATER,
    SNAPSHOT_A,
    SUPPORTED,
    UNKNOWN,
    UNRESOLVED,
    MatchBank,
    Support,
    attribute_subject,
    framed_mentions,
    support,
)

UNRESOLVED_THRESHOLD = 0.10  # O6, provisional


def _share(num: int, den: int) -> float | None:
    return num / den if den else None


# --- WF and plant DR (Snapshot A) ---------------------------------------------------------


def _planted_base(bank: MatchBank, planted_ids: Sequence[str]) -> list[str]:
    ids = dict.fromkeys(planted_ids)
    return [f for f in ids if f in bank.facts and bank.facts[f].distractor_of is None]


def write_fidelity_v3(
    bank: MatchBank, planted_ids: Sequence[str], plant_texts: Sequence[str] | None, store_lang: str
) -> dict[str, Any]:
    """WF over intended planted base facts: written iff a Snapshot A record SUPPORTS it."""
    base = _planted_base(bank, planted_ids)
    out: dict[str, Any] = {
        "population": len(base), "written": [], "confirmed": [], "provisional": [],
        "unresolved": [], "write_fidelity": None, "wf_confirmed": None, "invalid_reason": None,
    }  # fmt: skip
    if plant_texts is None:
        out["invalid_reason"] = "store_after_plant.json missing"
        return out
    if not base:
        out["invalid_reason"] = "no planted base facts in run_log.jsonl"
        return out
    for fid in base:
        sups = [support(t, fid, bank, store_lang, SNAPSHOT_A) for t in plant_texts]
        if any(s.status == SUPPORTED for s in sups):
            out["written"].append(fid)
            if any(s.status == SUPPORTED and not s.provisional for s in sups):
                out["confirmed"].append(fid)
            else:
                out["provisional"].append(fid)
        elif any(s.status == UNRESOLVED for s in sups):
            out["unresolved"].append(fid)
    out["write_fidelity"] = len(out["written"]) / len(base)
    out["wf_confirmed"] = len(out["confirmed"]) / len(base)
    return out


def plant_duplication_v3(
    bank: MatchBank, planted_ids: Sequence[str], plant_texts: Sequence[str] | None, store_lang: str
) -> dict[str, Any]:
    """DR on Snapshot A: N(f) = records that SUPPORT f, not records that merely hold the value."""
    base = _planted_base(bank, planted_ids)
    out: dict[str, Any] = {
        "population": len(base), "records_per_fact": {}, "provisional_records": 0,
        "unresolved_facts": [], "plant_duplication_rate": None, "invalid_reason": None,
    }  # fmt: skip
    if plant_texts is None:
        out["invalid_reason"] = "store_after_plant.json missing; no fallback to the final store"
        return out
    if not base:
        out["invalid_reason"] = "no planted base facts in run_log.jsonl"
        return out
    excess = 0
    for fid in base:
        sups = [support(t, fid, bank, store_lang, SNAPSHOT_A) for t in plant_texts]
        n = sum(1 for s in sups if s.status == SUPPORTED)
        out["records_per_fact"][fid] = n
        out["provisional_records"] += sum(
            1 for s in sups if s.status == SUPPORTED and s.provisional
        )
        if any(s.status == UNRESOLVED for s in sups):
            out["unresolved_facts"].append(fid)
        excess += max(0, n - 1)
    out["plant_duplication_rate"] = excess / len(base)
    return out


# --- Recall --------------------------------------------------------------------------------


def recall_v3(
    bank: MatchBank,
    eligible_ids: Sequence[str],
    probes: Sequence[ProbeResult],
    store_lang: str,
    snapshot_a_keys: set[tuple[str, ...]],
    ks: Sequence[int] = (1, 3, 5),
) -> dict[str, Any]:
    """Strict XL-Recall@k: a hit iff a top-k retrieved record SUPPORTS the fact. No fallback."""
    by_id = {p.fact_id: p for p in probes}
    eligible = list(dict.fromkeys(eligible_ids))
    out: dict[str, Any] = {"eligible": len(eligible)}
    for k in ks:
        hits = provisional = unresolved = distractor = 0
        for fid in eligible:
            probe = by_id.get(fid)
            if probe is None:
                continue
            texts = [m.text for m in probe.retrieved[:k]]
            sups = [support(t, fid, bank, store_lang, LATER, snapshot_a_keys) for t in texts]
            supported = [s for s in sups if s.status == SUPPORTED]
            if supported:
                hits += 1
                if all(s.provisional for s in supported):
                    provisional += 1
            elif any(s.status == UNRESOLVED for s in sups):
                unresolved += 1
            if any(
                support(t, d.id, bank, store_lang, LATER, snapshot_a_keys).status == SUPPORTED
                for d in bank.entity_shift(fid)
                for t in texts
            ):
                distractor += 1
        out[f"recall_at_{k}"] = _share(hits, len(eligible))
        out[f"recall_at_{k}_provisional_hits"] = provisional
        out[f"recall_at_{k}_unresolved"] = unresolved
        out[f"distractor_retrieval_at_{k}"] = _share(distractor, len(eligible))
    return out


# --- SR / MR -------------------------------------------------------------------------------


def classify_reprobe_v3(answer: str, fid: str, bank: MatchBank, probe_lang: str) -> dict[str, Any]:
    """UPDATED / STALE / MISS relative to this fact's old and corrected values (§3.5.8).

    Mentions whose sentence is about the distractor are ignored; an AMBIGUOUS or UNKNOWN
    subject makes the mention AMBIGUOUS. `unresolved` marks a MISS caused by ambiguity.
    """
    mentions, lex = framed_mentions(answer, bank, probe_lang)
    cues = [c for d in bank.entity_shift(fid) for c in bank.subject_cues(d.id, probe_lang)]
    sentences = split_sentences(answer)
    old: list[str] = []
    new: list[str] = []
    ignored = 0
    for m in mentions:
        if m.target.owner != fid or m.target.role not in ("value", "updated_value"):
            continue
        subj = attribute_subject(sentences[m.sentence], cues, lex, "answer", guarantee=True)
        if subj.label == DISTRACTOR:
            ignored += 1
            continue
        frame = AMBIGUOUS if subj.label in (AMBIGUOUS, UNKNOWN) else m.frame
        (old if m.target.role == "value" else new).append(frame)
    unresolved = False
    if any(f in (ASSERTED, AFFIRMED) for f in old):
        outcome = STALE
    elif AMBIGUOUS in old:
        outcome, unresolved = MISS, True
    elif any(f in (ASSERTED, AFFIRMED) for f in new):
        outcome = UPDATED
    else:
        outcome, unresolved = MISS, AMBIGUOUS in new
    return {
        "outcome": outcome, "unresolved": unresolved, "old_frames": old,
        "new_frames": new, "distractor_mentions_ignored": ignored,
    }  # fmt: skip


def staleness_v3(
    bank: MatchBank,
    corrected_ids: Sequence[str],
    written_ids: set[str] | None,
    provisional_ids: set[str],
    reprobes: Sequence[ProbeResult | InvalidReprobe],
) -> dict[str, Any]:
    """SR/MR with the D6 eligibility rules (v2.1) and the v3 classifier and write gate."""
    corrected = list(dict.fromkeys(corrected_ids))
    rows: dict[str, list[ProbeResult | InvalidReprobe]] = {}
    unattributed = [r for r in reprobes if isinstance(r, InvalidReprobe) and r.fact_id is None]
    for r in reprobes:
        if r.fact_id is not None:
            rows.setdefault(r.fact_id, []).append(r)
    counts = {UPDATED: 0, STALE: 0, MISS: 0, WRITE_INELIGIBLE: 0, MISSING_OR_INVALID: 0}
    bad_refs = unresolved = gated_provisional = 0
    per_fact: list[dict[str, Any]] = []
    for fid in corrected:
        entry: dict[str, Any] = {"fact_id": fid}
        fact = bank.facts.get(fid)
        got = rows.get(fid, [])
        if written_ids is None:
            entry["status"], entry["reason"] = None, "Snapshot A missing; write gate not applicable"
        elif fact is None or fact.update_data is None:
            entry["status"] = MISSING_OR_INVALID
            entry["reason"] = (
                "correction for a fact_id not in the fact bank"
                if fact is None
                else ("correction for a fact with no update block in the fact bank")
            )
            bad_refs += 1
        elif fid not in written_ids:
            entry["status"], entry["reason"] = (
                WRITE_INELIGIBLE,
                "original value not written (WF v3)",
            )
        elif len(got) != 1:
            entry["status"] = MISSING_OR_INVALID
            entry["reason"] = f"{len(got)} reprobe_result records (need exactly 1)"
            entry["malformed"] = [r.reason for r in got if isinstance(r, InvalidReprobe)]
        elif isinstance(got[0], InvalidReprobe):
            entry["status"], entry["reason"] = (
                MISSING_OR_INVALID,
                f"malformed reprobe_result: {got[0].reason}",
            )
        else:
            probe = got[0]
            lang = probe.probe_lang
            if not (
                bank.has_lang_targets(fid, "value", lang)
                and bank.has_lang_targets(fid, "updated_value", lang)
            ):
                entry["status"] = MISSING_OR_INVALID
                entry["reason"] = f"no tier-A/B targets for probe_lang {lang!r}"
            else:
                cls = classify_reprobe_v3(probe.response, fid, bank, lang)
                entry.update(status=cls["outcome"], probe_lang=lang, evidence=cls)
                unresolved += cls["unresolved"]
                gated_provisional += fid in provisional_ids
        if entry["status"] is not None:
            counts[entry["status"]] += 1
        per_fact.append(entry)

    eligible = counts[UPDATED] + counts[STALE] + counts[MISS]
    rep: dict[str, Any] = {
        "corrected_count": len(corrected), "eligible_corrections": eligible,
        "updated_count": counts[UPDATED], "stale_count": counts[STALE], "miss_count": counts[MISS],
        "write_ineligible_count": counts[WRITE_INELIGIBLE],
        "missing_or_invalid_reprobe_count": counts[MISSING_OR_INVALID],
        "unresolved_count": unresolved, "gated_on_provisional_write": gated_provisional,
        "staleness_rate": None, "miss_rate": None, "write_ineligible_rate": None,
        "invalid_reason": None, "unattributed_invalid_reprobes": [r.reason for r in unattributed],
        "per_fact": per_fact,
    }  # fmt: skip
    if not corrected:
        rep["invalid_reason"] = "no correction turn in run_log.jsonl"
        return rep
    if written_ids is None:
        rep["invalid_reason"] = "store_after_plant.json missing; write gate not applicable"
        return rep
    if len(corrected) != counts[WRITE_INELIGIBLE] + counts[MISSING_OR_INVALID] + eligible:
        raise RuntimeError(f"SR counts do not reconcile: {counts} vs {len(corrected)} corrected")
    rep["write_ineligible_rate"] = counts[WRITE_INELIGIBLE] / len(corrected)
    if counts[MISSING_OR_INVALID]:
        parts = []
        if counts[MISSING_OR_INVALID] - bad_refs:
            parts.append(
                f"{counts[MISSING_OR_INVALID] - bad_refs} write-eligible correction(s) "
                "without a valid re-probe"
            )
        if bad_refs:
            parts.append(
                f"{bad_refs} correction(s) for an unknown fact or a fact with no update block"
            )
        rep["invalid_reason"] = "; ".join(parts)
        return rep
    if unattributed:
        rep["invalid_reason"] = (
            f"{len(unattributed)} malformed reprobe_result record(s) with no usable fact_id"
        )
        return rep
    if eligible == 0:
        rep["invalid_reason"] = "no eligible corrections (all corrected facts write-ineligible)"
        return rep
    rep["staleness_rate"] = counts[STALE] / eligible
    rep["miss_rate"] = counts[MISS] / eligible
    return rep


# --- FMR (final store, snapshot-aware) -------------------------------------------------------

JOINT = "JOINT"
WRONG_PERSON = "WRONG_PERSON"
OVERWRITTEN = "OVERWRITTEN"
SEPARATED = "SEPARATED"
BASE_LOST = "BASE_LOST"
LOST = "LOST"
FMR_UNRESOLVED = "UNRESOLVED"


def _sentences(sups: Sequence[Support]) -> list[Any]:
    return [e for s in sups for e in s.sentences]


def classify_pair_v3(
    bank: MatchBank,
    fid: str,
    did: str,
    plant_texts: Sequence[str],
    final_texts: Sequence[str],
    store_lang: str,
    snapshot_a_keys: set[tuple[str, ...]],
) -> tuple[str, bool]:
    """FMR category of one (base, distractor) pair and whether it is an FMR event (§3.5.8)."""
    f_b = [support(t, fid, bank, store_lang, LATER, snapshot_a_keys) for t in final_texts]
    d_b = [support(t, did, bank, store_lang, LATER, snapshot_a_keys) for t in final_texts]
    f_sup = any(s.status == SUPPORTED for s in f_b)
    d_sup = any(s.status == SUPPORTED for s in d_b)
    f_ev, d_ev = _sentences(f_b), _sentences(d_b)

    if bank.is_entity_shift_distractor(did):
        joint = any(e.status == UNRESOLVED and e.subject == AMBIGUOUS for e in f_ev)
        d_cue_with_value = any(e.subject == DISTRACTOR for e in f_ev)
        explicit_new = any(
            e.status == SUPPORTED and e.explicit_user and e.tokens not in snapshot_a_keys
            for e in f_ev
        )
        unknown_new = any(
            e.status == UNRESOLVED and e.subject == UNKNOWN and e.tokens not in snapshot_a_keys
            for e in f_ev
        )
        if joint and not d_sup:
            return JOINT, True
        if not d_sup and not d_cue_with_value and explicit_new:
            return WRONG_PERSON, True
        if f_sup and d_sup:
            return SEPARATED, False
        if not d_sup and unknown_new:
            return FMR_UNRESOLVED, False
        if d_sup:
            return BASE_LOST, False
        return LOST, False

    f_a = any(
        support(t, fid, bank, store_lang, SNAPSHOT_A).status == SUPPORTED for t in plant_texts
    )
    f_keys = {e.tokens for e in f_ev if e.status == SUPPORTED}
    joint = any(e.status == SUPPORTED and e.tokens in f_keys for e in d_ev)
    if f_a and not f_sup and d_sup:
        return OVERWRITTEN, True
    if joint:
        return JOINT, False  # O3: a value-shift joint record is not automatically a false merge
    if f_sup and d_sup:
        return SEPARATED, False
    if any(e.status == UNRESOLVED for e in f_ev + d_ev):
        return FMR_UNRESOLVED, False
    if d_sup:
        return BASE_LOST, False
    return LOST, False


def false_merge_v3(
    bank: MatchBank,
    injected_distractor_ids: Sequence[str],
    plant_texts: Sequence[str] | None,
    final_texts: Sequence[str],
    store_lang: str,
) -> dict[str, Any]:
    """FMR = events / pairs, over pairs whose distractor turn actually occurs in the log."""
    snap = {tuple(s) for t in plant_texts or [] for s in split_sentences(t)}
    pairs = [
        (bank.facts[d].distractor_of, d)
        for d in dict.fromkeys(injected_distractor_ids)
        if d in bank.facts and bank.facts[d].distractor_of in bank.facts
    ]
    out: dict[str, Any] = {
        "pairs": len(pairs),
        "categories": {},
        "events": 0,
        "unresolved": 0,
        "false_merge_rate": None,
        "invalid_reason": None,
    }
    if plant_texts is None:
        out["invalid_reason"] = "store_after_plant.json missing (needed for snapshot-aware FMR)"
        return out
    if not pairs:
        out["invalid_reason"] = "no distractor turn in run_log.jsonl"
        return out
    for fid, did in pairs:
        cat, event = classify_pair_v3(
            bank, str(fid), did, plant_texts, final_texts, store_lang, snap
        )
        out["categories"][f"{fid}/{did}"] = cat
        out["events"] += event
        out["unresolved"] += cat == FMR_UNRESOLVED
    out["false_merge_rate"] = out["events"] / len(pairs)
    return out


# --- unresolved / relation-unverified reporting (O6) ------------------------------------------


def validation_report(
    wf: dict[str, Any], dr: dict[str, Any], recall: dict[str, Any], sr: dict[str, Any],
    fmr: dict[str, Any], ks: Sequence[int] = (1, 3, 5),
) -> dict[str, Any]:  # fmt: skip
    """Unresolved shares (with denominators), relation-unverified shares, and flags."""
    unresolved: dict[str, Any] = {
        "write_fidelity": (len(wf["unresolved"]), wf["population"]),
        "plant_duplication_rate": (len(dr["unresolved_facts"]), dr["population"]),
        "staleness_rate": (sr["unresolved_count"], sr["eligible_corrections"]),
        "false_merge_rate": (fmr["unresolved"], fmr["pairs"]),
    }
    for k in ks:
        unresolved[f"recall_at_{k}"] = (recall[f"recall_at_{k}_unresolved"], recall["eligible"])
    shares = {
        m: {"count": c, "denominator": d, "share": _share(c, d)} for m, (c, d) in unresolved.items()
    }
    flags = {
        m: f"{v['share']:.2f} unresolved > {UNRESOLVED_THRESHOLD:.2f}"
        for m, v in shares.items()
        if v["share"] is not None and v["share"] > UNRESOLVED_THRESHOLD
    }
    hits1 = round((recall.get("recall_at_1") or 0) * recall["eligible"])
    supporting = sum(dr["records_per_fact"].values())

    def _unverified(count: int, credited: int) -> dict[str, Any]:
        return {"count": count, "of_credited": credited, "share": _share(count, credited)}

    unverified = {
        "write_fidelity": _unverified(len(wf["provisional"]), len(wf["written"])),
        "recall_at_1": _unverified(recall.get("recall_at_1_provisional_hits", 0), hits1),
        "plant_duplication_rate": _unverified(dr["provisional_records"], supporting),
    }
    return {
        "unresolved": shares,
        "relation_unverified": unverified,
        "insufficient_validation": flags,
    }


def evidence_dict(s: Support) -> dict[str, Any]:
    return {"status": s.status, "provisional": s.provisional,
            "sentences": [asdict(e) for e in s.sentences]}  # fmt: skip
