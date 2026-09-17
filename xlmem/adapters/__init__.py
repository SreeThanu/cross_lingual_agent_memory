"""Adapter registry for memory frameworks."""

from __future__ import annotations

from typing import Type
from xlmem.adapters.base import MemoryAdapter
from xlmem.adapters.mock_adapter import MockAdapter

_REGISTRY: dict[str, Type[MemoryAdapter]] = {
    "mock": MockAdapter,
}


def register_adapter(name: str, adapter_cls: Type[MemoryAdapter]) -> None:
    """Register a new memory framework adapter."""
    _REGISTRY[name.lower()] = adapter_cls


def get_adapter(name: str, **kwargs: object) -> MemoryAdapter:
    """Instantiate a memory framework adapter by name."""
    key = name.lower()
    if key not in _REGISTRY:
        # Check if dynamic import is available
        if key == "mem0":
            from xlmem.adapters.mem0_adapter import Mem0Adapter

            register_adapter("mem0", Mem0Adapter)
        elif key == "letta":
            from xlmem.adapters.letta_adapter import LettaAdapter

            register_adapter("letta", LettaAdapter)
        elif key == "amem":
            from xlmem.adapters.amem_adapter import AMEMAdapter

            register_adapter("amem", AMEMAdapter)
        else:
            available = list(_REGISTRY.keys())
            raise ValueError(f"Unknown memory adapter '{name}'. Registered: {available}")

    cls = _REGISTRY[key]
    return cls(**kwargs)  # type: ignore[call-arg]


__all__ = [
    "MemoryAdapter",
    "MockAdapter",
    "get_adapter",
    "register_adapter",
]
