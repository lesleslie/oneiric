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

    asyncpg = pytest.importorskip("asyncpg")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    # Try to connect first, skip if not available
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host="localhost",
                port=5432,
                user="postgres",
                password="postgres",
                database="otel_test",
            ),
            timeout=2.0,
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


# ---------------------------------------------------------------------------
# Shared fixtures for the 14-module comprehensive test suite
# (Added 2026-06-05; see /Users/les/.claude/plans/moonlit-fluttering-naur.md)
#
# These are reused by tests/{core,domains,remote,runtime}/test_*_comprehensive.py.
# Subagents authoring new test files must NOT redefine any of these.
# ---------------------------------------------------------------------------


@pytest.fixture
def layer_settings():
    """Fresh LayerSettings with empty selections — used by domain-bridge tests."""
    from oneiric.core.config import LayerSettings

    return LayerSettings(selections={}, provider_settings={})


@pytest.fixture
def bridge_activity_store(tmp_path):
    """In-memory DomainActivityStore for domain-bridge activity tests.

    Backed by a per-test sqlite file under tmp_path so each test gets isolation.
    """
    from oneiric.runtime.activity import DomainActivityStore

    return DomainActivityStore(tmp_path / "activity.db")


@pytest.fixture
def checkpoint_store(tmp_path: Path):
    """Fresh WorkflowCheckpointStore backed by a per-test sqlite db."""
    from oneiric.runtime.checkpoints import WorkflowCheckpointStore

    return WorkflowCheckpointStore(tmp_path / "checkpoints.db")


@pytest.fixture
def event_envelope_factory():
    """The create_event_envelope factory — used to build deterministic envelopes."""
    from oneiric.runtime.events import create_event_envelope

    return create_event_envelope


@pytest.fixture
def dummy_task_handler():
    """Async-callable satisfying TaskHandlerProtocol (run(payload) -> result)."""
    from typing import Any

    class _DummyTaskHandler:
        async def run(self, payload: dict[str, Any] | None = None) -> str:
            return f"task-ok:{payload}"

    return _DummyTaskHandler()


@pytest.fixture
def dummy_event_handler():
    """Async-callable satisfying EventHandlerProtocol (handle(envelope) -> None)."""
    from oneiric.runtime.events import EventEnvelope

    class _DummyEventHandler:
        async def handle(self, envelope: EventEnvelope) -> None:
            return None

    return _DummyEventHandler()


@pytest.fixture
def reset_remote_breakers():
    """Snap and restore the module-level _REMOTE_BREAKERS dict around a test.

    Mandatory for any test that exercises oneiric.remote.loader's circuit breakers
    — without this, breakers cache across tests and produce order-dependent results.
    """
    from oneiric.remote import loader as rl

    saved = rl._REMOTE_BREAKERS.copy()
    yield
    rl._REMOTE_BREAKERS.clear()
    rl._REMOTE_BREAKERS.update(saved)
