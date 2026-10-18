"""AMEMAdapter against the real A-MEM code and a real in-memory Chroma store.

Only the LLM is stubbed (at litellm.completion, below the adapter's shim), so these
run offline. They use the cached all-MiniLM-L6-v2 embedder for speed; experiments
use the adapter's default, BGE-M3.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("agentic_memory")
litellm = pytest.importorskip("litellm")

from xlmem.adapters.amem_adapter import AMEMAdapter  # noqa: E402
from xlmem.benchmark.facts import Turn  # noqa: E402

TEST_EMBEDDER = "all-MiniLM-L6-v2"


@pytest.fixture
def llm_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        prompt = kwargs["messages"][-1]["content"]
        if "should_evolve" in prompt:
            body = {"should_evolve": False, "actions": [], "suggested_connections": [],
                    "tags_to_update": [], "new_context_neighborhood": [],
                    "new_tags_neighborhood": []}
        else:
            body = {"keywords": ["k"], "context": "c", "tags": ["t"]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(body)))])

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls


@pytest.fixture
def adapter() -> AMEMAdapter:
    try:
        return AMEMAdapter(embedder_model=TEST_EMBEDDER, ollama_base_url="http://ollama.test:1")
    except OSError as e:  # pragma: no cover - embedder not in the local cache
        pytest.skip(f"embedder unavailable: {e}")


def _turn(text: str, fact_id: str, lang: str = "en") -> Turn:
    return Turn(session_id=1, role="user", lang=lang, text=text, kind="plant", fact_id=fact_id)


def test_second_user_does_not_wipe_first_users_index(adapter: AMEMAdapter, llm_calls: list) -> None:
    """Regression: A-MEM's constructor resets the global Chroma client."""
    adapter.reset("alpha")
    adapter.write("alpha", _turn("My favorite color is navy blue.", "f_a"))
    adapter.reset("beta")
    adapter.write("beta", _turn("Beta's favorite color is green.", "f_b"))

    hits = adapter.retrieve("alpha", "What is my favorite color?", lang="en", k=3)
    assert [m.text for m in hits] == ["My favorite color is navy blue."]
    assert [m.metadata["fact_id"] for m in adapter.dump("alpha")] == ["f_a"]
    assert [m.metadata["fact_id"] for m in adapter.dump("beta")] == ["f_b"]

    adapter.reset("alpha")
    assert adapter.dump("alpha") == []
    assert len(adapter.dump("beta")) == 1


def test_dump_is_complete_and_keeps_duplicates(adapter: AMEMAdapter, llm_calls: list) -> None:
    adapter.reset("u")
    texts = ["मुझे मूंगफली से गंभीर एलर्जी है।", "I have a severe allergy to peanuts.",
             "I have a severe allergy to peanuts."] + [f"memory {i}" for i in range(9)]
    for i, text in enumerate(texts):
        assert adapter.write("u", _turn(text, f"f_{i}")).success
    dumped = adapter.dump("u")
    assert len(dumped) == 12
    assert sum(m.text == texts[1] for m in dumped) == 2  # A-MEM never deduplicates


def test_llm_calls_use_ollama_with_harness_temperature(
    adapter: AMEMAdapter, llm_calls: list
) -> None:
    adapter.reset("u")
    adapter.write("u", _turn("I live in Pune.", "f_1"))
    adapter.write("u", _turn("I work at Infosys.", "f_2"))
    assert llm_calls, "A-MEM made no LLM call"
    for call in llm_calls:
        assert call["model"] == "ollama_chat/qwen2.5:7b-instruct"
        assert call["temperature"] == 0.0
        assert call["api_base"] == "http://ollama.test:1"


def test_out_of_sync_index_raises_instead_of_returning_misses(
    adapter: AMEMAdapter, llm_calls: list
) -> None:
    adapter.reset("u")
    adapter.write("u", _turn("I live in Pune.", "f_1"))
    adapter._systems["u"].retriever.collection.delete(ids=list(adapter._systems["u"].memories))
    with pytest.raises(RuntimeError, match="out of sync"):
        adapter.retrieve("u", "Where do I live?", lang="en")
    with pytest.raises(RuntimeError, match="out of sync"):
        adapter.dump("u")


def test_shared_backend_imports_chromadb_in_a_fresh_interpreter() -> None:
    """Regression: a bare `import chromadb` fails in the xlmem env (libstdc++ load order).

    Runs in a subprocess because in this test process sqlite3 or torch is already
    loaded, which hides the bug.
    """
    import subprocess
    import sys

    code = (
        "import sys; from xlmem.adapters.amem_adapter import AMEMAdapter;"
        "a = AMEMAdapter(embedder_model='all-MiniLM-L6-v2'); a._shared_backend();"
        "assert 'torch' in sys.modules or 'sqlite3' in sys.modules; print('ok')"
    )
    env = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "ANONYMIZED_TELEMETRY": "False"}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, **env},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")
