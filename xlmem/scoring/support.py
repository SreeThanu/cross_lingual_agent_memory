"""Support evidence for metrics v3 (METRICS_SPEC §3.5.5-§3.5.7; decisions D1.5, O1, O2).

Turns foundation mentions into a judgement of whether a text supports a specific fact:
subject attribution (with the template guarantee), relation status, and a per-record
SUPPORTED / UNRESOLVED / NOT_SUPPORTED status. Metric policies are in metrics_v3.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from xlmem.benchmark.facts import Fact
from xlmem.scoring.alias_bank import AliasBankV2
from xlmem.scoring.matching import (
    AFFIRMED,
    AMBIGUOUS,
    ASSERTED,
    NEGATED,
    Lexicon,
    Mention,
    Target,
    analyze,
    find_spans,
    lexicon_for,
    make_target,
    resolve_past,
    split_sentences,
)

USER = "USER"
DISTRACTOR = "DISTRACTOR"
UNKNOWN = "UNKNOWN"

CONFIRMED = "CONFIRMED"
CONFLICTING = "CONFLICTING"

SUPPORTED = "SUPPORTED"
UNRESOLVED = "UNRESOLVED"
NOT_SUPPORTED = "NOT_SUPPORTED"
NONE = "NONE"  # the fact's value is not mentioned at all

SNAPSHOT_A = "snapshot_a"
LATER = "later"  # anything ingested after the plant phase (final store, retrieval)


class MatchBank:
    """Facts plus alias bank, with the target and cue lookups the support layer needs."""

    def __init__(
        self, facts: Sequence[Fact], aliases: AliasBankV2 | None, tiers: Sequence[str] = ("A", "B")
    ) -> None:
        self.facts = {f.id: f for f in facts}
        self.aliases = aliases
        self.tiers = tuple(tiers)

    def _langs(self, lang: str) -> list[str]:
        return ["en"] if lang == "en" else ["en", lang]

    def _alias_targets(self, fid: str, role: str, lang: str) -> list[Target]:
        if self.aliases is None:
            return []
        return [
            make_target(e.text, fid, role, e.tier)
            for e in self.aliases.get(fid, role, self._langs(lang), self.tiers)
        ]

    def value_targets(self, fid: str, lang: str, role: str = "value") -> list[Target]:
        fact = self.facts[fid]
        canonical = (
            fact.value
            if role == "value"
            else str((fact.update_data or {}).get("updated_value") or "")
        )
        out = [make_target(canonical, fid, role)] if canonical else []
        return out + self._alias_targets(fid, role, lang)

    def has_lang_targets(self, fid: str, role: str, lang: str) -> bool:
        return lang == "en" or bool(
            self.aliases and self.aliases.get(fid, role, [lang], self.tiers)
        )

    def all_value_targets(self, lang: str) -> list[Target]:
        out: list[Target] = []
        for fid, fact in self.facts.items():
            out += self.value_targets(fid, lang, "value")
            if fact.update_data:
                out += self.value_targets(fid, lang, "updated_value")
        return out

    def relation_cues(self, fid: str, lang: str) -> list[Target]:
        return self._alias_targets(fid, "relation_cue", lang)

    def subject_cues(self, fid: str, lang: str) -> list[Target]:
        return self._alias_targets(fid, "subject_cue", lang)

    def entity_shift(self, fid: str) -> list[Fact]:
        """Distractors of base fact `fid` that change the subject (same value, other entity)."""
        base = self.facts[fid]
        return [
            d for d in self.facts.values() if d.distractor_of == fid and d.entity != base.entity
        ]

    def value_shift(self, fid: str) -> list[Fact]:
        base = self.facts[fid]
        return [
            d for d in self.facts.values() if d.distractor_of == fid and d.entity == base.entity
        ]

    def is_entity_shift_distractor(self, fid: str) -> bool:
        f = self.facts[fid]
        base = self.facts.get(f.distractor_of or "")
        return base is not None and f.entity != base.entity


@dataclass(frozen=True)
class Subject:
    label: str  # USER / DISTRACTOR / AMBIGUOUS / UNKNOWN
    explicit_user: bool = False


def _cue_present(tokens: Sequence[str], targets: Sequence[Target]) -> bool:
    return bool(find_spans(tokens, [v for t in targets for v in t.variants()]))


def attribute_subject(
    tokens: Sequence[str],
    distractor_cues: Sequence[Target],
    lex: Lexicon,
    mode: str,
    guarantee: bool,
) -> Subject:
    """Subject of one sentence (METRICS_SPEC §3.5.5). Possessives are not user cues."""
    users = lex.user_answer if mode == "answer" else lex.user_record
    has_user = any(
        tok in users and not (i + 1 < len(tokens) and tokens[i + 1] == "s")
        for i, tok in enumerate(tokens)
    )
    has_dist = _cue_present(tokens, distractor_cues)
    if has_user and has_dist:
        return Subject(AMBIGUOUS)
    if has_dist:
        return Subject(DISTRACTOR)
    if has_user:
        return Subject(USER, explicit_user=True)
    if any(tok in lex.pronoun for tok in tokens):
        return Subject(UNKNOWN)
    return Subject(USER) if guarantee else Subject(UNKNOWN)


def relation_status(tokens: Sequence[str], fid: str, bank: MatchBank, lang: str) -> str:
    """CONFIRMED (own authored cue) / CONFLICTING (only another relation's cue) / UNKNOWN."""
    if _cue_present(tokens, bank.relation_cues(fid, lang)):
        return CONFIRMED
    rel = bank.facts[fid].relation
    others = [
        c
        for oid, o in bank.facts.items()
        if o.relation != rel
        for c in bank.relation_cues(oid, lang)
    ]
    return CONFLICTING if _cue_present(tokens, others) else UNKNOWN


@dataclass(frozen=True)
class SentenceEvidence:
    sentence: int
    tokens: tuple[str, ...]
    status: str
    reason: str
    frames: tuple[str, ...]
    subject: str | None = None
    explicit_user: bool = False
    relation: str | None = None
    provisional: bool = False


@dataclass(frozen=True)
class Support:
    status: str  # SUPPORTED / UNRESOLVED / NOT_SUPPORTED / NONE
    provisional: bool = False
    sentences: tuple[SentenceEvidence, ...] = field(default=())

    @property
    def explicit_user(self) -> bool:
        return any(s.status == SUPPORTED and s.explicit_user for s in self.sentences)


def framed_mentions(text: str, bank: MatchBank, lang: str) -> tuple[list[Mention], Lexicon]:
    """All bank value mentions in the text, frames resolved (PAST decided in context)."""
    lex = lexicon_for(lang)
    return resolve_past(analyze(text, bank.all_value_targets(lang), lex), text, lex), lex


def support(
    text: str,
    fid: str,
    bank: MatchBank,
    lang: str,
    phase: str,
    snapshot_a_keys: set[tuple[str, ...]] | frozenset[tuple[str, ...]] = frozenset(),
    mode: str = "record",
) -> Support:
    """Does this record (or answer) support fact `fid`'s value? (METRICS_SPEC §3.5.7)"""
    mentions, lex = framed_mentions(text, bank, lang)
    is_dist = bank.is_entity_shift_distractor(fid)
    if is_dist:
        cues = bank.subject_cues(fid, lang)
    else:
        cues = [c for d in bank.entity_shift(fid) for c in bank.subject_cues(d.id, lang)]
    evidence: list[SentenceEvidence] = []
    for s_idx, tokens in enumerate(split_sentences(text)):
        ms = [
            m
            for m in mentions
            if m.sentence == s_idx and m.target.owner == fid and m.target.role == "value"
        ]
        if not ms:
            continue
        frames = tuple(sorted({m.frame for m in ms}))
        key = tuple(tokens)
        if any(m.frame in (ASSERTED, AFFIRMED) for m in ms):
            guarantee = mode == "answer" or (
                not is_dist
                and (not bank.entity_shift(fid) or phase == SNAPSHOT_A or key in snapshot_a_keys)
            )
            subj = attribute_subject(tokens, cues, lex, mode, guarantee)
            wanted = DISTRACTOR if is_dist else USER
            if subj.label in (AMBIGUOUS, UNKNOWN):
                ev = SentenceEvidence(
                    s_idx, key, UNRESOLVED, f"subject {subj.label}", frames, subj.label
                )
            elif subj.label != wanted:
                ev = SentenceEvidence(
                    s_idx, key, NOT_SUPPORTED, "other subject", frames, subj.label
                )
            else:
                rel = relation_status(tokens, fid, bank, lang)
                if rel == CONFLICTING:
                    ev = SentenceEvidence(
                        s_idx, key, NOT_SUPPORTED, "relation conflicting", frames, subj.label,
                        subj.explicit_user, rel,
                    )  # fmt: skip
                else:
                    ev = SentenceEvidence(
                        s_idx, key, SUPPORTED, f"relation {rel}", frames, subj.label,
                        subj.explicit_user, rel, provisional=rel != CONFIRMED,
                    )  # fmt: skip
        elif any(m.frame == AMBIGUOUS for m in ms):
            ev = SentenceEvidence(s_idx, key, UNRESOLVED, "ambiguous frame", frames)
        else:
            reason = "negated" if any(m.frame == NEGATED for m in ms) else "not asserted"
            ev = SentenceEvidence(s_idx, key, NOT_SUPPORTED, reason, frames)
        evidence.append(ev)

    sentences = tuple(evidence)
    if any(e.status == SUPPORTED and not e.provisional for e in evidence):
        return Support(SUPPORTED, False, sentences)
    if any(e.status == SUPPORTED for e in evidence):
        contradicted = any(e.status in (UNRESOLVED, NOT_SUPPORTED) for e in evidence)
        return Support(UNRESOLVED if contradicted else SUPPORTED, not contradicted, sentences)
    if any(e.status == UNRESOLVED for e in evidence):
        return Support(UNRESOLVED, False, sentences)
    if evidence:
        return Support(NOT_SUPPORTED, False, sentences)
    return Support(NONE, False, sentences)
