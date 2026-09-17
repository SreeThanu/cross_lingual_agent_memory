"""Memory probe execution. Deliberately records raw responses without judging."""

from __future__ import annotations

import logging
from typing import Sequence
from xlmem.adapters.base import MemoryAdapter
from xlmem.benchmark.facts import Fact, Memory, ProbeResult
from xlmem.llm.client import LLMClient

logger = logging.getLogger(__name__)


def execute_probe(
    adapter: MemoryAdapter,
    llm_client: LLMClient,
    user_id: str,
    fact: Fact,
    store_lang: str,
    probe_lang: str,
    k: int = 5,
    system_prompt: str | None = None,
) -> ProbeResult:
    """Issue a single memory retrieval probe and generate a raw model response.

    The runner NEVER judges hit/miss. It retrieves memory context and records
    the raw generated output. Scoring happens offline in xlmem/scoring/.
    """
    # 1. Retrieve top-k memories
    q_text = ""
    if fact.probe_questions and probe_lang in fact.probe_questions:
        q_text = fact.probe_questions[probe_lang]
    else:
        if probe_lang == "hi":
            q_text = f"यूज़र के {fact.relation} के बारे में क्या जानकारी है?"
        else:
            q_text = f"What is the user's {fact.relation.replace('_', ' ')}?"

    retrieved: list[Memory] = adapter.retrieve(user_id=user_id, query=q_text, lang=probe_lang, k=k)

    # 2. Build context prompt for the backbone LLM
    context_str = "\n".join(f"- {m.text}" for m in retrieved) if retrieved else "None"
    sys = (
        system_prompt
        or "You are a helpful conversational AI assistant with access to user memory notes. Answer the question using the provided memories."
    )
    user_prompt = f"User Memories:\n{context_str}\n\nQuestion: {q_text}\nAnswer:"

    # 3. Call backbone LLM via chokepoint
    resp = llm_client.generate(prompt=user_prompt, system_prompt=sys, temperature=0.0)

    # 4. Record raw response. hit_strict and hit_lenient remain unjudged here
    return ProbeResult(
        fact_id=fact.id,
        store_lang=store_lang,
        probe_lang=probe_lang,
        retrieved=retrieved,
        response=resp.text,
        hit_strict=False,
        hit_lenient=False,
        metadata={"tokens": resp.total_tokens, "latency": resp.latency_seconds},
    )
