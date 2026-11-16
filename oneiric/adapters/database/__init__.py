"""Lazy-loaded database adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.database import SomeAdapter`` still works and
``import oneiric.adapters.database`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "DuckDBDatabaseAdapter",
    "DuckDBDatabaseSettings",
    "MySQLDatabaseAdapter",
    "MySQLDatabaseSettings",
    "PostgresDatabaseAdapter",
    "PostgresDatabaseSettings",
    "SQLiteDatabaseAdapter",
    "SQLiteDatabaseSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.database.duckdb import (
        DuckDBDatabaseAdapter,
        DuckDBDatabaseSettings,
    )
    from oneiric.adapters.database.mysql import (
        MySQLDatabaseAdapter,
        MySQLDatabaseSettings,
    )
    from oneiric.adapters.database.postgres import (
        PostgresDatabaseAdapter,
        PostgresDatabaseSettings,
    )
    from oneiric.adapters.database.sqlite import (
        SQLiteDatabaseAdapter,
        SQLiteDatabaseSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "DuckDBDatabaseAdapter": (
        "oneiric.adapters.database.duckdb",
        "DuckDBDatabaseAdapter",
    ),
    "DuckDBDatabaseSettings": (
        "oneiric.adapters.database.duckdb",
        "DuckDBDatabaseSettings",
    ),
    "MySQLDatabaseAdapter": ("oneiric.adapters.database.mysql", "MySQLDatabaseAdapter"),
    "MySQLDatabaseSettings": (
        "oneiric.adapters.database.mysql",
        "MySQLDatabaseSettings",
    ),
    "PostgresDatabaseAdapter": (
        "oneiric.adapters.database.postgres",
        "PostgresDatabaseAdapter",
    ),
    "PostgresDatabaseSettings": (
        "oneiric.adapters.database.postgres",
        "PostgresDatabaseSettings",
    ),
    "SQLiteDatabaseAdapter": (
        "oneiric.adapters.database.sqlite",
        "SQLiteDatabaseAdapter",
    ),
    "SQLiteDatabaseSettings": (
        "oneiric.adapters.database.sqlite",
        "SQLiteDatabaseSettings",
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
