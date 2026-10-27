"""Authored value aliases for Staleness Rate v2 (METRICS_SPEC.md §3.4, decision D6)."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import yaml

from xlmem.benchmark.facts import Fact


@dataclass(frozen=True)
class FactAliases:
    """Aliases for one fact's old and updated value, keyed by language code."""

    value: dict[str, tuple[str, ...]] = field(default_factory=dict)
    updated_value: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ValueAliases:
    """A validated alias bank bound to one fact bank by sha256."""

    path: str
    sha256: str
    fact_bank_sha256: str
    facts: dict[str, FactAliases] = field(default_factory=dict)

    def for_fact(self, fact_id: str) -> FactAliases:
        """Return the fact's aliases, or an empty entry if it has none."""
        return self.facts.get(fact_id, FactAliases())


def sha256_file(path: str | Path) -> str:
    """Hex sha256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def default_alias_path(fact_bank_path: str | Path) -> Path:
    """Sidecar location for a fact bank: data/aliases/<stem>.aliases.yaml next to data/."""
    p = Path(fact_bank_path)
    return p.parent / "aliases" / f"{p.stem}.aliases.yaml"


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _lang_map(raw: Any, where: str) -> dict[str, tuple[str, ...]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected a mapping of language -> list of aliases")
    out: dict[str, tuple[str, ...]] = {}
    for lang, items in raw.items():
        if not isinstance(items, list) or not all(isinstance(a, str) and a.strip() for a in items):
            raise ValueError(f"{where}.{lang}: expected a non-empty list of non-empty strings")
        out[str(lang)] = tuple(_nfc(a) for a in items)
    return out


def load_value_aliases(
    alias_path: str | Path, facts: Sequence[Fact], fact_bank_path: str | Path
) -> ValueAliases:
    """Load and validate an alias sidecar against the fact bank it was authored for.

    Refuses a file written for a different fact bank, aliases for unknown facts, and any alias
    that is not a verbatim span of the fact's own authored surface (the D6 authoring rule).
    """
    alias_path = Path(alias_path)
    payload = yaml.safe_load(alias_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), dict):
        raise ValueError(f"{alias_path}: expected a mapping with a 'facts' key")

    bank_sha = sha256_file(fact_bank_path)
    declared = payload.get("fact_bank_sha256")
    if declared != bank_sha:
        raise ValueError(
            f"{alias_path}: written for fact bank sha256 {declared}, "
            f"but {fact_bank_path} has sha256 {bank_sha}"
        )

    facts_by_id = {f.id: f for f in facts}
    entries: dict[str, FactAliases] = {}
    for fact_id, raw in payload["facts"].items():
        fact = facts_by_id.get(str(fact_id))
        if fact is None:
            raise ValueError(f"{alias_path}: aliases for unknown fact {fact_id}")
        if not isinstance(raw, dict):
            raise ValueError(f"{alias_path}: {fact_id}: expected a mapping")
        value = _lang_map(raw.get("value"), f"{fact_id}.value")
        updated = _lang_map(raw.get("updated_value"), f"{fact_id}.updated_value")

        for lang, aliases in value.items():
            surface = _nfc(fact.surface.get(lang, ""))
            for a in aliases:
                if a not in surface:
                    raise ValueError(f"{fact_id}.value.{lang}: {a!r} is not in surface[{lang}]")
        if updated and fact.update_data is None:
            raise ValueError(f"{fact_id}: updated_value aliases but the fact has no update block")
        update_surface = (fact.update_data or {}).get("surface", {}) or {}
        for lang, aliases in updated.items():
            surface = _nfc(str(update_surface.get(lang, "")))
            for a in aliases:
                if a not in surface:
                    raise ValueError(
                        f"{fact_id}.updated_value.{lang}: {a!r} is not in update.surface[{lang}]"
                    )
        entries[str(fact_id)] = FactAliases(value=value, updated_value=updated)

    return ValueAliases(
        path=str(alias_path),
        sha256=sha256_file(alias_path),
        fact_bank_sha256=bank_sha,
        facts=entries,
    )
