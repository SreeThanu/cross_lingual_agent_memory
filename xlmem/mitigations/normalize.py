"""Mitigation 1: Pivot-language normalization at write time."""

from __future__ import annotations

import logging
from xlmem.benchmark.facts import Turn
from xlmem.llm.client import LLMClient

logger = logging.getLogger(__name__)


class MemoryNormalizer:
    """Translates/normalizes incoming conversational turns into a canonical pivot language."""

    def __init__(self, llm_client: LLMClient, pivot_lang: str = "en") -> None:
        self.llm_client = llm_client
        self.pivot_lang = pivot_lang

    def normalize_turn(self, turn: Turn) -> Turn:
        """Translate turn text to pivot language if in a different language."""
        if turn.lang == self.pivot_lang:
            return turn

        prompt = (
            f"Translate the following user personal statement from {turn.lang} into clear, concise English. "
            f"Preserve all facts, names, and entities exactly.\n\nText: {turn.text}\nTranslation:"
        )
        resp = self.llm_client.generate(prompt=prompt, temperature=0.0)
        translated_text = resp.text.strip()

        return Turn(
            session_id=turn.session_id,
            role=turn.role,
            lang=self.pivot_lang,
            text=translated_text if translated_text else turn.text,
            kind=turn.kind,
            fact_id=turn.fact_id,
        )
