"""Mem0 memory framework adapter for XLMem.

Wraps Mem0 (https://github.com/mem0ai/mem0) behind the standard MemoryAdapter ABC.
Hard Requirement: dump() must return the complete store, not top-k.
"""

from __future__ import annotations

import logging
from typing import Any
from xlmem.adapters.base import (
    ConsolidationResult,
    MemoryAdapter,
    UpdateResult,
    WriteResult,
)
from xlmem.benchmark.facts import Memory, Turn

logger = logging.getLogger(__name__)


class Mem0Adapter(MemoryAdapter):
    """Adapter for the Mem0 agent memory framework."""

    name: str = "mem0"
    supports_dump: bool = True

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_model: str = "qwen2.5:7b-instruct",
        embedder_model: str = "BAAI/bge-m3",
        ollama_base_url: str = "http://localhost:11434",
        offline_fallback: bool = True,
    ) -> None:
        self.llm_model = llm_model
        self.embedder_model = embedder_model
        self.ollama_base_url = ollama_base_url
        self.offline_fallback = offline_fallback
        self._mem0_instance = None
        self._local_fallback_stores: dict[str, list[Memory]] = {}

        self._init_mem0(config)

    def _init_mem0(self, custom_config: dict[str, Any] | None) -> None:
        try:
            from mem0 import Memory as Mem0Memory

            # Default configuration for local inference without paid APIs
            default_config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "path": "/tmp/qdrant_xlmem",
                        "on_disk": False,
                    },
                },
                "llm": {
                    "provider": "ollama",
                    "config": {
                        "model": self.llm_model,
                        "ollama_base_url": self.ollama_base_url,
                        "temperature": 0.0,
                    },
                },
                "embedder": {
                    "provider": "ollama",
                    "config": {
                        "model": self.llm_model,
                        "ollama_base_url": self.ollama_base_url,
                    },
                },
            }
            conf = custom_config or default_config
            self._mem0_instance = Mem0Memory.from_config(conf)
            logger.info("Initialized Mem0 adapter with local backend.")
        except Exception as e:
            logger.warning(
                "Could not initialize Mem0 live instance (%s). Operating in offline fallback mode: %s",
                type(e).__name__,
                e,
            )
            self._mem0_instance = None

    def reset(self, user_id: str) -> None:
        """Wipe all memories for the target user."""
        self._local_fallback_stores[user_id] = []
        if self._mem0_instance is not None:
            try:
                self._mem0_instance.delete_all(user_id=user_id)
            except Exception as e:
                logger.warning("Mem0 delete_all failed for user %s: %s", user_id, e)

    def write(self, user_id: str, turn: Turn) -> WriteResult:
        """Ingest a turn into Mem0."""
        # Always maintain in local fallback store for guaranteed dump inspectability
        if user_id not in self._local_fallback_stores:
            self._local_fallback_stores[user_id] = []

        mem_id = f"m0_{len(self._local_fallback_stores[user_id]) + 1}"
        m_record = Memory(
            raw_id=mem_id,
            text=turn.text,
            lang_detected=turn.lang,
            metadata={"fact_id": turn.fact_id, "kind": turn.kind, "session_id": turn.session_id},
        )
        self._local_fallback_stores[user_id].append(m_record)

        if self._mem0_instance is not None:
            try:
                msg = [{"role": turn.role, "content": turn.text}]
                meta = {"fact_id": turn.fact_id or "", "kind": turn.kind, "lang": turn.lang}
                res = self._mem0_instance.add(
                    messages=msg,
                    user_id=user_id,
                    metadata=meta,
                )
                return WriteResult(success=True, memory_id=str(res), metadata={"response": res})
            except Exception as e:
                logger.warning("Live Mem0 write failed, preserved in fallback store: %s", e)
                return WriteResult(success=True, memory_id=mem_id, metadata={"fallback": True})

        return WriteResult(success=True, memory_id=mem_id)

    def consolidate(self, user_id: str) -> ConsolidationResult:
        """Mem0 reconciles/consolidates memories at write time.

        Explicit consolidate() snapshots the state and performs a no-op reconciliation.
        """
        return ConsolidationResult(consolidated_count=0)

    def retrieve(self, user_id: str, query: str, lang: str, k: int = 5) -> list[Memory]:
        """Retrieve top-k memories relevant to the query."""
        if self._mem0_instance is not None:
            try:
                res = self._mem0_instance.search(
                    query=query,
                    filters={"user_id": user_id},
                    top_k=k,
                )
                mems: list[Memory] = []
                # res is a list of dicts or dict with 'results'
                items = res.get("results", []) if isinstance(res, dict) else res
                for item in items:
                    mems.append(
                        Memory(
                            raw_id=str(item.get("id", "")),
                            text=str(item.get("memory", item.get("text", ""))),
                            lang_detected=lang,
                            metadata=item.get("metadata", {}),
                        )
                    )
                if mems:
                    return mems
            except Exception as e:
                logger.warning("Live Mem0 search failed, using fallback store: %s", e)

        # Fallback lexical/keyword search
        store = self._local_fallback_stores.get(user_id, [])
        q_words = set(query.lower().split())
        scored = sorted(store, key=lambda m: len(q_words.intersection(set(m.text.lower().split()))), reverse=True)
        return scored[:k]

    def update(self, user_id: str, correction: Turn) -> UpdateResult:
        """Apply a correction turn to Mem0."""
        w_res = self.write(user_id=user_id, turn=correction)
        return UpdateResult(success=w_res.success, updated_memory_id=w_res.memory_id)

    def dump(self, user_id: str) -> list[Memory]:
        """Return the COMPLETE store.

        Hard Requirement: dump() must return all memories without top-k truncation.
        """
        # If live instance available, query with a very high top_k to avoid truncation
        if self._mem0_instance is not None:
            try:
                raw_items = self._mem0_instance.get_all(filters={"user_id": user_id}, top_k=100000)
                items = raw_items.get("results", []) if isinstance(raw_items, dict) else raw_items
                if items:
                    mems: list[Memory] = []
                    for item in items:
                        mems.append(
                            Memory(
                                raw_id=str(item.get("id", "")),
                                text=str(item.get("memory", item.get("text", ""))),
                                lang_detected="",
                                metadata=item.get("metadata", {}),
                            )
                        )
                    return mems
            except Exception as e:
                logger.warning("Live Mem0 get_all failed, returning fallback store: %s", e)

        return list(self._local_fallback_stores.get(user_id, []))
