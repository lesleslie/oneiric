"""Lazy-loaded dns adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.dns import SomeAdapter`` still works and
``import oneiric.adapters.dns`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "CloudflareDNSAdapter",
    "CloudflareDNSSettings",
    "GCDNSAdapter",
    "GCDNSSettings",
    "Route53DNSAdapter",
    "Route53DNSSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.dns.cloudflare import (
        CloudflareDNSAdapter,
        CloudflareDNSSettings,
    )
    from oneiric.adapters.dns.gcdns import (
        GCDNSAdapter,
        GCDNSSettings,
    )
    from oneiric.adapters.dns.route53 import (
        Route53DNSAdapter,
        Route53DNSSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "CloudflareDNSAdapter": ("oneiric.adapters.dns.cloudflare", "CloudflareDNSAdapter"),
    "CloudflareDNSSettings": (
        "oneiric.adapters.dns.cloudflare",
        "CloudflareDNSSettings",
    ),
    "GCDNSAdapter": ("oneiric.adapters.dns.gcdns", "GCDNSAdapter"),
    "GCDNSSettings": ("oneiric.adapters.dns.gcdns", "GCDNSSettings"),
    "Route53DNSAdapter": ("oneiric.adapters.dns.route53", "Route53DNSAdapter"),
    "Route53DNSSettings": ("oneiric.adapters.dns.route53", "Route53DNSSettings"),
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
