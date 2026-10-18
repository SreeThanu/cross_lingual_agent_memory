"""Mem0Adapter's guards around Mem0 0.1.26's Ollama and telemetry behaviour (offline)."""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("mem0")

from xlmem.adapters.mem0_adapter import (  # noqa: E402
    _ollama_model_names,
    _patch_mem0_ollama,
    _require_local_model,
)


class _FakeClient:
    def __init__(self, listing: Any) -> None:
        self.listing = listing
        self.pulled: list[str] = []

    def list(self) -> Any:
        return self.listing

    def pull(self, model: str) -> None:  # pragma: no cover - must never be reached
        self.pulled.append(model)


def _new_style(*tags: str) -> dict[str, list[Any]]:
    """ollama>=0.4: list() items are Model objects with .model and no "name"."""

    class Model(dict):
        def __init__(self, tag: str) -> None:
            super().__init__(model=tag)
            self.model = tag

    return {"models": [Model(t) for t in tags]}


def test_model_names_read_both_ollama_client_formats() -> None:
    assert _ollama_model_names(_new_style("bge-m3:latest")) == {"bge-m3:latest"}
    assert _ollama_model_names({"models": [{"name": "qwen2.5:7b-instruct"}]}) == {
        "qwen2.5:7b-instruct"
    }


def test_present_model_is_accepted_without_pulling() -> None:
    """Regression: Mem0 matched on model["name"] (None in ollama 0.6.2) and pulled every init."""
    client = _FakeClient(_new_style("bge-m3:latest", "qwen2.5:7b-instruct"))
    obj = SimpleNamespace(client=client, config=SimpleNamespace(model="bge-m3:latest"))
    _require_local_model(obj)
    assert client.pulled == []


def test_missing_model_raises_instead_of_pulling() -> None:
    client = _FakeClient(_new_style("qwen2.5:7b-instruct"))
    obj = SimpleNamespace(client=client, config=SimpleNamespace(model="bge-m3:latest"))
    with pytest.raises(RuntimeError, match="not pulled locally"):
        _require_local_model(obj)
    assert client.pulled == []


def test_patch_replaces_both_mem0_model_checks() -> None:
    from mem0.embeddings.ollama import OllamaEmbedding
    from mem0.llms.ollama import OllamaLLM

    _patch_mem0_ollama()
    assert OllamaEmbedding._ensure_model_exists is _require_local_model
    assert OllamaLLM._ensure_model_exists is _require_local_model


def test_importing_the_adapter_turns_mem0_telemetry_off() -> None:
    """Mem0 reads MEM0_TELEMETRY once at import; the adapter must win even if the env says True."""
    code = (
        "import xlmem.adapters.mem0_adapter as a; a._patch_mem0_ollama();"
        "from mem0.memory import telemetry as t;"
        "assert t.MEM0_TELEMETRY is False and t.telemetry.posthog.disabled; print('ok')"
    )
    env = {**os.environ, "MEM0_TELEMETRY": "True", "HF_HUB_OFFLINE": "1"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            timeout=300, env=env)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")
