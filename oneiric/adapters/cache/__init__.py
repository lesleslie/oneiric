"""Lazy-loaded cache adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.cache import SomeAdapter`` still works and
``import oneiric.adapters.cache`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "MemoryCacheAdapter",
    "MemoryCacheSettings",
    "MultiTierCacheAdapter",
    "MultiTierCacheSettings",
    "PersistentKVCacheAdapter",
    "PersistentKVCacheSettings",
    "RedisCacheAdapter",
    "RedisCacheSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.cache.memory import (
        MemoryCacheAdapter,
        MemoryCacheSettings,
    )
    from oneiric.adapters.cache.multitier import (
        MultiTierCacheAdapter,
        MultiTierCacheSettings,
    )
    from oneiric.adapters.cache.persistent_kv import (
        PersistentKVCacheAdapter,
        PersistentKVCacheSettings,
    )
    from oneiric.adapters.cache.redis import (
        RedisCacheAdapter,
        RedisCacheSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "MemoryCacheAdapter": ("oneiric.adapters.cache.memory", "MemoryCacheAdapter"),
    "MemoryCacheSettings": ("oneiric.adapters.cache.memory", "MemoryCacheSettings"),
    "MultiTierCacheAdapter": (
        "oneiric.adapters.cache.multitier",
        "MultiTierCacheAdapter",
    ),
    "MultiTierCacheSettings": (
        "oneiric.adapters.cache.multitier",
        "MultiTierCacheSettings",
    ),
    "PersistentKVCacheAdapter": (
        "oneiric.adapters.cache.persistent_kv",
        "PersistentKVCacheAdapter",
    ),
    "PersistentKVCacheSettings": (
        "oneiric.adapters.cache.persistent_kv",
        "PersistentKVCacheSettings",
    ),
    "RedisCacheAdapter": ("oneiric.adapters.cache.redis", "RedisCacheAdapter"),
    "RedisCacheSettings": ("oneiric.adapters.cache.redis", "RedisCacheSettings"),
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported adapter on first attribute access (PEP 562)."""
    from oneiric.adapters._lazy import resolve_lazy_export

    value = resolve_lazy_export(__name__, name, _LAZY_EXPORTS)
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
