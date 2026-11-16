"""Adapter families, the resolution bridge, and the metadata registry.

The re-exports below are **lazy** (PEP 562). Importing this package used
to execute ``bootstrap`` -> ``core.config`` -> ``mcp.config`` -> ``mcp``
and the whole resolution stack behind it, which measured ~3 s.

That cost sat on somebody else's critical path. A Claude Code hook that
publishes one event per tool call imports a single concrete adapter
(``oneiric.adapters.queue.redis_streams``) and paid the full tax, because
Python executes every parent package's ``__init__`` on the way down. The
hook therefore blocked each tool call for ~3.4 s before the model could
see the tool result.

Resolution is now deferred to first attribute access, so
``import oneiric.adapters`` is cheap and the heavy modules load only when
something actually uses them. Import *order* changes, not behaviour: the
re-exported names still resolve to the same objects, and no module here
has an import-time side effect (``register_builtin_adapters`` is an
explicit call, not a side effect of importing this package).

Refs: ``docs/adr/0004-lazy-adapter-package-imports.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "AdapterBridge",
    "AdapterConfigWatcher",
    "AdapterHandle",
    "AdapterMetadata",
    "builtin_adapter_metadata",
    "register_adapter_metadata",
    "register_builtin_adapters",
]


if TYPE_CHECKING:
    from oneiric.adapters.bootstrap import (
        builtin_adapter_metadata,
        register_builtin_adapters,
    )
    from oneiric.adapters.bridge import AdapterBridge, AdapterHandle
    from oneiric.adapters.metadata import AdapterMetadata, register_adapter_metadata
    from oneiric.adapters.watcher import AdapterConfigWatcher


_LAZY_EXPORTS = {
    "builtin_adapter_metadata": (
        "oneiric.adapters.bootstrap",
        "builtin_adapter_metadata",
    ),
    "register_builtin_adapters": (
        "oneiric.adapters.bootstrap",
        "register_builtin_adapters",
    ),
    "AdapterBridge": ("oneiric.adapters.bridge", "AdapterBridge"),
    "AdapterHandle": ("oneiric.adapters.bridge", "AdapterHandle"),
    "AdapterMetadata": ("oneiric.adapters.metadata", "AdapterMetadata"),
    "register_adapter_metadata": (
        "oneiric.adapters.metadata",
        "register_adapter_metadata",
    ),
    "AdapterConfigWatcher": ("oneiric.adapters.watcher", "AdapterConfigWatcher"),
}

#: Submodules that stay reachable as attributes of this package, so
#: ``oneiric.adapters.bootstrap`` keeps working after a bare
#: ``import oneiric.adapters``.
_LAZY_SUBMODULES = ("bootstrap", "bridge", "metadata", "watcher")


def __getattr__(name: str):
    """Lazily resolve submodule exports on first attribute access.

    Keeps ``from oneiric.adapters import AdapterBridge`` working while
    leaving the resolution stack unloaded until something asks for it.
    """
    import importlib

    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr_name = target
    module = importlib.import_module(module_path)
    value = getattr(module, attr_name)
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports to ``dir()`` and tab-completion."""
    return sorted(set(__all__) | set(_LAZY_SUBMODULES))
