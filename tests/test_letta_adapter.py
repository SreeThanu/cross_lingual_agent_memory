"""LettaAdapter agent-config checks, against a fake Letta client (no server)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from xlmem.adapters.letta_adapter import LettaAdapter


class _Config(SimpleNamespace):
    def model_copy(self, update: dict[str, Any]) -> _Config:
        return _Config(**{**vars(self), **update})


class _FakeAgents:
    """Letta's server defaults new agents to temperature 0.7."""

    def __init__(self, endpoint: str = "http://localhost:11434/v1") -> None:
        self.llm = _Config(handle="ollama/qwen2.5:7b-instruct", temperature=0.7,
                           model_endpoint=endpoint)
        self.emb = _Config(handle="ollama/bge-m3:latest", embedding_endpoint=endpoint)
        self.deleted: list[str] = []

    def _agent(self) -> SimpleNamespace:
        return SimpleNamespace(id="agent-1", llm_config=self.llm, embedding_config=self.emb)

    def create(self, **_: Any) -> SimpleNamespace:
        return self._agent()

    def modify(self, agent_id: str, llm_config: _Config) -> None:
        self.llm = llm_config

    def retrieve(self, agent_id: str) -> SimpleNamespace:
        return self._agent()

    def delete(self, agent_id: str) -> None:
        self.deleted.append(agent_id)


def _adapter(agents: _FakeAgents, **kwargs: Any) -> LettaAdapter:
    adapter = LettaAdapter(base_url="http://letta.test:1", **kwargs)
    adapter._client = SimpleNamespace(agents=agents)
    return adapter


def test_new_agents_get_the_harness_temperature() -> None:
    agents = _FakeAgents()
    _adapter(agents)._create_agent("u")
    assert agents.llm.temperature == 0.0


def test_agent_on_another_ollama_is_rejected_and_deleted() -> None:
    agents = _FakeAgents(endpoint="http://elsewhere:11434/v1")
    with pytest.raises(RuntimeError, match="endpoint"):
        _adapter(agents)._create_agent("u")
    assert agents.deleted == ["agent-1"]


def test_hosted_letta_model_is_refused() -> None:
    adapter = _adapter(_FakeAgents())
    adapter.llm_handle = "letta/letta-free"
    with pytest.raises(RuntimeError, match="non-local"):
        adapter._create_agent("u")
