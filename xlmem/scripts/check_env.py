"""Environment verification script for XLMem.

Checks:
- Python >= 3.11
- PyTorch + CUDA available
- VRAM >= 14 GB free
- Ollama reachable at localhost:11434, with the experiment models pulled
- BGE-M3 (sentence-transformers, used by A-MEM) loads and embeds Hindi and English
- HuggingFace reachability
"""

from __future__ import annotations

import logging
import sys
import requests

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("check_env")

# Ollama tags the pilot and main configs use; the harness never pulls (mem0_adapter).
REQUIRED_OLLAMA_MODELS = ("qwen2.5:7b-instruct", "bge-m3:latest")
# Second backbone of the main matrix (PRD §8); not needed until P3.
LATER_OLLAMA_MODELS = ("llama3.2:3b-instruct",)
EMBEDDER = "BAAI/bge-m3"


def check_python_version() -> bool:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    logger.info("Python version: %d.%d.%d -> %s", v.major, v.minor, v.micro, "OK" if ok else "FAIL")
    return ok


def check_cuda_and_vram() -> bool:
    try:
        import torch

        cuda_ok = torch.cuda.is_available()
        logger.info("CUDA available: %s", cuda_ok)
        if not cuda_ok:
            logger.warning("CUDA is NOT available. Running on CPU / MPS. (Acceptable for testing/scoring).")
            return False

        device_count = torch.cuda.device_count()
        device_name = torch.cuda.get_device_name(0)
        # Device-wide figures: memory held by other processes (the Ollama server and
        # its loaded models) counts. torch.cuda.memory_reserved sees only this process.
        free_b, total_b = torch.cuda.mem_get_info(0)
        total_vram_gb = total_b / (1024**3)
        free_vram_gb = free_b / (1024**3)

        logger.info("GPU device 0: %s (%d devices)", device_name, device_count)
        logger.info("Total VRAM: %.2f GB | Free: %.2f GB", total_vram_gb, free_vram_gb)

        if free_vram_gb < 14.0:
            logger.warning(
                "Free VRAM (%.2f GB) is below the 14 GB threshold (models already loaded by "
                "Ollama count against it; see nvidia-smi).", free_vram_gb
            )
            return False
        return True
    except ImportError:
        logger.error("PyTorch not installed.")
        return False


def missing_models(installed: list[str], required: tuple[str, ...]) -> list[str]:
    """Required Ollama tags absent from an /api/tags listing (a bare name means :latest)."""
    have = set(installed) | {n.removesuffix(":latest") for n in installed}
    return [m for m in required if m not in have]


def check_ollama_reachable(base_url: str = "http://localhost:11434") -> bool:
    try:
        res = requests.get(f"{base_url}/api/tags", timeout=5)
    except requests.RequestException as e:
        logger.warning("Ollama NOT reachable at %s: %s", base_url, e)
        return False
    if res.status_code != 200:
        logger.warning("Ollama responded with status code %d", res.status_code)
        return False
    models = [m.get("name") or m.get("model") for m in res.json().get("models", [])]
    logger.info("Ollama reachable at %s. Installed models: %s", base_url, models)
    missing = missing_models(models, REQUIRED_OLLAMA_MODELS)
    if missing:
        logger.error("Required Ollama models not pulled: %s (run: ollama pull <tag>)", missing)
    later = missing_models(models, LATER_OLLAMA_MODELS)
    if later:
        logger.warning("Not pulled yet, needed from P3 (main matrix): %s", later)
    return not missing


def check_embedder_loads(model_name: str = EMBEDDER) -> bool:
    """Load the real BGE-M3 and check a Hindi/English paraphrase pair embeds close together."""
    try:
        import sqlite3  # noqa: F401  # load order: see xlmem/adapters/amem_adapter.py

        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        en, hi, other = model.encode(
            ["I am allergic to peanuts.", "मुझे मूंगफली से एलर्जी है।", "My hometown is Jaipur."],
            normalize_embeddings=True,
        )
    except Exception as e:  # report any load failure; this is a diagnostic script
        logger.error("Embedder %s failed to load: %s", model_name, e)
        return False
    same, diff = float(en @ hi), float(en @ other)
    ok = same > diff
    logger.info(
        "Embedder %s: dim %d, cos(en, hi paraphrase) %.2f vs cos(en, unrelated) %.2f -> %s",
        model_name, len(en), same, diff, "OK" if ok else "FAIL",
    )
    return ok


def check_huggingface_reachable() -> bool:
    try:
        res = requests.get("https://huggingface.co", timeout=5)
        ok = res.status_code == 200
        logger.info("huggingface.co reachable: %s", "OK" if ok else "FAIL")
        return ok
    except requests.RequestException as e:
        logger.warning("huggingface.co not directly reachable: %s", e)
        return False


def main() -> int:
    logger.info("=== Running XLMem Environment Verification ===")
    results = [
        check_python_version(),
        check_cuda_and_vram(),  # before the embedder check puts BGE-M3 on the GPU
        check_huggingface_reachable(),
        check_ollama_reachable(),
        check_embedder_loads(),
    ]
    all_ok = all(results)
    if all_ok:
        logger.info("=== All environment checks PASSED ===")
        return 0
    logger.warning("=== Some checks did not pass (see details above) ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
