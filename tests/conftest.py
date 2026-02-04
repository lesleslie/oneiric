"""Shared pytest fixtures and configuration for Oneiric tests."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from oneiric.core.config import RemoteSourceConfig
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Candidate, Resolver


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def cache_dir(temp_dir: Path) -> Path:
    """Create a cache directory for tests."""
    cache = temp_dir / "cache"
    cache.mkdir()
    return cache


@pytest.fixture
def config_dir(temp_dir: Path) -> Path:
    """Create a config directory for tests."""
    config = temp_dir / "config"
    config.mkdir()
    return config


@pytest.fixture
def resolver() -> Resolver:
    """Create a fresh Resolver instance."""
    return Resolver()


@pytest.fixture
def lifecycle_manager(resolver: Resolver, temp_dir: Path) -> LifecycleManager:
    """Create a LifecycleManager instance."""
    snapshot_path = temp_dir / "lifecycle_status.json"
    return LifecycleManager(resolver, status_snapshot_path=str(snapshot_path))


@pytest.fixture
def sample_candidate() -> Candidate:
    """Create a sample Candidate for testing."""
    return Candidate(
        domain="adapter",
        key="test-cache",
        provider="redis",
        factory=lambda: {"type": "redis"},
        priority=10,
        stack_level=5,
        description="Test Redis cache adapter",
    )


@pytest.fixture
def remote_config(cache_dir: Path) -> RemoteSourceConfig:
    """Create a RemoteSourceConfig for testing."""
    return RemoteSourceConfig(
        enabled=True,
        manifest_url="https://example.com/manifest.yaml",
        cache_dir=str(cache_dir),
        verify_tls=True,
    )


# Security test fixtures
@pytest.fixture
def allowed_factory() -> str:
    """Factory string that should pass validation."""
    return "oneiric.demo:DemoAdapter"


@pytest.fixture
def blocked_factory() -> str:
    """Factory string that should be blocked (os.system)."""
    return "os:system"


@pytest.fixture
def malformed_factory() -> str:
    """Malformed factory string."""
    return "invalid-no-colon"


@pytest.fixture
def path_traversal_key() -> str:
    """Key with path traversal attempt."""
    return "../../evil"


@pytest.fixture
def valid_key() -> str:
    """Valid component key."""
    return "my-component"


# OTel storage test fixtures
@pytest.fixture
async def otel_db_session():
    """Create async database session for testing OTel migrations.

    This fixture requires a running PostgreSQL instance with pgvector extension:
    - Database: otel_test
    - User: postgres
    - Password: postgres
    - Host: localhost
    - Port: 5432

    Tests using this fixture should be marked with @pytest.mark.integration

    Skip if database is not available.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    import asyncpg

    # Try to connect first, skip if not available
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host="localhost",
                port=5432,
                user="postgres",
                password="postgres",
                database="otel_test"
            ),
            timeout=2.0
        )
        await conn.close()
    except Exception:
        pytest.skip("PostgreSQL database not available - skipping integration test")

    engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/otel_test"
    )
    async_session = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()
