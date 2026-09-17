"""Session driver: ingests turns into memory adapter and captures snapshots."""

from __future__ import annotations

import logging
from typing import Sequence
from xlmem.adapters.base import MemoryAdapter
from xlmem.benchmark.facts import Memory, Turn

logger = logging.getLogger(__name__)


class SessionRunner:
    """Orchestrates turn ingestion into a MemoryAdapter."""

    def __init__(self, adapter: MemoryAdapter, user_id: str) -> None:
        self.adapter = adapter
        self.user_id = user_id

    def run_session(self, turns: Sequence[Turn]) -> list[dict[str, object]]:
        """Ingest a batch of turns into the adapter and return per-turn trace records."""
        records: list[dict[str, object]] = []

        for turn in turns:
            if turn.kind in ("plant", "filler"):
                w_res = self.adapter.write(user_id=self.user_id, turn=turn)
                records.append({
                    "session_id": turn.session_id,
                    "kind": turn.kind,
                    "fact_id": turn.fact_id,
                    "lang": turn.lang,
                    "text": turn.text,
                    "write_success": w_res.success,
                    "memory_id": w_res.memory_id,
                })
            elif turn.kind == "correction":
                u_res = self.adapter.update(user_id=self.user_id, correction=turn)
                records.append({
                    "session_id": turn.session_id,
                    "kind": turn.kind,
                    "fact_id": turn.fact_id,
                    "lang": turn.lang,
                    "text": turn.text,
                    "update_success": u_res.success,
                    "updated_memory_id": u_res.updated_memory_id,
                })

        return records

    def consolidate(self) -> int:
        """Trigger consolidation on the underlying store."""
        c_res = self.adapter.consolidate(user_id=self.user_id)
        return c_res.consolidated_count

    def snapshot(self) -> list[Memory]:
        """Capture a complete snapshot of the store via dump()."""
        return self.adapter.dump(user_id=self.user_id)
