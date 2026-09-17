"""Mitigation 2: Cross-lingual Entity Resolution (XLing-ER) before consolidation."""

from __future__ import annotations

import logging
from typing import Sequence
from xlmem.benchmark.facts import Memory, Turn
from xlmem.llm.client import LLMClient

logger = logging.getLogger(__name__)


class CrossLingualEntityResolver:
    """Detects cross-lingual entity and proposition equivalence before consolidation."""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def resolve_and_deduplicate(
        self,
        new_turn: Turn,
        existing_memories: Sequence[Memory],
    ) -> tuple[bool, Memory | None]:
        """Determine if new_turn expresses the same underlying fact as any existing memory.

        Returns:
            (is_duplicate, matched_existing_memory)
        """
        if not existing_memories:
            return False, None

        # Build prompt listing existing memories to verify entity match
        mems_context = "\n".join(f"[{i+1}] {m.text}" for i, m in enumerate(existing_memories[:10]))
        prompt = (
            f"You are a cross-lingual entity resolution system. Determine if the new statement "
            f"refers to the exact same personal fact as any existing memory (even if in a different language).\n\n"
            f"Existing Memories:\n{mems_context}\n\n"
            f"New Statement: {new_turn.text}\n\n"
            f"Is this statement already captured in an existing memory? Answer YES with the memory index, or NO."
        )

        resp = self.llm_client.generate(prompt=prompt, temperature=0.0)
        text = resp.text.strip().upper()
        if "YES" in text:
            # Found duplicate
            return True, existing_memories[0]

        return False, None
