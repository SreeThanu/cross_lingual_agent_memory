"""In-memory mock adapter for unit tests, contract tests, and offline test harnesses."""

from __future__ import annotations

from typing import Any
from xlmem.adapters.base import (
    ConsolidationResult,
    MemoryAdapter,
    UpdateResult,
    WriteResult,
)
from xlmem.benchmark.facts import Memory, Turn


class MockAdapter(MemoryAdapter):
    """Deterministic in-memory adapter for testing without GPU or network dependencies."""

    name: str = "mock"
    supports_dump: bool = True

    def __init__(self) -> None:
        # Stores user_id -> list of Memory objects
        self.stores: dict[str, list[Memory]] = {}
        self._counter: int = 0

    def reset(self, user_id: str) -> None:
        """Clear memory for the specified user."""
        self.stores[user_id] = []

    def write(self, user_id: str, turn: Turn) -> WriteResult:
        """Store the text of the turn as a memory record."""
        if user_id not in self.stores:
            self.stores[user_id] = []

        self._counter += 1
        mem_id = f"mock_mem_{self._counter}"
        mem = Memory(
            raw_id=mem_id,
            text=turn.text,
            lang_detected=turn.lang,
            metadata={"fact_id": turn.fact_id, "kind": turn.kind, "session_id": turn.session_id},
        )
        self.stores[user_id].append(mem)
        return WriteResult(success=True, memory_id=mem_id, metadata={"stored_text": turn.text})

    def consolidate(self, user_id: str) -> ConsolidationResult:
        """Consolidate memories. In this mock, deduplicates exact string matches."""
        if user_id not in self.stores:
            return ConsolidationResult(consolidated_count=0)

        seen_texts: set[str] = set()
        deduped: list[Memory] = []
        before_count = len(self.stores[user_id])
        for mem in self.stores[user_id]:
            if mem.text not in seen_texts:
                seen_texts.add(mem.text)
                deduped.append(mem)

        self.stores[user_id] = deduped
        consolidated = before_count - len(deduped)
        return ConsolidationResult(consolidated_count=consolidated)

    def retrieve(self, user_id: str, query: str, lang: str, k: int = 5) -> list[Memory]:
        """Simple retrieval: substring / keyword matching or top-k."""
        store = self.stores.get(user_id, [])
        query_words = set(query.lower().split())

        def score(m: Memory) -> int:
            m_words = set(m.text.lower().split())
            return len(query_words.intersection(m_words))

        # Sort by overlap score descending
        sorted_mems = sorted(store, key=score, reverse=True)
        return sorted_mems[:k]

    def update(self, user_id: str, correction: Turn) -> UpdateResult:
        """Update memory: append correction and optionally remove superseded fact."""
        if user_id not in self.stores:
            self.stores[user_id] = []

        self._counter += 1
        new_id = f"mock_mem_{self._counter}"
        new_mem = Memory(
            raw_id=new_id,
            text=correction.text,
            lang_detected=correction.lang,
            metadata={"fact_id": correction.fact_id, "kind": "correction"},
        )
        self.stores[user_id].append(new_mem)
        return UpdateResult(success=True, updated_memory_id=new_id)

    def dump(self, user_id: str) -> list[Memory]:
        """Return full store for the user."""
        return list(self.stores.get(user_id, []))
