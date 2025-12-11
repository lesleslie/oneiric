"""Tests for AdapterBridge."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from oneiric.adapters.bridge import AdapterBridge, AdapterHandle
from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.runtime.activity import DomainActivity, DomainActivityStore

# Test fixtures


class MockAdapter:
    """Mock adapter for testing."""

    def __init__(self, name: str):
        self.name = name
        self.connected = True

    async def disconnect(self):
        self.connected = False


class CacheAdapterSettings(BaseModel):
    """Mock settings for cache adapter."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    timeout: int = 5


class TestAdapterHandle:
    """Test AdapterHandle dataclass."""

    def test_handle_fields(self):
        """AdapterHandle has all required fields."""
        instance = MockAdapter("redis")
        settings = {"host": "cache.example.com"}
        metadata = {"version": "7.0"}

        handle = AdapterHandle(
            category="cache",
            provider="redis",
            instance=instance,
            settings=settings,
            metadata=metadata,
        )

        assert handle.category == "cache"
        assert handle.provider == "redis"
        assert handle.instance is instance
        assert handle.settings == settings
        assert handle.metadata == metadata


class TestAdapterBridgeConstruction:
    """Test AdapterBridge initialization."""

    def test_bridge_initialization(self):
        """AdapterBridge initializes with required dependencies."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        bridge = AdapterBridge(resolver, lifecycle, settings)

        assert bridge.domain == "adapter"
        assert bridge.resolver is resolver
        assert bridge.lifecycle is lifecycle
        assert bridge.settings is settings
        assert bridge._settings_models == {}
        assert bridge._settings_cache == {}
        assert bridge._activity == {}

    def test_bridge_with_activity_store(self, tmp_path: Path):
        """AdapterBridge initializes with activity store."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.sqlite"
        activity_store = DomainActivityStore(store_path)

        bridge = AdapterBridge(
            resolver, lifecycle, settings, activity_store=activity_store
        )

        assert bridge._activity_store is activity_store


class TestAdapterBridgeSettings:
    """Test settings management in AdapterBridge."""

    def test_register_settings_model(self):
        """register_settings_model() registers Pydantic model for provider."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        bridge.register_settings_model("redis", CacheAdapterSettings)

        assert "redis" in bridge._settings_models
        assert bridge._settings_models["redis"] is CacheAdapterSettings

    def test_get_settings_with_model(self):
        """get_settings() parses raw settings using registered model."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            provider_settings={
                "redis": {"host": "cache.example.com", "port": 6380, "db": 2}
            }
        )
        bridge = AdapterBridge(resolver, lifecycle, settings)
        bridge.register_settings_model("redis", CacheAdapterSettings)

        parsed = bridge.get_settings("redis")

        assert isinstance(parsed, CacheAdapterSettings)
        assert parsed.host == "cache.example.com"
        assert parsed.port == 6380
        assert parsed.db == 2

    def test_get_settings_without_model(self):
        """get_settings() returns raw dict when no model registered."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            provider_settings={"memcached": {"servers": ["localhost:11211"]}}
        )
        bridge = AdapterBridge(resolver, lifecycle, settings)

        raw = bridge.get_settings("memcached")

        assert isinstance(raw, dict)
        assert raw == {"servers": ["localhost:11211"]}

    def test_get_settings_caching(self):
        """get_settings() caches parsed settings."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(provider_settings={"redis": {"host": "localhost"}})
        bridge = AdapterBridge(resolver, lifecycle, settings)
        bridge.register_settings_model("redis", CacheAdapterSettings)

        parsed1 = bridge.get_settings("redis")
        parsed2 = bridge.get_settings("redis")

        assert parsed1 is parsed2

    def test_update_settings_clears_cache(self):
        """update_settings() clears settings cache."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings1 = LayerSettings(provider_settings={"redis": {"host": "localhost"}})
        bridge = AdapterBridge(resolver, lifecycle, settings1)
        bridge.register_settings_model("redis", CacheAdapterSettings)

        parsed1 = bridge.get_settings("redis")
        assert parsed1.host == "localhost"

        settings2 = LayerSettings(
            provider_settings={"redis": {"host": "cache.example.com"}}
        )
        bridge.update_settings(settings2)

        parsed2 = bridge.get_settings("redis")
        assert parsed2.host == "cache.example.com"
        assert parsed1 is not parsed2


class TestAdapterBridgeUse:
    """Test AdapterBridge.use() for adapter activation."""

    @pytest.mark.asyncio
    async def test_use_simple_adapter(self):
        """use() activates and returns adapter in AdapterHandle."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
                metadata={"version": "7.0"},
            )
        )

        handle = await bridge.use("cache")

        assert isinstance(handle, AdapterHandle)
        assert handle.category == "cache"
        assert handle.provider == "redis"
        assert isinstance(handle.instance, MockAdapter)
        assert handle.instance.name == "redis"
        assert handle.metadata == {"version": "7.0"}

    @pytest.mark.asyncio
    async def test_use_with_explicit_provider(self):
        """use() respects explicit provider override."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockAdapter("memcached"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("cache", provider="memcached")

        assert handle.provider == "memcached"
        assert handle.instance.name == "memcached"

    @pytest.mark.asyncio
    async def test_use_with_config_selection(self):
        """use() uses configured selection from settings."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(selections={"cache": "redis"})
        bridge = AdapterBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockAdapter("memcached"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("cache")

        assert handle.provider == "redis"

    @pytest.mark.asyncio
    async def test_use_returns_cached_instance(self):
        """use() returns cached instance on second call."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        handle1 = await bridge.use("cache")
        handle2 = await bridge.use("cache")

        assert handle1.instance is handle2.instance

    @pytest.mark.asyncio
    async def test_use_with_force_reload(self):
        """use() creates new instance with force_reload=True."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MockAdapter(f"redis-{call_count}")

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=factory,
                source=CandidateSource.MANUAL,
            )
        )

        handle1 = await bridge.use("cache")
        assert handle1.instance.name == "redis-1"

        handle2 = await bridge.use("cache", force_reload=True)
        assert handle2.instance.name == "redis-2"
        assert handle1.instance is not handle2.instance

    @pytest.mark.asyncio
    async def test_use_fails_when_no_candidate(self):
        """use() raises LifecycleError when adapter not found."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        with pytest.raises(
            LifecycleError, match="No adapter candidate found for missing"
        ):
            await bridge.use("missing")

    @pytest.mark.asyncio
    async def test_use_includes_provider_settings(self):
        """use() includes provider settings in handle."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            provider_settings={"redis": {"host": "cache.example.com", "port": 6380}}
        )
        bridge = AdapterBridge(resolver, lifecycle, settings)
        bridge.register_settings_model("redis", CacheAdapterSettings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("cache")

        assert isinstance(handle.settings, CacheAdapterSettings)
        assert handle.settings.host == "cache.example.com"
        assert handle.settings.port == 6380

    @pytest.mark.asyncio
    async def test_use_rejected_when_paused(self, tmp_path: Path):
        """use() raises when adapter is paused."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store = DomainActivityStore(tmp_path / "activity.sqlite")
        bridge = AdapterBridge(resolver, lifecycle, settings, activity_store=store)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        store.set("adapter", "cache", DomainActivity(paused=True))

        with pytest.raises(LifecycleError, match="adapter:cache is paused"):
            await bridge.use("cache")

    @pytest.mark.asyncio
    async def test_use_rejected_when_draining(self, tmp_path: Path):
        """use() raises when adapter is draining."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store = DomainActivityStore(tmp_path / "activity.sqlite")
        bridge = AdapterBridge(resolver, lifecycle, settings, activity_store=store)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        store.set("adapter", "cache", DomainActivity(draining=True))

        with pytest.raises(LifecycleError, match="adapter:cache is draining"):
            await bridge.use("cache")


class TestAdapterBridgeListingMethods:
    """Test AdapterBridge candidate listing methods."""

    def test_active_candidates(self):
        """active_candidates() returns active adapter candidates."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        active = bridge.active_candidates()

        assert len(active) == 1
        assert active[0].domain == "adapter"
        assert active[0].key == "cache"

    def test_shadowed_candidates(self):
        """shadowed_candidates() returns shadowed adapter candidates."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(selections={"cache": "redis"})
        bridge = AdapterBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        shadowed = bridge.shadowed_candidates()

        assert len(shadowed) == 1
        assert shadowed[0].provider == "memcached"

    def test_explain(self):
        """explain() returns resolution explanation for adapter category."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        explanation = bridge.explain("cache")

        assert isinstance(explanation, dict)
        assert explanation["domain"] == "adapter"
        assert explanation["key"] == "cache"
        assert len(explanation["ordered"]) == 1
        assert explanation["ordered"][0]["provider"] == "redis"


class TestAdapterBridgeActivity:
    """Test AdapterBridge activity state management."""

    def test_activity_state_default(self):
        """activity_state() returns default state for new category."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        state = bridge.activity_state("cache")

        assert isinstance(state, DomainActivity)
        assert not state.paused
        assert not state.draining

    def test_set_paused(self):
        """set_paused() updates pause state for adapter."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        state = bridge.set_paused("cache", True, note="cache maintenance")

        assert state.paused is True
        assert state.note == "cache maintenance"

    def test_set_paused_resume(self):
        """set_paused(False) resumes paused adapter."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        bridge.set_paused("cache", True, note="maintenance")
        state = bridge.set_paused("cache", False)

        assert state.paused is False

    def test_set_draining(self):
        """set_draining() updates drain state for adapter."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        state = bridge.set_draining("cache", True, note="draining connections")

        assert state.draining is True
        assert state.note == "draining connections"

    def test_set_draining_clear(self):
        """set_draining(False) clears drain state."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        bridge.set_draining("cache", True)
        state = bridge.set_draining("cache", False)

        assert state.draining is False

    def test_activity_snapshot(self):
        """activity_snapshot() returns all adapter activity states."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        bridge.set_paused("cache", True)
        bridge.set_draining("database", True)

        snapshot = bridge.activity_snapshot()

        assert "cache" in snapshot
        assert "database" in snapshot
        assert snapshot["cache"].paused is True
        assert snapshot["database"].draining is True

    def test_activity_with_store(self, tmp_path: Path):
        """Activity persists to external store when provided."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.sqlite"
        activity_store = DomainActivityStore(store_path)

        bridge = AdapterBridge(
            resolver, lifecycle, settings, activity_store=activity_store
        )

        bridge.set_paused("cache", True, note="maintenance")

        assert store_path.exists()
        persisted = DomainActivityStore(store_path)
        state = persisted.get("adapter", "cache")
        assert state.paused is True
        assert state.note == "maintenance"

    def test_activity_loads_from_store(self, tmp_path: Path):
        """Activity loads from store on initialization."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.sqlite"

        primer = DomainActivityStore(store_path)
        primer.set("adapter", "cache", DomainActivity(paused=True, note="existing"))

        activity_store = DomainActivityStore(store_path)
        bridge = AdapterBridge(
            resolver, lifecycle, settings, activity_store=activity_store
        )

        state = bridge.activity_state("cache")
        assert state.paused is True
        assert state.note == "existing"


class TestAdapterBridgeIntegration:
    """Integration tests for AdapterBridge."""

    @pytest.mark.asyncio
    async def test_full_adapter_lifecycle(self):
        """Full lifecycle: register, use, reload, pause."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            selections={"cache": "redis"},
            provider_settings={"redis": {"host": "localhost", "port": 6379}},
        )
        bridge = AdapterBridge(resolver, lifecycle, settings)
        bridge.register_settings_model("redis", CacheAdapterSettings)

        # Register adapter
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("redis"),
                source=CandidateSource.MANUAL,
                metadata={"version": "7.0"},
            )
        )

        # Use adapter
        handle1 = await bridge.use("cache")
        assert handle1.provider == "redis"
        assert handle1.settings.host == "localhost"

        # Use again (cached)
        handle2 = await bridge.use("cache")
        assert handle1.instance is handle2.instance

        # Force reload
        handle3 = await bridge.use("cache", force_reload=True)
        assert handle1.instance is not handle3.instance

        # Pause adapter
        state = bridge.set_paused("cache", True, note="maintenance")
        assert state.paused is True

    @pytest.mark.asyncio
    async def test_multiple_adapter_categories(self):
        """Bridge handles multiple adapter categories independently."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings)

        # Register cache adapter
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockAdapter("cache"),
                source=CandidateSource.MANUAL,
            )
        )

        # Register database adapter
        resolver.register(
            Candidate(
                domain="adapter",
                key="database",
                provider="postgres",
                factory=lambda: MockAdapter("database"),
                source=CandidateSource.MANUAL,
            )
        )

        # Use both
        cache_handle = await bridge.use("cache")
        db_handle = await bridge.use("database")

        assert cache_handle.category == "cache"
        assert db_handle.category == "database"
        assert cache_handle.instance is not db_handle.instance
