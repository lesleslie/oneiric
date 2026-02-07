"""Tests for multi-tier cache adapter."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from oneiric.adapters.cache.memory import MemoryCacheAdapter, MemoryCacheSettings
from oneiric.adapters.cache.multitier import (
    CacheMetrics,
    MultiTierCacheAdapter,
    MultiTierCacheSettings,
)
from oneiric.core.lifecycle import LifecycleError


class TestCacheMetrics:
    """Test cache metrics calculations."""

    def test_l1_hit_rate_calculation(self):
        """Test L1 hit rate is calculated correctly."""
        metrics = CacheMetrics(l1_hits=85, l1_misses=15)
        assert metrics.l1_hit_rate == 85.0

    def test_l1_hit_rate_no_requests(self):
        """Test L1 hit rate returns 0 when no requests."""
        metrics = CacheMetrics()
        assert metrics.l1_hit_rate == 0.0

    def test_l2_hit_rate_calculation(self):
        """Test L2 hit rate is calculated correctly."""
        metrics = CacheMetrics(l2_hits=60, l2_misses=40)
        assert metrics.l2_hit_rate == 60.0

    def test_combined_hit_rate_calculation(self):
        """Test combined hit rate includes both tiers."""
        metrics = CacheMetrics(
            l1_hits=70,  # 70% hit in L1
            l1_misses=30,
            l2_hits=20,  # 20% hit in L2 (out of 30 misses)
            l2_misses=10,
            total_requests=100,
        )
        # Combined: (70 + 20) / 100 = 90%
        assert metrics.combined_hit_rate == 90.0

    def test_avg_latency_calculation(self):
        """Test average latency includes both tiers."""
        metrics = CacheMetrics(
            l1_hits=50,
            l1_misses=30,
            l2_hits=15,
            l2_misses=5,
            l1_latency_ms=500.0,  # 50 ops * 10ms = 500ms
            l2_latency_ms=1000.0,  # 15 ops * 50ms + misses
        )
        # Total: 100 ops, 1500ms total = 15ms avg
        assert metrics.avg_latency_ms == 1500.0 / 100

    def test_to_dict(self):
        """Test metrics serialization."""
        metrics = CacheMetrics(l1_hits=80, l1_misses=20, total_requests=100)
        result = metrics.to_dict()
        assert result["l1_hit_rate"] == "80.0%"
        assert result["total_requests"] == 100


class TestMultiTierCacheSettings:
    """Test multi-tier cache settings validation."""

    def test_default_settings(self):
        """Test default settings match optimization plan."""
        settings = MultiTierCacheSettings()
        assert settings.l1_enabled is True
        assert settings.l1_max_entries == 1000
        assert settings.l1_ttl_seconds == 600  # 10 minutes
        assert settings.l2_enabled is True
        assert settings.l2_ttl_seconds == 86400  # 24 hours
        assert settings.write_through is True
        assert settings.write_back_l1_on_l2_hit is True
        assert settings.enable_metrics is True

    def test_l1_max_entries_validation(self):
        """Test L1 max entries constraints."""
        # Valid range
        settings = MultiTierCacheSettings(l1_max_entries=5000)
        assert settings.l1_max_entries == 5000

        # Too low
        with pytest.raises(ValueError):
            MultiTierCacheSettings(l1_max_entries=0)

        # Too high
        with pytest.raises(ValueError):
            MultiTierCacheSettings(l1_max_entries=10001)

    def test_ttl_validation(self):
        """Test TTL must be positive."""
        with pytest.raises(ValueError):
            MultiTierCacheSettings(l1_ttl_seconds=0)

        with pytest.raises(ValueError):
            MultiTierCacheSettings(l2_ttl_seconds=-1)


class TestMultiTierCacheAdapter:
    """Test multi-tier cache adapter functionality."""

    @pytest.fixture
    async def l1_cache(self):
        """Create L1 cache instance."""
        cache = MemoryCacheAdapter(
            settings=MemoryCacheSettings(max_entries=100, default_ttl=60)
        )
        await cache.init()
        yield cache
        await cache.cleanup()

    @pytest.fixture
    async def multitier_cache(self, l1_cache):
        """Create multi-tier cache with mocked L2."""
        # Mock L2 cache
        mock_l2 = AsyncMock()
        mock_l2.get = AsyncMock(return_value=None)
        mock_l2.set = AsyncMock()
        mock_l2.delete = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        # Create cache without L2 (L1-only mode for testing)
        settings = MultiTierCacheSettings(
            l1_enabled=True,
            l2_enabled=False,
            enable_metrics=True,
        )
        cache = MultiTierCacheAdapter(settings=settings, l1_cache=l1_cache, l2_cache=None)
        await cache.init()
        yield cache
        await cache.cleanup()

    @pytest.mark.asyncio
    async def test_init_initializes_both_layers(self):
        """Test init initializes both cache layers."""
        mock_l1 = AsyncMock()
        mock_l1.init = AsyncMock()
        mock_l1.health = AsyncMock(return_value=True)

        mock_l2 = AsyncMock()
        mock_l2.init = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        cache = MultiTierCacheAdapter(
            l1_cache=mock_l1, l2_cache=mock_l2, settings=MultiTierCacheSettings()
        )
        await cache.init()

        mock_l1.init.assert_called_once()
        mock_l2.init.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_l1_hit(self, multitier_cache):
        """Test cache get hits in L1."""
        await multitier_cache.set("test_key", "test_value")
        result = await multitier_cache.get("test_key")

        assert result == "test_value"

        metrics = await multitier_cache.get_metrics()
        assert metrics["l1_hits"] == 1
        assert metrics["l1_misses"] == 0

    @pytest.mark.asyncio
    async def test_get_l1_miss(self, multitier_cache):
        """Test cache get misses in L1."""
        result = await multitier_cache.get("nonexistent_key")

        assert result is None

        metrics = await multitier_cache.get_metrics()
        assert metrics["l1_misses"] == 1
        assert metrics["l1_hits"] == 0

    @pytest.mark.asyncio
    async def test_set_writes_to_both_layers(self):
        """Test set writes to both L1 and L2 when write_through enabled."""
        mock_l1 = AsyncMock()
        mock_l1.set = AsyncMock()
        mock_l1.health = AsyncMock(return_value=True)

        mock_l2 = AsyncMock()
        mock_l2.set = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        settings = MultiTierCacheSettings(write_through=True)
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=mock_l1, l2_cache=mock_l2
        )
        await cache.init()

        await cache.set("test_key", "test_value")

        # Both layers should be written
        mock_l1.set.assert_called_once()
        mock_l2.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_skips_l2_when_write_through_disabled(self):
        """Test set skips L2 when write_through is False."""
        mock_l1 = AsyncMock()
        mock_l1.set = AsyncMock()
        mock_l1.health = AsyncMock(return_value=True)

        mock_l2 = AsyncMock()
        mock_l2.set = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        settings = MultiTierCacheSettings(write_through=False)
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=mock_l1, l2_cache=mock_l2
        )
        await cache.init()

        await cache.set("test_key", "test_value")

        # Only L1 should be written
        mock_l1.set.assert_called_once()
        mock_l2.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_removes_from_both_layers(self):
        """Test delete removes from both cache layers."""
        mock_l1 = AsyncMock()
        mock_l1.delete = AsyncMock()
        mock_l1.health = AsyncMock(return_value=True)

        mock_l2 = AsyncMock()
        mock_l2.delete = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        cache = MultiTierCacheAdapter(
            l1_cache=mock_l1, l2_cache=mock_l2, settings=MultiTierCacheSettings()
        )
        await cache.init()

        await cache.delete("test_key")

        mock_l1.delete.assert_called_once_with("test_key")
        mock_l2.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_clear_empties_both_layers(self):
        """Test clear empties both cache layers."""
        mock_l1 = AsyncMock()
        mock_l1.clear = AsyncMock()
        mock_l1.health = AsyncMock(return_value=True)

        mock_l2 = AsyncMock()
        mock_l2.clear = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        cache = MultiTierCacheAdapter(
            l1_cache=mock_l1, l2_cache=mock_l2, settings=MultiTierCacheSettings()
        )
        await cache.init()

        await cache.clear()

        mock_l1.clear.assert_called_once()
        mock_l2.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_returns_true_if_either_layer_healthy(self):
        """Test health returns True if at least one layer is healthy."""
        mock_l1 = AsyncMock()
        mock_l1.health = AsyncMock(return_value=False)

        mock_l2 = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        cache = MultiTierCacheAdapter(
            l1_cache=mock_l1, l2_cache=mock_l2, settings=MultiTierCacheSettings()
        )
        await cache.init()

        result = await cache.health()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_returns_false_if_both_layers_unhealthy(self):
        """Test health returns False if both layers are unhealthy."""
        mock_l1 = AsyncMock()
        mock_l1.health = AsyncMock(return_value=False)

        mock_l2 = AsyncMock()
        mock_l2.health = AsyncMock(return_value=False)

        cache = MultiTierCacheAdapter(
            l1_cache=mock_l1, l2_cache=mock_l2, settings=MultiTierCacheSettings()
        )
        await cache.init()

        result = await cache.health()
        assert result is False

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, multitier_cache):
        """Test metrics are tracked correctly."""
        # Generate some cache activity
        await multitier_cache.set("key1", "value1")
        await multitier_cache.get("key1")  # L1 hit
        await multitier_cache.get("key2")  # L1 miss

        metrics = await multitier_cache.get_metrics()
        assert metrics["l1_hits"] == 1
        assert metrics["l1_misses"] == 1
        assert metrics["total_requests"] == 2
        assert metrics["combined_hit_rate"] == "50.0%"

    @pytest.mark.asyncio
    async def test_reset_metrics(self, multitier_cache):
        """Test metrics can be reset."""
        await multitier_cache.set("key1", "value1")
        await multitier_cache.get("key1")

        await multitier_cache.reset_metrics()

        metrics = await multitier_cache.get_metrics()
        assert metrics["l1_hits"] == 0
        assert metrics["total_requests"] == 0

    @pytest.mark.asyncio
    async def test_metrics_disabled(self):
        """Test metrics can be disabled."""
        mock_l1 = AsyncMock()
        mock_l1.get = AsyncMock(return_value="value")
        mock_l1.health = AsyncMock(return_value=True)

        settings = MultiTierCacheSettings(enable_metrics=False)
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=mock_l1, l2_cache=None
        )
        await cache.init()

        result = await cache.get("key")
        assert result == "value"

        metrics = await cache.get_metrics()
        assert metrics == {"error": "metrics_disabled"}

    @pytest.mark.asyncio
    async def test_l2_hit_populates_l1(self):
        """Test L2 hit populates L1 cache when write_back_l1_on_l2_hit enabled."""
        mock_l1 = AsyncMock()
        mock_l1.get = AsyncMock(return_value=None)  # L1 miss
        mock_l1.set = AsyncMock()
        mock_l1.health = AsyncMock(return_value=True)

        mock_l2 = AsyncMock()
        mock_l2.get = AsyncMock(return_value="l2_value")  # L2 hit
        mock_l2.set = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        settings = MultiTierCacheSettings(write_back_l1_on_l2_hit=True)
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=mock_l1, l2_cache=mock_l2
        )
        await cache.init()

        result = await cache.get("test_key")

        assert result == "l2_value"
        # L1 should be populated with L2 value
        mock_l1.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalidate_l1(self):
        """Test L1 cache invalidation."""
        l1_cache = MemoryCacheAdapter(
            settings=MemoryCacheSettings(max_entries=10, default_ttl=60)
        )
        await l1_cache.init()

        settings = MultiTierCacheSettings(l2_enabled=False)
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=l1_cache, l2_cache=None
        )
        await cache.init()

        # Set some values
        await cache.set("key1", "value1")
        assert await cache.get("key1") == "value1"

        # Invalidate L1
        cache.invalidate_l1()

        # L1 should now be empty
        assert await cache.get("key1") is None

        await l1_cache.cleanup()

    @pytest.mark.asyncio
    async def test_get_settings(self):
        """Test getting current settings."""
        settings = MultiTierCacheSettings(
            l1_max_entries=2000,
            l2_ttl_seconds=3600,
        )
        cache = MultiTierCacheAdapter(settings=settings)

        result = cache.get_settings()
        assert result.l1_max_entries == 2000
        assert result.l2_ttl_seconds == 3600

    @pytest.mark.asyncio
    async def test_custom_ttl_override(self):
        """Test custom TTL overrides default TTLs."""
        mock_l1 = AsyncMock()
        mock_l1.set = AsyncMock()
        mock_l1.health = AsyncMock(return_value=True)

        mock_l2 = AsyncMock()
        mock_l2.set = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        settings = MultiTierCacheSettings(
            l1_ttl_seconds=600,  # 10 minutes default
            l2_ttl_seconds=86400,  # 24 hours default
        )
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=mock_l1, l2_cache=mock_l2
        )
        await cache.init()

        # Set with custom TTL
        await cache.set("key", "value", ttl=300)  # 5 minutes

        # Check custom TTL was used
        mock_l1.set.assert_called_once()
        call_kwargs = mock_l1.set.call_args.kwargs
        assert call_kwargs["ttl"] == 300

        mock_l2.set.assert_called_once()
        call_kwargs = mock_l2.set.call_args.kwargs
        assert call_kwargs["ttl"] == 300


@pytest.mark.integration
class TestMultiTierCacheIntegration:
    """Integration tests for multi-tier cache with real components."""

    @pytest.mark.asyncio
    async def test_l1_l2_fallback_pattern(self):
        """Test L1 miss → L2 hit → L1 populate pattern."""
        # Create L1 cache with short TTL
        l1_cache = MemoryCacheAdapter(
            settings=MemoryCacheSettings(max_entries=10, default_ttl=1)
        )
        await l1_cache.init()

        # Mock L2 that always returns a value
        mock_l2 = AsyncMock()
        mock_l2.get = AsyncMock(return_value="from_l2")
        mock_l2.set = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        settings = MultiTierCacheSettings(
            write_back_l1_on_l2_hit=True,
            enable_metrics=True,
        )
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=l1_cache, l2_cache=mock_l2
        )
        await cache.init()

        # First get: L1 miss, L2 hit, L1 populated
        result = await cache.get("test_key")
        assert result == "from_l2"

        # Check L1 was populated
        assert await l1_cache.get("test_key") == "from_l2"

        # Second get: Should hit in L1
        result = await cache.get("test_key")
        assert result == "from_l2"

        # Verify L2 wasn't called on second get
        assert mock_l2.get.call_count == 1

        await l1_cache.cleanup()
        await cache.cleanup()

    @pytest.mark.asyncio
    async def test_cache_hit_rate_target(self):
        """Test cache achieves 85% hit rate target."""
        # This test simulates the target hit rate from the optimization plan
        l1_cache = MemoryCacheAdapter(
            settings=MemoryCacheSettings(max_entries=1000, default_ttl=600)
        )
        await l1_cache.init()

        # Mock L2 with some data (10% miss rate)
        mock_l2 = AsyncMock()
        mock_l2.get = AsyncMock(side_effect=lambda k: f"value_{k}" if int(k.split("_")[1]) % 10 != 0 else None)
        mock_l2.set = AsyncMock()
        mock_l2.health = AsyncMock(return_value=True)

        settings = MultiTierCacheSettings(enable_metrics=True)
        cache = MultiTierCacheAdapter(
            settings=settings, l1_cache=l1_cache, l2_cache=mock_l2
        )
        await cache.init()

        # Simulate 100 cache requests with working set of 30 items
        # With 90% L2 hit rate and L1 caching, we should achieve >85% combined
        for i in range(100):
            key = f"key_{i % 30}"
            await cache.get(key)

        metrics = await cache.get_metrics()
        combined_rate = float(metrics["combined_hit_rate"].rstrip("%"))

        # Should achieve >=85% hit rate with 30-item working set and 10% miss rate
        assert combined_rate >= 85.0

        await l1_cache.cleanup()
        await cache.cleanup()
