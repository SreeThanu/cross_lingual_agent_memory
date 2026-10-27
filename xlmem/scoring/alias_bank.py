"""Alias bank v2 for metrics v3 (METRICS_SPEC §3.5.4; decisions D1.3, O7).

Tier A: token spans extracted mechanically from a fact's authored text (index references,
checked against `expect`). Tier B: variants written by >= 2 bilingual annotators before
seeing model outputs, then frozen. Tier C: post-hoc entries, for sensitivity analysis only.
The v2.1 sidecar (xlmem/scoring/aliases.py) is separate and unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from xlmem.benchmark.facts import Fact
from xlmem.scoring.matching import TOKENIZER_VERSION, find_spans, split_sentences, tokenize

ALIAS_BANK_VERSION = 2
ROLES = ("value", "updated_value", "relation_cue", "subject_cue")
FIELDS = ("surface", "update.surface")
MAX_SPAN_TOKENS = 4


@dataclass(frozen=True)
class AliasEntry:
    role: str
    lang: str
    tier: str
    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class AliasBankV2:
    path: str | None
    sha256: str | None
    fact_bank_sha256: str | None
    entries: dict[str, tuple[AliasEntry, ...]] = field(default_factory=dict)

    def get(
        self, fact_id: str, role: str, langs: Sequence[str], tiers: Sequence[str] = ("A", "B")
    ) -> list[AliasEntry]:
        return [
            e
            for e in self.entries.get(fact_id, ())
            if e.role == role and e.lang in langs and e.tier in tiers
        ]


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def default_alias_bank_path(fact_bank_path: str | Path) -> Path:
    p = Path(fact_bank_path)
    return p.parent / "aliases" / f"{p.stem}.aliases.v2.yaml"


def authored_text(fact: Fact, field_name: str, lang: str) -> str | None:
    """The authored string a tier-A span points into."""
    if field_name == "surface":
        return fact.surface.get(lang)
    if field_name == "update.surface":
        surf = (fact.update_data or {}).get("surface") or {}
        value = surf.get(lang)
        return str(value) if value is not None else None
    return None


def locate_span(text: str, expect: str) -> tuple[int, int]:
    """Authoring helper: token indices of `expect` in `text` (must occur exactly once)."""
    spans = find_spans(tokenize(text), [tuple(tokenize(expect))])
    if len(spans) != 1:
        raise ValueError(f"{expect!r} occurs {len(spans)} times in {text!r}; need exactly 1")
    return spans[0]


def _extract_span(fact: Fact, ref: Mapping[str, Any], where: str) -> AliasEntry:
    field_name, lang, role = ref.get("field"), ref.get("lang"), ref.get("role")
    start, end, expect = ref.get("start"), ref.get("end"), ref.get("expect")
    if field_name not in FIELDS or role not in ROLES or not isinstance(lang, str):
        raise ValueError(f"{where}: bad field/role/lang {field_name!r}/{role!r}/{lang!r}")
    if not (isinstance(start, int) and isinstance(end, int) and isinstance(expect, str)):
        raise ValueError(f"{where}: start/end must be ints and expect a string")
    text = authored_text(fact, field_name, lang)
    if text is None:
        raise ValueError(f"{where}: fact has no {field_name}[{lang}]")
    tokens = tokenize(text)
    if not (0 <= start < end <= len(tokens)) or end - start > MAX_SPAN_TOKENS:
        raise ValueError(f"{where}: span [{start}, {end}) invalid for {len(tokens)} tokens")
    offset = 0
    for sent in split_sentences(text):
        if (
            offset < end
            and start < offset + len(sent)
            and not (offset <= start and end <= offset + len(sent))
        ):
            raise ValueError(f"{where}: span [{start}, {end}) crosses a sentence boundary")
        offset += len(sent)
    extracted = tuple(tokens[start:end])
    if extracted != tuple(tokenize(expect)):
        raise ValueError(f"{where}: span extracts {' '.join(extracted)!r}, expect {expect!r}")
    if role == "updated_value" and field_name != "update.surface":
        raise ValueError(f"{where}: updated_value spans must come from update.surface")
    if role == "value" and field_name != "surface":
        raise ValueError(f"{where}: value spans must come from surface")
    return AliasEntry(role=role, lang=lang, tier="A", text=" ".join(extracted), tokens=extracted)


def _listed_entry(raw: Mapping[str, Any], tier: str, where: str) -> AliasEntry:
    role, lang, text = raw.get("role"), raw.get("lang"), raw.get("text")
    if role not in ROLES or not isinstance(lang, str) or not isinstance(text, str):
        raise ValueError(f"{where}: bad role/lang/text")
    toks = tuple(tokenize(text))
    if not toks or len(toks) > MAX_SPAN_TOKENS:
        raise ValueError(f"{where}: {text!r} must be 1..{MAX_SPAN_TOKENS} tokens")
    if tier == "B":
        annotators = raw.get("annotators")
        if not isinstance(annotators, list) or len(set(map(str, annotators))) < 2:
            raise ValueError(f"{where}: tier B needs >= 2 distinct annotators")
        if not raw.get("date") or raw.get("frozen") is not True:
            raise ValueError(f"{where}: tier B needs a date and frozen: true")
    else:
        if not raw.get("added_by") or not raw.get("date") or not raw.get("reason"):
            raise ValueError(f"{where}: tier C needs added_by, date and reason")
    return AliasEntry(role=role, lang=lang, tier=tier, text=" ".join(toks), tokens=toks)


def alias_bank_from_mapping(
    payload: Mapping[str, Any],
    facts: Sequence[Fact],
    fact_bank_sha256: str | None = None,
    path: str | None = None,
    sha256: str | None = None,
) -> AliasBankV2:
    """Validate a parsed alias bank. `fact_bank_sha256` (if given) must match the payload's."""
    if payload.get("alias_bank_version") != ALIAS_BANK_VERSION:
        raise ValueError(f"alias_bank_version must be {ALIAS_BANK_VERSION}")
    if payload.get("tokenizer_version") != TOKENIZER_VERSION:
        raise ValueError(
            f"tokenizer_version {payload.get('tokenizer_version')!r} != {TOKENIZER_VERSION!r}; "
            "regenerate the tier-A spans"
        )
    declared = payload.get("fact_bank_sha256")
    if fact_bank_sha256 is not None and declared != fact_bank_sha256:
        raise ValueError(f"written for fact bank sha256 {declared}, got {fact_bank_sha256}")
    by_id = {f.id: f for f in facts}
    entries: dict[str, tuple[AliasEntry, ...]] = {}
    for fid, raw in (payload.get("facts") or {}).items():
        fact = by_id.get(str(fid))
        if fact is None:
            raise ValueError(f"aliases for unknown fact {fid}")
        out: list[AliasEntry] = []
        for i, ref in enumerate(raw.get("tier_a") or []):
            out.append(_extract_span(fact, ref, f"{fid}.tier_a[{i}]"))
        for tier, key in (("B", "tier_b"), ("C", "tier_c")):
            for i, item in enumerate(raw.get(key) or []):
                out.append(_listed_entry(item, tier, f"{fid}.{key}[{i}]"))
        entries[str(fid)] = tuple(out)
    return AliasBankV2(path=path, sha256=sha256, fact_bank_sha256=declared, entries=entries)


def load_alias_bank_v2(
    alias_path: str | Path, facts: Sequence[Fact], fact_bank_path: str | Path
) -> AliasBankV2:
    payload = yaml.safe_load(Path(alias_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{alias_path}: expected a mapping")
    return alias_bank_from_mapping(
        payload,
        facts,
        fact_bank_sha256=sha256_file(fact_bank_path),
        path=str(alias_path),
        sha256=sha256_file(alias_path),
    )


def validate_contract_bank(
    facts: Sequence[Fact],
    bank: AliasBankV2,
    filler_turns: Sequence[Mapping[str, str]] = (),
) -> list[str]:
    """Bank checks the matching contract relies on (METRICS_SPEC §3.5.4); [] means valid."""
    errors: list[str] = []
    by_id = {f.id: f for f in facts}
    base = [f for f in facts if f.distractor_of is None]

    def has(fid: str, role: str, lang: str) -> bool:
        return any(e.tier == "A" for e in bank.get(fid, role, [lang], tiers=("A",)))

    for f in base:
        for lang in f.surface:
            if not has(f.id, "value", lang):
                errors.append(f"{f.id}: no tier-A value span for {lang}")
            if not has(f.id, "relation_cue", lang):
                errors.append(f"{f.id}: no tier-A relation_cue span for {lang}")
    for d in facts:
        base_f = by_id.get(d.distractor_of or "")
        if base_f is not None and d.entity != base_f.entity:
            for lang in d.surface:
                if not has(d.id, "subject_cue", lang):
                    errors.append(f"{d.id}: entity-shift distractor has no subject_cue for {lang}")

    def value_seqs(f: Fact) -> set[tuple[str, ...]]:
        seqs = {tuple(tokenize(f.value))}
        seqs |= {
            e.tokens for e in bank.entries.get(f.id, ()) if e.role == "value" and e.tier != "C"
        }
        return {s for s in seqs if s}

    owner: dict[tuple[str, ...], str] = {}
    for f in base:
        for seq in value_seqs(f):
            if seq in owner and owner[seq] != f.id:
                errors.append(f"{f.id} and {owner[seq]} share value target {' '.join(seq)!r}")
            owner.setdefault(seq, f.id)

    cue_relation: dict[tuple[str, ...], str] = {}
    for f in facts:
        for e in bank.entries.get(f.id, ()):
            if e.role == "relation_cue":
                prev = cue_relation.setdefault(e.tokens, f.relation)
                if prev != f.relation:
                    errors.append(f"relation cue {e.text!r} used for both {prev} and {f.relation}")

    all_values = {seq: f.id for f in facts for seq in value_seqs(f)}
    for i, turn in enumerate(filler_turns):
        for lang, text in turn.items():
            toks = tuple(tokenize(text))
            for start, end in find_spans(toks, all_values.keys()):
                seq = toks[start:end]
                errors.append(f"filler turn {i} [{lang}] contains value of {all_values[seq]}")
    return errors
