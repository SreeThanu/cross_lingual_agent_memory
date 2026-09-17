"""Mitigations for cross-lingual agent memory degradation."""

from xlmem.mitigations.normalize import MemoryNormalizer
from xlmem.mitigations.xling_er import CrossLingualEntityResolver

__all__ = ["MemoryNormalizer", "CrossLingualEntityResolver"]
