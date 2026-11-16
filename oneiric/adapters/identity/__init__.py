"""Lazy-loaded identity adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.identity import SomeAdapter`` still works and
``import oneiric.adapters.identity`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "Auth0IdentityAdapter",
    "Auth0IdentitySettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.identity.auth0 import (
        Auth0IdentityAdapter,
        Auth0IdentitySettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "Auth0IdentityAdapter": ("oneiric.adapters.identity.auth0", "Auth0IdentityAdapter"),
    "Auth0IdentitySettings": (
        "oneiric.adapters.identity.auth0",
        "Auth0IdentitySettings",
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
