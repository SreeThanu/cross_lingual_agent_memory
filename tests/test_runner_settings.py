"""The runner builds every adapter with the experiment config's model settings.

Regression: get_adapter(framework) was called without settings, so every framework
ran its default backbone (qwen2.5:7b-instruct) whatever the config named.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

import xlmem.runner.experiment as experiment
from xlmem.adapters.amem_adapter import AMEMAdapter
from xlmem.adapters.base import ADAPTER_SETTINGS
from xlmem.adapters.letta_adapter import LettaAdapter
from xlmem.adapters.mem0_adapter import Mem0Adapter
from xlmem.adapters.mock_adapter import MockAdapter
from xlmem.benchmark.facts import Fact
from xlmem.config import BenchmarkConfig, ExperimentConfig, LanguageConfig, ModelConfig
from xlmem.llm.client import LLMClient

FACT = Fact(
    id="g_01", domain="health", entity="user", relation="allergic_to", value="peanuts",
    surface={"en": "I am allergic to peanuts.", "hi": "मुझे मूंगफली से एलर्जी है।"},
    probe_questions={"en": "What food am I allergic to?", "hi": "मुझे किस चीज़ से एलर्जी है?"},
)


def _config(tmp_path: Path, **model: Any) -> ExperimentConfig:
    return ExperimentConfig(
        experiment="settings_test",
        framework="mock",
        model=ModelConfig(**model),
        embedder="intfloat/multilingual-e5-base",
        languages=LanguageConfig(store="en", probe="en"),
        benchmark=BenchmarkConfig(fact_bank="dummy", n_facts=1, filler_sessions=0),
        seeds=[11],
        output_dir=str(tmp_path / "run"),
    )


def test_runner_passes_config_model_to_adapter_and_logs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[dict[str, Any]] = []

    def recording_get_adapter(name: str, **kwargs: Any) -> MockAdapter:
        built.append({"name": name, **kwargs})
        return MockAdapter(**kwargs)

    monkeypatch.setattr(experiment, "get_adapter", recording_get_adapter)
    cfg = _config(tmp_path, name="llama3.2:3b-instruct", temperature=0.0,
                  base_url="http://ollama.test:1")
    runner = experiment.ExperimentRunner(config=cfg, llm_client=LLMClient(mock_mode=True))
    seed_dir = runner.run_single_seed(facts=[FACT], seed=11)

    expected = {
        "llm_model": "llama3.2:3b-instruct",
        "embedder_model": "intfloat/multilingual-e5-base",
        "ollama_base_url": "http://ollama.test:1",
        "temperature": 0.0,
    }
    assert built == [{"name": "mock", **expected}]
    with open(seed_dir / "run_log.jsonl", encoding="utf-8") as f:
        meta = json.loads(f.readline())
    assert meta["adapter_settings"] == expected


@pytest.mark.parametrize("adapter_cls", [MockAdapter, Mem0Adapter, LettaAdapter, AMEMAdapter])
def test_every_adapter_accepts_the_settings_contract(adapter_cls: type) -> None:
    params = inspect.signature(adapter_cls.__init__).parameters
    assert set(ADAPTER_SETTINGS) <= set(params), adapter_cls.__name__


def test_letta_maps_the_config_embedder_to_its_ollama_tag() -> None:
    adapter = LettaAdapter(base_url="http://letta.test:1", llm_model="llama3.2:3b-instruct",
                           embedder_model="BAAI/bge-m3")
    assert adapter.llm_handle == "ollama/llama3.2:3b-instruct"
    assert adapter.embedding_handle == "ollama/bge-m3:latest"


def test_non_ollama_backend_is_rejected_for_real_frameworks(tmp_path: Path) -> None:
    cfg = _config(tmp_path, backend="vllm").model_copy(update={"framework": "mem0"})
    with pytest.raises(ValueError, match="Ollama only"):
        experiment.adapter_settings(cfg)


def test_run_log_records_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENTS.md §12: every run records git SHA, input hashes and package versions."""
    monkeypatch.setattr(experiment, "get_adapter", lambda name, **kw: MockAdapter(**kw))
    cfg = _config(tmp_path)
    runner = experiment.ExperimentRunner(config=cfg, llm_client=LLMClient(mock_mode=True))
    seed_dir = runner.run_single_seed(facts=[FACT], seed=11)
    with open(seed_dir / "run_log.jsonl", encoding="utf-8") as f:
        prov = json.loads(f.readline())["provenance"]

    assert prov["git_sha"] == experiment._git("rev-parse", "HEAD")
    assert len(prov["git_sha"]) == 40
    assert isinstance(prov["git_dirty"], bool)
    assert prov["config_sha256"] == experiment.hashlib.sha256(
        cfg.model_dump_json().encode("utf-8")).hexdigest()
    assert prov["fact_bank_sha256"] is None  # "dummy" is not a file
    assert set(prov["packages"]) == set(experiment.PROVENANCE_PACKAGES)
    assert prov["packages"]["pydantic"]


def test_config_hash_changes_with_the_config(tmp_path: Path) -> None:
    a = experiment.run_provenance(_config(tmp_path))
    b = experiment.run_provenance(_config(tmp_path, temperature=0.7))
    assert a["config_sha256"] != b["config_sha256"]
