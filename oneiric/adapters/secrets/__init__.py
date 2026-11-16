"""Lazy-loaded secrets adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.secrets import SomeAdapter`` still works and
``import oneiric.adapters.secrets`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "AWSSecretManagerAdapter",
    "AWSSecretManagerSettings",
    "EnvSecretAdapter",
    "EnvSecretSettings",
    "FileSecretAdapter",
    "FileSecretSettings",
    "GCPSecretManagerAdapter",
    "GCPSecretManagerSettings",
    "InfisicalSecretAdapter",
    "InfisicalSecretSettings",
    "KeyringSecretAdapter",
    "KeyringSecretSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.secrets.aws import (
        AWSSecretManagerAdapter,
        AWSSecretManagerSettings,
    )
    from oneiric.adapters.secrets.env import (
        EnvSecretAdapter,
        EnvSecretSettings,
    )
    from oneiric.adapters.secrets.file import (
        FileSecretAdapter,
        FileSecretSettings,
    )
    from oneiric.adapters.secrets.gcp import (
        GCPSecretManagerAdapter,
        GCPSecretManagerSettings,
    )
    from oneiric.adapters.secrets.infisical import (
        InfisicalSecretAdapter,
        InfisicalSecretSettings,
    )
    from oneiric.adapters.secrets.keyring import (
        KeyringSecretAdapter,
        KeyringSecretSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AWSSecretManagerAdapter": (
        "oneiric.adapters.secrets.aws",
        "AWSSecretManagerAdapter",
    ),
    "AWSSecretManagerSettings": (
        "oneiric.adapters.secrets.aws",
        "AWSSecretManagerSettings",
    ),
    "EnvSecretAdapter": ("oneiric.adapters.secrets.env", "EnvSecretAdapter"),
    "EnvSecretSettings": ("oneiric.adapters.secrets.env", "EnvSecretSettings"),
    "FileSecretAdapter": ("oneiric.adapters.secrets.file", "FileSecretAdapter"),
    "FileSecretSettings": ("oneiric.adapters.secrets.file", "FileSecretSettings"),
    "GCPSecretManagerAdapter": (
        "oneiric.adapters.secrets.gcp",
        "GCPSecretManagerAdapter",
    ),
    "GCPSecretManagerSettings": (
        "oneiric.adapters.secrets.gcp",
        "GCPSecretManagerSettings",
    ),
    "InfisicalSecretAdapter": (
        "oneiric.adapters.secrets.infisical",
        "InfisicalSecretAdapter",
    ),
    "InfisicalSecretSettings": (
        "oneiric.adapters.secrets.infisical",
        "InfisicalSecretSettings",
    ),
    "KeyringSecretAdapter": (
        "oneiric.adapters.secrets.keyring",
        "KeyringSecretAdapter",
    ),
    "KeyringSecretSettings": (
        "oneiric.adapters.secrets.keyring",
        "KeyringSecretSettings",
    ),
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
