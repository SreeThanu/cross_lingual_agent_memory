"""Core data models for facts, conversation turns, memory records, and probe results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import yaml


@dataclass(frozen=True)
class Fact:
    """A language-neutral canonical fact with multi-lingual surface representations.

    Ground truth by construction: the entity, relation, and value are language-neutral
    canonical keys, allowing exact matching across language boundaries.
    """

    id: str
    domain: str
    entity: str
    relation: str
    value: str
    surface: dict[str, str]
    distractor_of: str | None = None
    probe_questions: dict[str, str] = field(default_factory=dict)
    update_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize Fact to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        """Create a Fact instance from a dictionary."""
        update_info = data.get("update") or data.get("update_data")
        return cls(
            id=data["id"],
            domain=data["domain"],
            entity=data["entity"],
            relation=data["relation"],
            value=data["value"],
            surface=dict(data.get("surface", {})),
            distractor_of=data.get("distractor_of"),
            probe_questions=dict(data.get("probe_questions", {})),
            update_data=update_info,
        )


@dataclass(frozen=True)
class Turn:
    """A single conversational dialogue turn in a scripted session."""

    session_id: int
    role: str  # "user" | "assistant"
    lang: str  # "hi" | "en" | "hi-en"
    text: str
    kind: str  # "plant" | "filler" | "probe" | "correction"
    fact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize Turn to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Turn:
        """Create a Turn instance from a dictionary."""
        return cls(
            session_id=int(data["session_id"]),
            role=str(data["role"]),
            lang=str(data["lang"]),
            text=str(data["text"]),
            kind=str(data["kind"]),
            fact_id=data.get("fact_id"),
        )


@dataclass
class Memory:
    """A single memory record as persisted and dumped by a memory framework."""

    raw_id: str
    text: str
    lang_detected: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize Memory to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Memory:
        """Create a Memory instance from a dictionary."""
        return cls(
            raw_id=str(data.get("raw_id", "")),
            text=str(data.get("text", "")),
            lang_detected=str(data.get("lang_detected", "")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ProbeResult:
    """Outcome of probing memory for a specific planted fact."""

    fact_id: str
    store_lang: str
    probe_lang: str
    retrieved: list[Memory]
    response: str
    hit_strict: bool = False
    hit_lenient: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize ProbeResult to a dictionary."""
        return {
            "fact_id": self.fact_id,
            "store_lang": self.store_lang,
            "probe_lang": self.probe_lang,
            "retrieved": [m.to_dict() for m in self.retrieved],
            "response": self.response,
            "hit_strict": self.hit_strict,
            "hit_lenient": self.hit_lenient,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProbeResult:
        """Create a ProbeResult instance from a dictionary."""
        retrieved_raw = data.get("retrieved", [])
        retrieved = [Memory.from_dict(m) if isinstance(m, dict) else m for m in retrieved_raw]
        return cls(
            fact_id=str(data["fact_id"]),
            store_lang=str(data["store_lang"]),
            probe_lang=str(data["probe_lang"]),
            retrieved=retrieved,
            response=str(data.get("response", "")),
            hit_strict=bool(data.get("hit_strict", False)),
            hit_lenient=bool(data.get("hit_lenient", False)),
            metadata=dict(data.get("metadata", {})),
        )


def load_facts(fact_bank_path: str | Path) -> list[Fact]:
    """Load and validate facts from a YAML fact bank file.

    Args:
        fact_bank_path: Path to the YAML fact bank.

    Returns:
        A list of validated Fact dataclass instances.
    """
    path = Path(fact_bank_path)
    if not path.exists():
        raise FileNotFoundError(f"Fact bank not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)

    if not isinstance(payload, dict) or "facts" not in payload:
        raise ValueError(f"Invalid fact bank YAML format in {path}: expected 'facts' key")

    raw_facts = payload["facts"]
    facts: list[Fact] = []
    for item in raw_facts:
        facts.append(Fact.from_dict(item))

    return facts
