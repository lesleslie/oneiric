"""Adapter utilities."""

from .bootstrap import builtin_adapter_metadata, register_builtin_adapters
from .bridge import AdapterBridge, AdapterHandle
from .metadata import AdapterMetadata, register_adapter_metadata
from .watcher import AdapterConfigWatcher

__all__ = [
    "AdapterBridge",
    "AdapterHandle",
    "AdapterMetadata",
    "register_adapter_metadata",
    "AdapterConfigWatcher",
    "register_builtin_adapters",
    "builtin_adapter_metadata",
]
