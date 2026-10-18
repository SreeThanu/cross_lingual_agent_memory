"""A-MEM memory framework adapter for XLMem.

Wraps A-MEM (agiresearch/A-mem @ ceffb86, Xu et al., 2025) behind the standard
MemoryAdapter ABC. Hard Requirement: dump() must return the complete store, not top-k.

A-MEM quirks absorbed here (OPEN_ISSUES.md §1.3), so none reach the runner:
- AgenticMemorySystem.__init__ resets the process-wide Chroma client and every
  instance uses the collection "memories", so a second user would wipe the first.
  Each user gets its own collection on one shared client, and A-MEM's reset is
  made a no-op for retrievers this adapter creates.
- The default LLM backend is OpenAI (a paid API, AGENTS.md Hard Rule 1); this
  adapter always uses Ollama and checks that it did.
- The default embedder is English-only (all-MiniLM-L6-v2); the default here is
  BGE-M3, matching Mem0Adapter.
- OllamaController.get_completion ignores its temperature argument; the call is
  shimmed to pass the harness temperature and the Ollama base URL.
- search_agentic() swallows exceptions and returns []. retrieve() and dump() raise
  instead of letting a broken index pass as a retrieval miss.

Unchanged from A-MEM's own behaviour: every turn is stored verbatim as a new note
(no deduplication), memory evolution runs on write, and retrieval is
search_agentic(), the README's search.
"""

from __future__ import annotations

import logging
import re
import types
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from xlmem.adapters.base import (
    ConsolidationResult,
    MemoryAdapter,
    UpdateResult,
    WriteResult,
    capture_framework_errors,
)
from xlmem.benchmark.facts import Memory, Turn

logger = logging.getLogger(__name__)

# A-MEM's own system message for its Ollama JSON calls (llm_controller.py @ ceffb86).
_AMEM_SYSTEM_MESSAGE = "You must respond with a JSON object."


class _NoResetClient:
    """Chroma client proxy whose reset() does nothing: A-MEM resets on construction."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def reset(self) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class AMEMAdapter(MemoryAdapter):
    """Adapter for the A-MEM agentic memory framework."""

    name: str = "amem"
    supports_dump: bool = True

    def __init__(
        self,
        llm_model: str = "qwen2.5:7b-instruct",
        embedder_model: str = "BAAI/bge-m3",
        ollama_base_url: str = "http://localhost:11434",
        temperature: float = 0.0,
        evo_threshold: int = 100,
    ) -> None:
        self.llm_model = llm_model
        self.embedder_model = embedder_model
        self.ollama_base_url = ollama_base_url
        self.temperature = temperature
        self.evo_threshold = evo_threshold
        # Heavy objects (Chroma client, embedding model) are created on first use,
        # so constructing the adapter is cheap and needs no network or GPU.
        self._client: Any = None
        self._embedding_function: Any = None
        self._systems: dict[str, Any] = {}
        # Harness bookkeeping per note (fact_id, kind, lang), like the metadata
        # Mem0Adapter stores in Mem0. A-MEM notes cannot carry arbitrary metadata.
        self._note_meta: dict[str, dict[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------ internals

    def _collection_name(self, user_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", user_id)
        return f"xlmem_amem_{safe}"[:63]

    def _shared_backend(self) -> tuple[Any, Any]:
        if self._client is None:
            # Import order matters in the xlmem env: `import chromadb` loads
            # onnxruntime, whose native module resolves the old system libstdc++.
            # Python's sqlite3 (needed by chromadb) links conda's ICU, which needs
            # the newer conda libstdc++, so a bare `import chromadb` fails with
            # "CXXABI_1.3.15 not found". Loading sqlite3 first pins the right one.
            import sqlite3  # noqa: F401

            import chromadb
            from chromadb.config import Settings
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )

            self._client = chromadb.Client(
                Settings(allow_reset=True, anonymized_telemetry=False)
            )
            self._embedding_function = SentenceTransformerEmbeddingFunction(
                model_name=self.embedder_model
            )
        return self._client, self._embedding_function

    @contextmanager
    def _user_scope(self, user_id: str) -> Iterator[None]:
        """Route every ChromaRetriever A-MEM creates (at construction and in
        consolidate_memories) to this user's collection on the shared client."""
        import agentic_memory.memory_system as amem_ms  # type: ignore[import-not-found]
        from agentic_memory.retrievers import ChromaRetriever  # type: ignore[import-not-found]

        client, embedding_function = self._shared_backend()
        user_collection = self._collection_name(user_id)

        # Same signature as ChromaRetriever; A-MEM's arguments are ignored on purpose.
        def scoped_retriever(collection_name: str = "memories", model_name: str = "") -> Any:
            retriever = ChromaRetriever.__new__(ChromaRetriever)
            retriever.client = _NoResetClient(client)
            retriever.embedding_function = embedding_function
            retriever.collection = client.get_or_create_collection(
                name=user_collection, embedding_function=embedding_function
            )
            return retriever

        original = amem_ms.ChromaRetriever
        amem_ms.ChromaRetriever = scoped_retriever
        try:
            yield
        finally:
            amem_ms.ChromaRetriever = original

    def _install_llm_shim(self, system: Any) -> None:
        """Pass temperature and base URL that OllamaController.get_completion drops."""
        from agentic_memory.llm_controller import OllamaController  # type: ignore[import-not-found]

        llm = system.llm_controller.llm
        if not isinstance(llm, OllamaController):
            raise RuntimeError("A-MEM is not using the Ollama backend; refusing (no paid APIs).")

        adapter = self

        def get_completion(
            self_llm: Any, prompt: str, response_format: dict[str, Any], temperature: float = 0.0
        ) -> str:
            from litellm import completion

            response = completion(
                model=f"ollama_chat/{self_llm.model}",
                messages=[
                    {"role": "system", "content": _AMEM_SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ],
                response_format=response_format,
                temperature=adapter.temperature,
                api_base=adapter.ollama_base_url,
            )
            return str(response.choices[0].message.content)

        llm.get_completion = types.MethodType(get_completion, llm)

    def _system(self, user_id: str) -> Any:
        if user_id not in self._systems:
            from agentic_memory.memory_system import AgenticMemorySystem

            with self._user_scope(user_id):
                system = AgenticMemorySystem(
                    model_name=self.embedder_model,
                    llm_backend="ollama",
                    llm_model=self.llm_model,
                    evo_threshold=self.evo_threshold,
                )
            self._install_llm_shim(system)
            self._systems[user_id] = system
            self._note_meta.setdefault(user_id, {})
        return self._systems[user_id]

    def _check_index(self, user_id: str, system: Any) -> None:
        """The vector index must hold exactly the notes A-MEM knows about."""
        indexed = system.retriever.collection.count()
        if indexed != len(system.memories):
            raise RuntimeError(
                f"A-MEM index out of sync for {user_id}: {indexed} indexed vs "
                f"{len(system.memories)} notes. Retrieval results would be invalid."
            )

    def _to_memory(self, user_id: str, note_id: str, text: str, extra: dict[str, Any]) -> Memory:
        meta = dict(self._note_meta.get(user_id, {}).get(note_id, {}))
        meta.update(extra)
        return Memory(raw_id=note_id, text=text, lang_detected="", metadata=meta)

    # ------------------------------------------------------------------ interface

    def reset(self, user_id: str) -> None:
        """Wipe all memories for the target user, leaving other users untouched."""
        self._systems.pop(user_id, None)
        self._note_meta[user_id] = {}
        client, _ = self._shared_backend()
        name = self._collection_name(user_id)
        if name in {c.name for c in client.list_collections()}:
            client.delete_collection(name)

    def write(self, user_id: str, turn: Turn) -> WriteResult:
        """Ingest a turn: A-MEM stores the text as a new note and runs evolution."""
        system = self._system(user_id)
        try:
            with self._user_scope(user_id), capture_framework_errors("agentic_memory") as errs:
                note_id = system.add_note(turn.text)
        except Exception as e:  # A-MEM raises bare exceptions from LLM/Chroma calls
            logger.warning("A-MEM add_note failed for %s: %s", user_id, e)
            return WriteResult(success=False, memory_id=None, metadata={"error": str(e)})
        self._note_meta[user_id][note_id] = {
            "fact_id": turn.fact_id or "",
            "kind": turn.kind,
            "lang": turn.lang,
            "session_id": turn.session_id,
        }
        return WriteResult(success=True, memory_id=note_id, metadata={"framework_errors": errs})

    def consolidate(self, user_id: str) -> ConsolidationResult:
        """A-MEM evolves memories on write; no explicit consolidation (AGENTS.md §14)."""
        return ConsolidationResult(consolidated_count=0, metadata={"implicit": True})

    def retrieve(self, user_id: str, query: str, lang: str, k: int = 5) -> list[Memory]:
        """Top-k memories via A-MEM's search_agentic (vector hits plus linked notes)."""
        system = self._system(user_id)
        self._check_index(user_id, system)
        with self._user_scope(user_id):
            results = system.search_agentic(query, k)
        if not results and system.memories:
            raise RuntimeError(
                f"A-MEM search_agentic returned nothing for {user_id} with "
                f"{len(system.memories)} notes stored (it swallows its own errors)."
            )
        return [
            self._to_memory(
                user_id,
                str(r["id"]),
                str(r.get("content", "")),
                {"is_neighbor": bool(r.get("is_neighbor", False)), "score": r.get("score")},
            )
            for r in results
        ]

    def update(self, user_id: str, correction: Turn) -> UpdateResult:
        """A correction is another conversational turn; A-MEM stores it as a new note."""
        w_res = self.write(user_id=user_id, turn=correction)
        return UpdateResult(
            success=w_res.success, updated_memory_id=w_res.memory_id, metadata=w_res.metadata
        )

    def dump(self, user_id: str) -> list[Memory]:
        """Return the COMPLETE store: every note in A-MEM's in-process note dict.

        Hard Requirement: dump() must return all memories without top-k truncation.
        """
        if user_id not in self._systems:
            return []
        system = self._systems[user_id]
        self._check_index(user_id, system)
        return [
            self._to_memory(
                user_id,
                note_id,
                note.content,
                {
                    "keywords": list(note.keywords or []),
                    "tags": list(note.tags or []),
                    "context": note.context,
                    "links": list(note.links or []),
                },
            )
            for note_id, note in system.memories.items()
        ]
