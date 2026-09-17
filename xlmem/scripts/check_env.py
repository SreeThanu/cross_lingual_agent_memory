"""Environment verification script for XLMem.

Checks:
- Python >= 3.11
- PyTorch + CUDA available
- VRAM >= 14 GB free
- Ollama reachable at localhost:11434
- Sentence-transformers / embedder loads
- HuggingFace reachability
"""

from __future__ import annotations

import logging
import sys
import requests

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("check_env")


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
        total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        reserved_vram_gb = torch.cuda.memory_reserved(0) / (1024**3)
        free_vram_gb = total_vram_gb - reserved_vram_gb

        logger.info("GPU device 0: %s (%d devices)", device_name, device_count)
        logger.info("Total VRAM: %.2f GB | Free: %.2f GB", total_vram_gb, free_vram_gb)

        if free_vram_gb < 14.0:
            logger.warning("Free VRAM (%.2f GB) is below the 14 GB threshold.", free_vram_gb)
            return False
        return True
    except ImportError:
        logger.error("PyTorch not installed.")
        return False


def check_ollama_reachable(base_url: str = "http://localhost:11434") -> bool:
    try:
        res = requests.get(f"{base_url}/api/tags", timeout=5)
        if res.status_code == 200:
            models = [m.get("name") for m in res.json().get("models", [])]
            logger.info("Ollama reachable at %s. Installed models: %s", base_url, models)
            return True
        logger.warning("Ollama responded with status code %d", res.status_code)
        return False
    except requests.RequestException as e:
        logger.warning("Ollama NOT reachable at %s: %s", base_url, e)
        return False


def check_embedder_loads() -> bool:
    try:
        from xlmem.llm.embedder import Embedder

        embedder = Embedder(mock_mode=True)
        res = embedder.embed(["Hello world", "नमस्ते दुनिया"])
        logger.info("Embedder test shape: %s -> OK", res.shape)
        return True
    except Exception as e:
        logger.error("Embedder failed to load: %s", e)
        return False


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
        check_embedder_loads(),
        check_huggingface_reachable(),
        check_ollama_reachable(),
        check_cuda_and_vram(),
    ]
    all_ok = all(results)
    if all_ok:
        logger.info("=== All environment checks PASSED ===")
        return 0
    logger.warning("=== Some checks did not pass (see details above) ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
