"""Embedding interface for BGE-M3 and multilingual sentence encoders."""

from __future__ import annotations

import logging
from typing import Sequence
import numpy as np

logger = logging.getLogger(__name__)


class Embedder:
    """Local multilingual sentence embedder using BGE-M3 or equivalent."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        mock_mode: bool = False,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.mock_mode = mock_mode
        self.device = device
        self._model = None

        if not self.mock_mode:
            self._load_model()

    def _load_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            import torch

            chosen_device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._model = SentenceTransformer(self.model_name, device=chosen_device)
            logger.info("Loaded embedder '%s' on %s", self.model_name, chosen_device)
        except Exception as e:
            logger.warning(
                "Could not load SentenceTransformer (%s). Falling back to mock embeddings: %s",
                self.model_name,
                e,
            )
            self.mock_mode = True

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Encode a sequence of texts into unit-normalized embeddings."""
        if not texts:
            return np.empty((0, 384), dtype=np.float32)

        if self.mock_mode or self._model is None:
            # Deterministic pseudo-embedding based on hash
            dim = 384
            embeddings = []
            for t in texts:
                rng = np.random.RandomState(abs(hash(t)) % (2**32))
                vec = rng.randn(dim).astype(np.float32)
                norm = np.linalg.norm(vec)
                embeddings.append(vec / (norm if norm > 0 else 1.0))
            return np.array(embeddings)

        return self._model.encode(list(texts), normalize_embeddings=True)  # type: ignore[no-any-return]
