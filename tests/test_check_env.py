"""check_env's pure helpers."""

from xlmem.scripts.check_env import REQUIRED_OLLAMA_MODELS, missing_models


def test_missing_models_treats_bare_names_as_latest() -> None:
    assert missing_models(["qwen2.5:7b-instruct", "bge-m3:latest"], REQUIRED_OLLAMA_MODELS) == []
    assert missing_models(["qwen2.5:7b-instruct"], REQUIRED_OLLAMA_MODELS) == ["bge-m3:latest"]
    assert missing_models(["bge-m3"], ("bge-m3",)) == []


def test_a_different_quantisation_or_size_does_not_count() -> None:
    assert missing_models(["qwen2.5:7b-instruct-q8_0"], ("qwen2.5:7b-instruct",)) == [
        "qwen2.5:7b-instruct"
    ]
