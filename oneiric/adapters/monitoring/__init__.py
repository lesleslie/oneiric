"""Lazy-loaded monitoring adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.monitoring import SomeAdapter`` still works and
``import oneiric.adapters.monitoring`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "LogfireMonitoringAdapter",
    "LogfireMonitoringSettings",
    "NetdataMonitoringAdapter",
    "NetdataMonitoringSettings",
    "OTLPObservabilityAdapter",
    "OTLPObservabilitySettings",
    "SentryMonitoringAdapter",
    "SentryMonitoringSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.monitoring.logfire import (
        LogfireMonitoringAdapter,
        LogfireMonitoringSettings,
    )
    from oneiric.adapters.monitoring.netdata import (
        NetdataMonitoringAdapter,
        NetdataMonitoringSettings,
    )
    from oneiric.adapters.monitoring.otlp import (
        OTLPObservabilityAdapter,
        OTLPObservabilitySettings,
    )
    from oneiric.adapters.monitoring.sentry import (
        SentryMonitoringAdapter,
        SentryMonitoringSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "LogfireMonitoringAdapter": (
        "oneiric.adapters.monitoring.logfire",
        "LogfireMonitoringAdapter",
    ),
    "LogfireMonitoringSettings": (
        "oneiric.adapters.monitoring.logfire",
        "LogfireMonitoringSettings",
    ),
    "NetdataMonitoringAdapter": (
        "oneiric.adapters.monitoring.netdata",
        "NetdataMonitoringAdapter",
    ),
    "NetdataMonitoringSettings": (
        "oneiric.adapters.monitoring.netdata",
        "NetdataMonitoringSettings",
    ),
    "OTLPObservabilityAdapter": (
        "oneiric.adapters.monitoring.otlp",
        "OTLPObservabilityAdapter",
    ),
    "OTLPObservabilitySettings": (
        "oneiric.adapters.monitoring.otlp",
        "OTLPObservabilitySettings",
    ),
    "SentryMonitoringAdapter": (
        "oneiric.adapters.monitoring.sentry",
        "SentryMonitoringAdapter",
    ),
    "SentryMonitoringSettings": (
        "oneiric.adapters.monitoring.sentry",
        "SentryMonitoringSettings",
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
