"""Adapter utilities."""

from .bridge import AdapterBridge, AdapterHandle
from .metadata import AdapterMetadata, register_adapter_metadata
from .watcher import AdapterConfigWatcher

__all__ = [
    "AdapterBridge",
    "AdapterHandle",
    "AdapterMetadata",
    "register_adapter_metadata",
    "AdapterConfigWatcher",
]
