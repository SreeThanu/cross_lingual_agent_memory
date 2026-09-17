"""MemoryAdapter abstract base class and operation result dataclasses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from xlmem.benchmark.facts import Memory, Turn


@dataclass
class WriteResult:
    """Result returned by a memory framework after ingesting a turn."""

    success: bool
    memory_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsolidationResult:
    """Result returned after explicit or implicit memory consolidation."""

    consolidated_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpdateResult:
    """Result returned after ingesting a memory correction."""

    success: bool
    updated_memory_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryAdapter(ABC):
    """Uniform interface over heterogeneous memory frameworks.

    Every framework (Mem0, Letta, A-MEM) must implement this interface.
    Hard requirement: supports_dump must be True and dump() must return
    the full store (not top-k).
    """

    name: str
    supports_dump: bool

    @abstractmethod
    def reset(self, user_id: str) -> None:
        """Wipe all memory for a user. Called between seeds."""
        pass

    @abstractmethod
    def write(self, user_id: str, turn: Turn) -> WriteResult:
        """Ingest a conversational turn; framework decides what to store."""
        pass

    @abstractmethod
    def consolidate(self, user_id: str) -> ConsolidationResult:
        """Trigger merge/dedup. No-op if the framework consolidates implicitly."""
        pass

    @abstractmethod
    def retrieve(self, user_id: str, query: str, lang: str, k: int = 5) -> list[Memory]:
        """Return top-k memories for a query."""
        pass

    @abstractmethod
    def update(self, user_id: str, correction: Turn) -> UpdateResult:
        """Apply a user correction."""
        pass

    @abstractmethod
    def dump(self, user_id: str) -> list[Memory]:
        """Return the FULL raw store. Required for duplication analysis."""
        pass
