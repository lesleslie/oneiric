"""Tests for DomainBridge base class."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.domains.base import DomainBridge, DomainHandle
from oneiric.runtime.activity import DomainActivity, DomainActivityStore

# Test fixtures and helpers


class MockComponent:
    """Mock component for testing."""

    def __init__(self, name: str):
        self.name = name
        self.active = True

    async def cleanup(self):
        self.active = False


class MockProviderSettings(BaseModel):
    """Mock settings model for provider configuration."""

    host: str = "localhost"
    port: int = 8080
    timeout: int = 30


class TestDomainHandle:
    """Test DomainHandle dataclass."""

    def test_handle_fields(self):
        """DomainHandle has all required fields."""
        instance = MockComponent("test")
        metadata = {"version": "1.0.0"}
        settings = {"host": "localhost"}

        handle = DomainHandle(
            domain="service",
            key="api",
            provider="fastapi",
            instance=instance,
            metadata=metadata,
            settings=settings,
        )

        assert handle.domain == "service"
        assert handle.key == "api"
        assert handle.provider == "fastapi"
        assert handle.instance is instance
        assert handle.metadata == metadata
        assert handle.settings == settings


class TestDomainBridgeConstruction:
    """Test DomainBridge initialization."""

    def test_bridge_initialization(self):
        """DomainBridge initializes with required dependencies."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        bridge = DomainBridge(
            domain="service",
            resolver=resolver,
            lifecycle=lifecycle,
            settings=settings,
        )

        assert bridge.domain == "service"
        assert bridge.resolver is resolver
        assert bridge.lifecycle is lifecycle
        assert bridge.settings is settings
        assert bridge._settings_models == {}
        assert bridge._settings_cache == {}
        assert bridge._activity == {}

    def test_bridge_with_activity_store(self, tmp_path: Path):
        """DomainBridge initializes with activity store."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.sqlite"
        activity_store = DomainActivityStore(store_path)

        bridge = DomainBridge(
            domain="service",
            resolver=resolver,
            lifecycle=lifecycle,
            settings=settings,
            activity_store=activity_store,
        )

        assert bridge._activity_store is activity_store


class TestDomainBridgeSettings:
    """Test settings management in DomainBridge."""

    def test_register_settings_model(self):
        """register_settings_model() registers Pydantic model for provider."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        bridge.register_settings_model("fastapi", MockProviderSettings)

        assert "fastapi" in bridge._settings_models
        assert bridge._settings_models["fastapi"] is MockProviderSettings

    def test_get_settings_with_model(self):
        """get_settings() parses raw settings using registered model."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            provider_settings={
                "fastapi": {"host": "api.example.com", "port": 443, "timeout": 60}
            }
        )
        bridge = DomainBridge("service", resolver, lifecycle, settings)
        bridge.register_settings_model("fastapi", MockProviderSettings)

        parsed = bridge.get_settings("fastapi")

        assert isinstance(parsed, MockProviderSettings)
        assert parsed.host == "api.example.com"
        assert parsed.port == 443
        assert parsed.timeout == 60

    def test_get_settings_without_model(self):
        """get_settings() returns raw dict when no model registered."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            provider_settings={"redis": {"host": "cache.example.com", "port": 6379}}
        )
        bridge = DomainBridge("adapter", resolver, lifecycle, settings)

        raw = bridge.get_settings("redis")

        assert isinstance(raw, dict)
        assert raw == {"host": "cache.example.com", "port": 6379}

    def test_get_settings_caching(self):
        """get_settings() caches parsed settings."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            provider_settings={"fastapi": {"host": "localhost", "port": 8000}}
        )
        bridge = DomainBridge("service", resolver, lifecycle, settings)
        bridge.register_settings_model("fastapi", MockProviderSettings)

        # First call parses and caches
        parsed1 = bridge.get_settings("fastapi")
        # Second call returns cached instance
        parsed2 = bridge.get_settings("fastapi")

        assert parsed1 is parsed2  # Same instance (cached)

    def test_update_settings_clears_cache(self):
        """update_settings() clears settings cache."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings1 = LayerSettings(
            provider_settings={"fastapi": {"host": "localhost", "port": 8000}}
        )
        bridge = DomainBridge("service", resolver, lifecycle, settings1)
        bridge.register_settings_model("fastapi", MockProviderSettings)

        # Cache settings
        parsed1 = bridge.get_settings("fastapi")
        assert parsed1.host == "localhost"

        # Update settings
        settings2 = LayerSettings(
            provider_settings={"fastapi": {"host": "api.example.com", "port": 443}}
        )
        bridge.update_settings(settings2)

        # Get settings again (should re-parse from new settings)
        parsed2 = bridge.get_settings("fastapi")
        assert parsed2.host == "api.example.com"
        assert parsed1 is not parsed2  # Different instances


class TestDomainBridgeUse:
    """Test DomainBridge.use() for component activation."""

    @pytest.mark.asyncio
    async def test_use_simple_component(self):
        """use() activates and returns component in DomainHandle."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        # Register component
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("api"),
                source=CandidateSource.MANUAL,
                metadata={"version": "1.0.0"},
            )
        )

        # Use component
        handle = await bridge.use("api")

        assert isinstance(handle, DomainHandle)
        assert handle.domain == "service"
        assert handle.key == "api"
        assert handle.provider == "fastapi"
        assert isinstance(handle.instance, MockComponent)
        assert handle.instance.name == "api"
        assert handle.metadata == {"version": "1.0.0"}

    @pytest.mark.asyncio
    async def test_use_with_explicit_provider(self):
        """use() respects explicit provider override."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        # Register two providers
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="flask",
                factory=lambda: MockComponent("flask"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("fastapi"),
                source=CandidateSource.MANUAL,
            )
        )

        # Use with explicit provider
        handle = await bridge.use("api", provider="flask")

        assert handle.provider == "flask"
        assert handle.instance.name == "flask"

    @pytest.mark.asyncio
    async def test_use_with_config_selection(self):
        """use() uses configured selection from settings."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(selections={"api": "fastapi"})
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        # Register two providers
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="flask",
                factory=lambda: MockComponent("flask"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("fastapi"),
                source=CandidateSource.MANUAL,
            )
        )

        # Use without explicit provider (uses selection)
        handle = await bridge.use("api")

        assert handle.provider == "fastapi"
        assert handle.instance.name == "fastapi"

    @pytest.mark.asyncio
    async def test_use_returns_cached_instance(self):
        """use() returns cached instance on second call."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("api"),
                source=CandidateSource.MANUAL,
            )
        )

        # First use activates
        handle1 = await bridge.use("api")
        # Second use returns cached instance
        handle2 = await bridge.use("api")

        assert handle1.instance is handle2.instance

    @pytest.mark.asyncio
    async def test_use_with_force_reload(self):
        """use() creates new instance with force_reload=True."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MockComponent(f"api-{call_count}")

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=factory,
                source=CandidateSource.MANUAL,
            )
        )

        # First use
        handle1 = await bridge.use("api")
        assert handle1.instance.name == "api-1"

        # Force reload
        handle2 = await bridge.use("api", force_reload=True)
        assert handle2.instance.name == "api-2"
        assert handle1.instance is not handle2.instance

    @pytest.mark.asyncio
    async def test_use_fails_when_no_candidate(self):
        """use() raises LifecycleError when component not found."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        with pytest.raises(Exception, match="No candidate found for service:missing"):
            await bridge.use("missing")

    @pytest.mark.asyncio
    async def test_use_includes_provider_settings(self):
        """use() includes provider settings in handle."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(
            provider_settings={"fastapi": {"host": "localhost", "port": 8000}}
        )
        bridge = DomainBridge("service", resolver, lifecycle, settings)
        bridge.register_settings_model("fastapi", MockProviderSettings)

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("api"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("api")

        assert isinstance(handle.settings, MockProviderSettings)
        assert handle.settings.host == "localhost"
        assert handle.settings.port == 8000

    @pytest.mark.asyncio
    async def test_use_rejected_when_paused(self, tmp_path: Path):
        """use() raises when the key is paused."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store = DomainActivityStore(tmp_path / "activity.sqlite")
        bridge = DomainBridge(
            "service", resolver, lifecycle, settings, activity_store=store
        )

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("api"),
                source=CandidateSource.MANUAL,
            )
        )
        store.set("service", "api", DomainActivity(paused=True))

        with pytest.raises(LifecycleError, match="service:api is paused"):
            await bridge.use("api")

    @pytest.mark.asyncio
    async def test_use_rejected_when_draining(self, tmp_path: Path):
        """use() raises when the key is draining."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store = DomainActivityStore(tmp_path / "activity.sqlite")
        bridge = DomainBridge(
            "service", resolver, lifecycle, settings, activity_store=store
        )

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("api"),
                source=CandidateSource.MANUAL,
            )
        )
        store.set("service", "api", DomainActivity(draining=True))

        with pytest.raises(LifecycleError, match="service:api is draining"):
            await bridge.use("api")


class TestDomainBridgeListingMethods:
    """Test DomainBridge candidate listing methods."""

    def test_active_candidates(self):
        """active_candidates() returns active candidates for domain."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
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

        active = bridge.active_candidates()

        assert len(active) == 1
        assert active[0].domain == "service"
        assert active[0].key == "api"

    def test_shadowed_candidates(self):
        """shadowed_candidates() returns shadowed candidates for domain."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(selections={"api": "fastapi"})
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        # Register two providers (one will be shadowed)
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="flask",
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

        shadowed = bridge.shadowed_candidates()

        assert len(shadowed) == 1
        assert shadowed[0].provider == "flask"  # Shadowed by selection

    def test_explain(self):
        """explain() returns resolution explanation as dict."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        explanation = bridge.explain("api")

        assert isinstance(explanation, dict)
        assert explanation["domain"] == "service"
        assert explanation["key"] == "api"
        assert len(explanation["ordered"]) == 1
        # First entry should be selected winner
        assert explanation["ordered"][0]["provider"] == "fastapi"
        assert explanation["ordered"][0]["selected"] is True


class TestDomainBridgeActivity:
    """Test DomainBridge activity state management."""

    def test_activity_state_default(self):
        """activity_state() returns default state for new key."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        state = bridge.activity_state("api")

        assert isinstance(state, DomainActivity)
        assert not state.paused
        assert not state.draining
        assert state.note is None

    def test_set_paused(self):
        """set_paused() updates pause state."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        state = bridge.set_paused("api", True, note="maintenance window")

        assert state.paused is True
        assert state.note == "maintenance window"

        # Verify persisted
        retrieved = bridge.activity_state("api")
        assert retrieved.paused is True

    def test_set_paused_emits_metric(self, monkeypatch):
        """set_paused() records pause metrics via instrumentation."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        calls = []
        monkeypatch.setattr(
            "oneiric.domains.base.record_pause_state",
            lambda domain, paused: calls.append((domain, paused)),
        )

        bridge.set_paused("api", True)
        bridge.set_paused("api", False)

        assert calls == [("service", True), ("service", False)]

    def test_set_paused_resume(self):
        """set_paused(False) resumes paused component."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        # Pause
        bridge.set_paused("api", True, note="maintenance")
        # Resume
        state = bridge.set_paused("api", False)

        assert state.paused is False
        assert state.note == "maintenance"  # Note preserved

    def test_set_draining(self):
        """set_draining() updates drain state."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        state = bridge.set_draining("api", True, note="draining queue")

        assert state.draining is True
        assert state.note == "draining queue"

    def test_set_draining_emits_metric(self, monkeypatch):
        """set_draining() records drain metrics."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        calls = []
        monkeypatch.setattr(
            "oneiric.domains.base.record_drain_state",
            lambda domain, draining: calls.append((domain, draining)),
        )

        bridge.set_draining("api", True)
        bridge.set_draining("api", False)

        assert calls == [("service", True), ("service", False)]

    def test_set_draining_clear(self):
        """set_draining(False) clears drain state."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        # Set draining
        bridge.set_draining("api", True, note="draining")
        # Clear
        state = bridge.set_draining("api", False)

        assert state.draining is False

    def test_activity_snapshot(self):
        """activity_snapshot() returns all activity states."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("service", resolver, lifecycle, settings)

        # Set activity for multiple keys
        bridge.set_paused("api", True)
        bridge.set_draining("worker", True)

        snapshot = bridge.activity_snapshot()

        assert isinstance(snapshot, dict)
        assert "api" in snapshot
        assert "worker" in snapshot
        assert snapshot["api"].paused is True
        assert snapshot["worker"].draining is True

    def test_activity_with_store(self, tmp_path: Path):
        """Activity persists to external store when provided."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.sqlite"
        activity_store = DomainActivityStore(store_path)

        bridge = DomainBridge(
            "service", resolver, lifecycle, settings, activity_store=activity_store
        )

        # Set activity
        bridge.set_paused("api", True, note="maintenance")

        # Verify persisted to sqlite store
        assert store_path.exists()
        persisted = DomainActivityStore(store_path)
        state = persisted.get("service", "api")
        assert state.paused is True
        assert state.note == "maintenance"

    def test_activity_loads_from_store(self, tmp_path: Path):
        """Activity loads from store on initialization."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.sqlite"

        # Pre-populate store
        primer = DomainActivityStore(store_path)
        primer.set("service", "api", DomainActivity(paused=True, note="existing"))

        activity_store = DomainActivityStore(store_path)
        bridge = DomainBridge(
            "service", resolver, lifecycle, settings, activity_store=activity_store
        )

        # Should load from store
        state = bridge.activity_state("api")
        assert state.paused is True
        assert state.note == "existing"
