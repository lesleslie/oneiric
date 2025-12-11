"""DuckDB database adapter with lifecycle integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class DuckDBDatabaseSettings(BaseModel):
    """Configuration for the DuckDB adapter."""

    database_url: str = Field(
        default="duckdb:///data/app.duckdb",
        description="DuckDB connection URL (duckdb:// for sync, duckdb+async:// for async)",
    )
    read_only: bool = Field(
        default=False, description="Open database in read-only mode"
    )
    threads: int | None = Field(
        default=None, description="Number of threads for query execution"
    )
    pragmas: dict[str, str | int | float] = Field(
        default_factory=dict,
        description="DuckDB PRAGMA settings (e.g., {'memory_limit': '4GB'})",
    )
    extensions: list[str] = Field(
        default_factory=list,
        description="DuckDB extensions to install and load (e.g., ['httpfs', 'postgres_scanner'])",
    )
    temp_directory: str | None = Field(
        default=None, description="Temporary directory for spill-to-disk"
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Validate that database URL starts with duckdb:// or duckdb+async://."""
        if not value.startswith(("duckdb://", "duckdb+async://")):
            raise ValueError(
                "Database URL must start with duckdb:// or duckdb+async://"
            )
        return value

    @property
    def database_path(self) -> Path | None:
        """Extract database path from URL."""
        # Parse URL to get path
        if ":///" in self.database_url:
            path_part = self.database_url.split("///", 1)[1]
            # Remove query parameters
            if "?" in path_part:
                path_part = path_part.split("?")[0]
            if path_part and path_part != ":memory:":
                return Path(path_part)
        return None


class DuckDBDatabaseAdapter:
    """DuckDB adapter optimized for analytical workloads and in-memory processing."""

    metadata = AdapterMetadata(
        category="database",
        provider="duckdb",
        factory="oneiric.adapters.database.duckdb:DuckDBDatabaseAdapter",
        capabilities=[
            "sql",
            "analytics",
            "columnar",
            "in_memory",
            "embedded",
            "extensions",
        ],
        stack_level=10,
        priority=100,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=False,
        settings_model=DuckDBDatabaseSettings,
    )

    def __init__(self, settings: DuckDBDatabaseSettings) -> None:
        self._settings = settings
        self._conn: Any | None = None
        self._logger = get_logger("adapter.database.duckdb").bind(
            domain="adapter",
            key="database",
            provider="duckdb",
        )

    async def init(self) -> None:
        """Initialize DuckDB connection and apply configuration."""
        try:
            import duckdb
        except ImportError as exc:
            raise LifecycleError("duckdb-import-failed: pip install duckdb") from exc

        # Ensure parent directory exists for file-based databases
        db_path = self._settings.database_path
        if db_path:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._logger.debug("duckdb-database-path", path=str(db_path))

        # Extract database path from URL
        database = ":memory:"
        if ":///" in self._settings.database_url:
            path_part = self._settings.database_url.split("///", 1)[1]
            if "?" in path_part:
                path_part = path_part.split("?")[0]
            database = path_part or ":memory:"

        # Connect to DuckDB
        try:
            self._conn = duckdb.connect(
                database=database,
                read_only=self._settings.read_only,
            )
            self._logger.debug(
                "duckdb-connected",
                database=database,
                read_only=self._settings.read_only,
            )
        except Exception as exc:
            raise LifecycleError(f"duckdb-connection-failed: {exc}") from exc

        # Apply configuration
        await self._set_threads()
        await self._apply_pragmas()
        await self._install_extensions()
        await self._set_temp_directory()

        self._logger.info("duckdb-adapter-init-success", database=database)

    async def _set_threads(self) -> None:
        """Set number of threads for query execution."""
        if self._settings.threads is None:
            return

        conn = self._ensure_conn()
        threads = int(self._settings.threads)
        conn.execute(f"PRAGMA threads={threads}")
        self._logger.debug("duckdb-threads-set", threads=threads)

    async def _apply_pragmas(self) -> None:
        """Apply PRAGMA settings."""
        if not self._settings.pragmas:
            return

        conn = self._ensure_conn()
        for pragma, value in self._settings.pragmas.items():
            # Convert value to string
            value_str = value if isinstance(value, str) else str(value)

            # Check if value is numeric
            numeric_check = value_str.lstrip("-+").replace(".", "", 1).isdigit()
            if isinstance(value, (int, float)) or numeric_check:
                clause = value_str
            else:
                # Escape single quotes in string values
                escaped = value_str.replace("'", "''")
                clause = f"'{escaped}'"

            conn.execute(f"PRAGMA {pragma}={clause}")
            self._logger.debug("duckdb-pragma-applied", pragma=pragma, value=clause)

    async def _install_extensions(self) -> None:
        """Install and load DuckDB extensions."""
        if not self._settings.extensions or self._settings.read_only:
            return

        conn = self._ensure_conn()
        for extension in self._settings.extensions:
            # Sanitize extension name
            safe_ext = extension.replace('"', "").replace("'", "")

            try:
                conn.execute(f"INSTALL {safe_ext}")
                conn.execute(f"LOAD {safe_ext}")
                self._logger.debug("duckdb-extension-loaded", extension=safe_ext)
            except Exception as exc:
                self._logger.warning(
                    "duckdb-extension-failed", extension=safe_ext, error=str(exc)
                )

    async def _set_temp_directory(self) -> None:
        """Set temporary directory for spill-to-disk."""
        if not self._settings.temp_directory:
            return

        conn = self._ensure_conn()
        conn.execute(f"SET temp_directory='{self._settings.temp_directory}'")
        self._logger.debug(
            "duckdb-temp-directory-set", temp_directory=self._settings.temp_directory
        )

    async def health(self) -> bool:
        """Check if DuckDB connection is healthy."""
        if not self._conn:
            return False

        try:
            conn = self._ensure_conn()
            result = conn.execute("SELECT 1").fetchone()
            return result is not None and result[0] == 1
        except Exception as exc:
            self._logger.warning("duckdb-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Cleanup DuckDB connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception as exc:
                self._logger.warning("duckdb-cleanup-warning", error=str(exc))
            finally:
                self._conn = None

        self._logger.info("duckdb-cleanup-complete")

    async def execute(self, query: str, *args: Any) -> int:
        """Execute a SQL query and return number of affected rows."""
        conn = self._ensure_conn()

        try:
            if args:
                result = conn.execute(query, args)
            else:
                result = conn.execute(query)

            # DuckDB doesn't always provide rowcount, try to get it
            rowcount = 0
            try:
                # For INSERT/UPDATE/DELETE, DuckDB returns affected rows
                rowcount = len(result.fetchall()) if result.description else 0
            except Exception:
                rowcount = 0

            return rowcount
        except Exception as exc:
            self._logger.exception("duckdb-execute-failed", query=query, error=str(exc))
            raise LifecycleError(f"duckdb-execute-failed: {exc}") from exc

    async def fetch_all(self, query: str, *args: Any) -> list[tuple[Any, ...]]:
        """Execute a SQL query and fetch all rows."""
        conn = self._ensure_conn()

        try:
            if args:
                result = conn.execute(query, args)
            else:
                result = conn.execute(query)

            rows = result.fetchall()
            return rows
        except Exception as exc:
            self._logger.exception(
                "duckdb-fetch-all-failed", query=query, error=str(exc)
            )
            raise LifecycleError(f"duckdb-fetch-all-failed: {exc}") from exc

    async def fetch_one(self, query: str, *args: Any) -> tuple[Any, ...] | None:
        """Execute a SQL query and fetch one row."""
        conn = self._ensure_conn()

        try:
            if args:
                result = conn.execute(query, args)
            else:
                result = conn.execute(query)

            row = result.fetchone()
            return row
        except Exception as exc:
            self._logger.exception(
                "duckdb-fetch-one-failed", query=query, error=str(exc)
            )
            raise LifecycleError(f"duckdb-fetch-one-failed: {exc}") from exc

    async def fetch_df(self, query: str, *args: Any) -> Any:
        """Execute a SQL query and return results as a pandas DataFrame."""
        conn = self._ensure_conn()

        try:
            if args:
                result = conn.execute(query, args)
            else:
                result = conn.execute(query)

            # DuckDB natively returns DataFrames via df() method
            df = result.df()
            return df
        except ImportError as exc:
            raise LifecycleError("duckdb-pandas-missing: pip install pandas") from exc
        except Exception as exc:
            self._logger.exception(
                "duckdb-fetch-df-failed", query=query, error=str(exc)
            )
            raise LifecycleError(f"duckdb-fetch-df-failed: {exc}") from exc

    async def fetch_arrow(self, query: str, *args: Any) -> Any:
        """Execute a SQL query and return results as an Arrow table."""
        conn = self._ensure_conn()

        try:
            if args:
                result = conn.execute(query, args)
            else:
                result = conn.execute(query)

            # DuckDB natively returns Arrow tables via arrow() method
            arrow_table = result.arrow()
            return arrow_table
        except ImportError as exc:
            raise LifecycleError("duckdb-arrow-missing: pip install pyarrow") from exc
        except Exception as exc:
            self._logger.exception(
                "duckdb-fetch-arrow-failed", query=query, error=str(exc)
            )
            raise LifecycleError(f"duckdb-fetch-arrow-failed: {exc}") from exc

    def _ensure_conn(self) -> Any:
        """Ensure connection is initialized."""
        if not self._conn:
            raise LifecycleError("duckdb-connection-not-initialized")
        return self._conn

    @property
    def connection(self) -> Any:
        """Get the underlying DuckDB connection."""
        return self._ensure_conn()
