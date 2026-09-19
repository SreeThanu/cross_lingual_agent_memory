"""Letta (MemGPT) memory framework adapter for XLMem.

Wraps Letta 0.13.0 (https://github.com/letta-ai/letta) behind the standard MemoryAdapter ABC.
Hard Requirement: dump() must return the complete store, not top-k.

Letta requires a running REST server (`letta server`), backed by PostgreSQL, reachable at
`base_url`. Setup notes (see OPEN_ISSUES.md for the full spike write-up):
  - The server enables an LLM/embedding provider only if the corresponding env var is set;
    setting OLLAMA_BASE_URL registers a local-only "ollama" provider. A "letta" provider
    (model "letta-free", pointing at https://inference.letta.com and
    https://embeddings.letta.com) is ALWAYS registered regardless of config, so this adapter
    always pins agents to explicit `ollama/<model>` handles to avoid silently using it.

Letta has two memory substrates per agent:
  - Core memory: small, fixed set of blocks (e.g. "human", "persona"), overwritten in place.
  - Archival memory: an append-only, paginated passage store, searchable by text.
Which substrate a given fact lands in is decided by the agent's own LLM tool-calling during
`write()`, the same class of framework-internal nondeterminism already documented for Mem0's
add/update/no-op decision (see AGENTS.md 14.2 / OPEN_ISSUES.md 2.2). Because a fact can live in
core memory ONLY, both dump() and retrieve() must inspect core memory AND archival memory --
using archival alone would misreport core-memory-only facts as WRITE failures.
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


class LettaAdapter(MemoryAdapter):
    """Adapter for the Letta (MemGPT) agent memory framework."""

    name: str = "letta"
    supports_dump: bool = True

    def __init__(
        self,
        base_url: str = "http://localhost:8283",
        llm_model: str = "qwen2.5:7b-instruct",
        embedder_model: str = "bge-m3:latest",
        token: str | None = None,
        offline_fallback: bool = False,
    ) -> None:
        self.base_url = base_url
        self.llm_handle = f"ollama/{llm_model}"
        self.embedding_handle = f"ollama/{embedder_model}"
        self.offline_fallback = offline_fallback
        self._client: Any = None
        self._agent_ids: dict[str, str] = {}
        self._local_fallback_stores: dict[str, list[Memory]] = {}

        self._init_client(token=token)

    def _init_client(self, token: str | None) -> None:
        try:
            from letta_client import Letta as LettaClient

            self._client = LettaClient(base_url=self.base_url, token=token)
            # Cheap reachability check; raises if the server is unreachable.
            self._client.health.check()
            logger.info("Initialized Letta adapter against server at %s.", self.base_url)
        except Exception as e:
            self._client = None
            if self.offline_fallback:
                logger.warning(
                    "Could not reach Letta server at %s (%s). Operating in offline fallback mode: %s",
                    self.base_url,
                    type(e).__name__,
                    e,
                )
            else:
                logger.error(
                    "Could not reach Letta server at %s (%s): %s", self.base_url, type(e).__name__, e
                )

    def _create_agent(self, user_id: str) -> str:
        """Create a fresh agent explicitly pinned to local Ollama models.

        Core memory blocks start EMPTY, not with scaffolding text (e.g. a persona
        description). Any non-empty block value is treated as a stored memory record
        by dump() -- starting non-empty would make dump() report phantom records
        immediately after reset(), before anything was ever planted, and would corrupt
        Write Fidelity (AGENTS.md Rule 11 / test_reset_isolation contract: dump() must
        be empty right after reset(), before any write()).
        """
        agent = self._client.agents.create(
            name=f"xlmem_{user_id}",
            memory_blocks=[
                {"label": "human", "value": ""},
                {"label": "persona", "value": ""},
            ],
            model=self.llm_handle,
            embedding=self.embedding_handle,
        )
        return str(agent.id)

    def reset(self, user_id: str) -> None:
        """Wipe all memory for the target user by deleting and recreating its agent."""
        if self.offline_fallback:
            self._local_fallback_stores[user_id] = []

        if self._client is not None:
            try:
                old_agent_id = self._agent_ids.get(user_id)
                if old_agent_id:
                    self._client.agents.delete(agent_id=old_agent_id)
                self._agent_ids[user_id] = self._create_agent(user_id)
            except Exception as e:
                if self.offline_fallback:
                    logger.warning("Letta reset failed for user %s: %s", user_id, e)
                else:
                    raise RuntimeError(f"Letta reset failed for user {user_id}") from e
        elif not self.offline_fallback:
            raise RuntimeError("Letta server is unavailable")

    def write(self, user_id: str, turn: Turn) -> WriteResult:
        """Ingest a turn by sending it as a message to the user's agent."""
        if self.offline_fallback:
            if user_id not in self._local_fallback_stores:
                self._local_fallback_stores[user_id] = []
            mem_id = f"letta_fallback_{len(self._local_fallback_stores[user_id]) + 1}"
            self._local_fallback_stores[user_id].append(
                Memory(
                    raw_id=mem_id,
                    text=turn.text,
                    lang_detected=turn.lang,
                    metadata={"fact_id": turn.fact_id, "kind": turn.kind, "session_id": turn.session_id},
                )
            )

        if self._client is not None:
            agent_id = self._agent_ids.get(user_id)
            if agent_id is None:
                agent_id = self._create_agent(user_id)
                self._agent_ids[user_id] = agent_id
            try:
                resp = self._client.agents.messages.create(
                    agent_id=agent_id,
                    messages=[{"role": turn.role, "content": turn.text}],
                )
                return WriteResult(
                    success=True,
                    memory_id=agent_id,
                    metadata={"n_response_messages": len(resp.messages)},
                )
            except Exception as e:
                if self.offline_fallback:
                    logger.warning("Live Letta write failed, preserved in fallback store: %s", e)
                    return WriteResult(success=True, memory_id=agent_id, metadata={"fallback": True})
                return WriteResult(success=False, memory_id=None, metadata={"error": str(e)})

        if self.offline_fallback:
            return WriteResult(success=True, memory_id=None)

        return WriteResult(success=False, memory_id=None, metadata={"error": "Letta server is unavailable"})

    def consolidate(self, user_id: str) -> ConsolidationResult:
        """Letta manages core/archival promotion via its own agent tool-calling loop.

        There is no separate batch consolidation call to trigger; explicit consolidate()
        is a no-op, matching the existing Mem0Adapter precedent for eager frameworks
        (AGENTS.md 14.2 / OPEN_ISSUES.md 2.2).
        """
        return ConsolidationResult(consolidated_count=0)

    def _core_memory_as_records(self, agent_id: str) -> list[Memory]:
        """Core memory blocks with actual content, excluding untouched-empty scaffolding."""
        blocks = self._client.agents.core_memory.retrieve(agent_id=agent_id)
        return [
            Memory(
                raw_id=f"{agent_id}:core:{b.label}",
                text=str(b.value),
                lang_detected="",
                metadata={"substrate": "core", "label": b.label},
            )
            for b in blocks.blocks
            if str(b.value).strip()
        ]

    def _all_archival_records(self, agent_id: str, page_size: int = 100) -> list[Memory]:
        """Cursor-paginate archival passages until exhausted. Never relies on an
        undocumented default limit (see OPEN_ISSUES.md Letta spike: verified empirically
        that an unbounded list() call does NOT silently truncate in 0.13.0, but pagination
        is used anyway as the documented, version-independent contract)."""
        records: list[Memory] = []
        after: str | None = None
        while True:
            page = self._client.agents.passages.list(agent_id=agent_id, limit=page_size, after=after)
            if not page:
                break
            for p in page:
                records.append(
                    Memory(
                        raw_id=str(p.id),
                        text=str(p.text),
                        lang_detected="",
                        metadata={"substrate": "archival"},
                    )
                )
            after = str(page[-1].id)
        return records

    def retrieve(self, user_id: str, query: str, lang: str, k: int = 5) -> list[Memory]:
        """Return top-k memories: archival search results plus current core memory blocks.

        Core memory is always "in context" for the agent rather than retrieved by
        similarity, but a fact can live ONLY in core memory (observed empirically -- see
        OPEN_ISSUES.md). Omitting it here would understate recall for facts Letta chose to
        store in core memory instead of archival, a framework-specific bias that must be
        absorbed inside the adapter, not left for the runner/scorer to misattribute.
        """
        agent_id = self._agent_ids.get(user_id)
        if self._client is not None and agent_id is not None:
            try:
                archival_hits = self._client.agents.passages.list(agent_id=agent_id, search=query, limit=k)
                mems = [
                    Memory(
                        raw_id=str(p.id),
                        text=str(p.text),
                        lang_detected=lang,
                        metadata={"substrate": "archival"},
                    )
                    for p in archival_hits
                ]
                core_records = self._core_memory_as_records(agent_id)
                q_words = set(query.lower().split())
                core_records.sort(
                    key=lambda m: len(q_words.intersection(set(m.text.lower().split()))),
                    reverse=True,
                )
                combined = mems + core_records
                return combined[:k]
            except Exception as e:
                if not self.offline_fallback:
                    raise RuntimeError("Letta retrieve failed") from e
                logger.warning("Live Letta retrieve failed, using fallback store: %s", e)

        if not self.offline_fallback:
            raise RuntimeError("Letta server is unavailable")

        store = self._local_fallback_stores.get(user_id, [])
        q_words = set(query.lower().split())
        scored = sorted(
            store, key=lambda m: len(q_words.intersection(set(m.text.lower().split()))), reverse=True
        )
        return scored[:k]

    def update(self, user_id: str, correction: Turn) -> UpdateResult:
        """Apply a correction turn by sending it as a message, same as write()."""
        w_res = self.write(user_id=user_id, turn=correction)
        return UpdateResult(success=w_res.success, updated_memory_id=w_res.memory_id)

    def dump(self, user_id: str) -> list[Memory]:
        """Return the COMPLETE store: core memory blocks + all archival passages.

        Hard Requirement: dump() must return all memories without top-k truncation.
        """
        agent_id = self._agent_ids.get(user_id)
        if self._client is not None and agent_id is not None:
            try:
                return self._core_memory_as_records(agent_id) + self._all_archival_records(agent_id)
            except Exception as e:
                if not self.offline_fallback:
                    raise RuntimeError("Letta dump failed") from e
                logger.warning("Live Letta dump failed, returning fallback store: %s", e)

        if not self.offline_fallback:
            raise RuntimeError("Letta server is unavailable")

        return list(self._local_fallback_stores.get(user_id, []))
