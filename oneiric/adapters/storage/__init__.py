"""Lazy-loaded storage adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.storage import SomeAdapter`` still works and
``import oneiric.adapters.storage`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "AzureBlobStorageAdapter",
    "AzureBlobStorageSettings",
    "GCSStorageAdapter",
    "GCSStorageSettings",
    "LocalStorageAdapter",
    "LocalStorageSettings",
    "S3StorageAdapter",
    "S3StorageSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.storage.azure import (
        AzureBlobStorageAdapter,
        AzureBlobStorageSettings,
    )
    from oneiric.adapters.storage.gcs import (
        GCSStorageAdapter,
        GCSStorageSettings,
    )
    from oneiric.adapters.storage.local import (
        LocalStorageAdapter,
        LocalStorageSettings,
    )
    from oneiric.adapters.storage.s3 import (
        S3StorageAdapter,
        S3StorageSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AzureBlobStorageAdapter": (
        "oneiric.adapters.storage.azure",
        "AzureBlobStorageAdapter",
    ),
    "AzureBlobStorageSettings": (
        "oneiric.adapters.storage.azure",
        "AzureBlobStorageSettings",
    ),
    "GCSStorageAdapter": ("oneiric.adapters.storage.gcs", "GCSStorageAdapter"),
    "GCSStorageSettings": ("oneiric.adapters.storage.gcs", "GCSStorageSettings"),
    "LocalStorageAdapter": ("oneiric.adapters.storage.local", "LocalStorageAdapter"),
    "LocalStorageSettings": ("oneiric.adapters.storage.local", "LocalStorageSettings"),
    "S3StorageAdapter": ("oneiric.adapters.storage.s3", "S3StorageAdapter"),
    "S3StorageSettings": ("oneiric.adapters.storage.s3", "S3StorageSettings"),
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
