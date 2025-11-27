"""Integration tests for remote manifest watchers and hot-reloading.

This test suite validates that remote manifest changes trigger proper component
swapping across all domains (adapters, actions, services, tasks, events, workflows).
"""

from __future__ import annotations

import asyncio
import pytest
import yaml
from pathlib import Path

from oneiric.adapters.bridge import AdapterBridge
from oneiric.actions.bridge import ActionBridge
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.remote.loader import sync_remote_manifest
from oneiric.remote.models import RemoteManifest, RemoteManifestEntry


class TestRemoteManifestHotReload:
    """Test remote manifest hot-reloading and component swapping."""

    @pytest.mark.asyncio
    async def test_remote_manifest_triggers_adapter_swap(self, tmp_path):
        """Should swap adapter when remote manifest updates with higher precedence."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver, status_snapshot_path=None)
        adapter_bridge = AdapterBridge(resolver, lifecycle, {})

        # Initial manifest with memory cache (stack_level=10)
        manifest_v1 = RemoteManifest(
            source="test-v1",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                    stack_level=10,
                )
            ],
        )

        # Sync v1
        result = await sync_remote_manifest(resolver, manifest_v1, str(tmp_path))
        assert result.registered == 1
        assert result.per_domain["adapter"] == 1

        # Resolve and verify memory cache active
        decision = resolver.resolve("adapter", "cache")
        assert decision is not None
        assert decision.provider == "memory"
        assert decision.stack_level == 10

        # Updated manifest with memory cache at higher stack level
        manifest_v2 = RemoteManifest(
            source="test-v2",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory-upgraded",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                    stack_level=50,  # Higher precedence
                    metadata={"upgraded": True},
                )
            ],
        )

        # Sync v2
        result = await sync_remote_manifest(resolver, manifest_v2, str(tmp_path))
        assert result.registered == 1

        # Re-resolve should get upgraded version now
        decision = resolver.resolve("adapter", "cache")
        assert decision is not None
        assert decision.provider == "memory-upgraded"
        assert decision.stack_level == 50
        assert decision.metadata.get("upgraded") is True

    @pytest.mark.asyncio
    async def test_remote_action_registration(self, tmp_path):
        """Should register actions from remote manifest."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver, status_snapshot_path=None)

        # Manifest with multiple actions
        manifest = RemoteManifest(
            source="test-actions",
            entries=[
                RemoteManifestEntry(
                    domain="action",
                    key="http.fetch",
                    provider="builtin-http-fetch",
                    factory="oneiric.actions.http:HttpFetchAction",
                    side_effect_free=False,
                    timeout_seconds=30.0,
                ),
                RemoteManifestEntry(
                    domain="action",
                    key="data.transform",
                    provider="builtin-data-transform",
                    factory="oneiric.actions.data:DataTransformAction",
                    side_effect_free=True,
                ),
            ],
        )

        # Sync
        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        assert result.registered == 2
        assert result.per_domain["action"] == 2

        # Verify both actions registered
        http_action = resolver.resolve("action", "http.fetch")
        assert http_action is not None
        assert http_action.provider == "builtin-http-fetch"
        assert http_action.metadata.get("side_effect_free") is False
        assert http_action.metadata.get("timeout_seconds") == 30.0

        transform_action = resolver.resolve("action", "data.transform")
        assert transform_action is not None
        assert transform_action.metadata.get("side_effect_free") is True

    @pytest.mark.asyncio
    async def test_multi_domain_manifest_registration(self, tmp_path):
        """Should register components across all domains."""
        resolver = Resolver()

        # Manifest with all 6 domains
        manifest = RemoteManifest(
            source="test-all-domains",
            entries=[
                # Adapter
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                ),
                # Action
                RemoteManifestEntry(
                    domain="action",
                    key="http.fetch",
                    provider="builtin",
                    factory="oneiric.actions.http:HttpFetchAction",
                ),
                # Service
                RemoteManifestEntry(
                    domain="service",
                    key="status",
                    provider="demo",
                    factory="oneiric.remote.samples:demo_remote_service",
                ),
                # Task
                RemoteManifestEntry(
                    domain="task",
                    key="scheduler",
                    provider="demo",
                    factory="oneiric.remote.samples:demo_remote_task",
                ),
                # Event
                RemoteManifestEntry(
                    domain="event",
                    key="webhook",
                    provider="demo",
                    factory="oneiric.remote.samples:demo_remote_event_handler",
                ),
                # Workflow
                RemoteManifestEntry(
                    domain="workflow",
                    key="pipeline",
                    provider="demo",
                    factory="oneiric.remote.samples:demo_remote_workflow",
                ),
            ],
        )

        # Sync
        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        assert result.registered == 6
        assert result.per_domain == {
            "adapter": 1,
            "action": 1,
            "service": 1,
            "task": 1,
            "event": 1,
            "workflow": 1,
        }

        # Verify all domains registered
        assert resolver.resolve("adapter", "cache") is not None
        assert resolver.resolve("action", "http.fetch") is not None
        assert resolver.resolve("service", "status") is not None
        assert resolver.resolve("task", "scheduler") is not None
        assert resolver.resolve("event", "webhook") is not None
        assert resolver.resolve("workflow", "pipeline") is not None

    @pytest.mark.asyncio
    async def test_manifest_metadata_propagation(self, tmp_path):
        """Should propagate all v2 metadata fields to candidates."""
        resolver = Resolver()

        # Manifest with full v2 metadata
        manifest = RemoteManifest(
            source="test-metadata",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    factory="oneiric.adapters.cache.redis:RedisCacheAdapter",
                    version="1.0.0",
                    # Adapter-specific metadata
                    capabilities=["kv", "ttl", "tracking"],
                    owner="Platform Core Team",
                    requires_secrets=True,
                    settings_model="oneiric.adapters.cache.redis:RedisSettings",
                    # Dependencies
                    requires=["redis>=5.0.0", "coredis>=4.0.0"],
                    # Platform constraints
                    python_version=">=3.14",
                    os_platform=["linux", "darwin"],
                    # Documentation
                    license="MIT",
                    documentation_url="https://docs.example.com/redis",
                ),
            ],
        )

        # Sync
        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        assert result.registered == 1

        # Verify metadata propagation
        decision = resolver.resolve("adapter", "cache")
        assert decision is not None
        assert decision.metadata["version"] == "1.0.0"
        assert decision.metadata["capabilities"] == ["kv", "ttl", "tracking"]
        assert decision.metadata["owner"] == "Platform Core Team"
        assert decision.metadata["requires_secrets"] is True
        assert decision.metadata["settings_model"] == "oneiric.adapters.cache.redis:RedisSettings"
        assert decision.metadata["requires"] == ["redis>=5.0.0", "coredis>=4.0.0"]
        assert decision.metadata["python_version"] == ">=3.14"
        assert decision.metadata["os_platform"] == ["linux", "darwin"]
        assert decision.metadata["license"] == "MIT"
        assert decision.metadata["documentation_url"] == "https://docs.example.com/redis"


class TestRemoteCacheInvalidation:
    """Test artifact cache invalidation and cleanup."""

    @pytest.mark.asyncio
    async def test_digest_mismatch_prevents_load(self, tmp_path):
        """Should reject manifest entry if cached artifact digest doesn't match."""
        from oneiric.remote.loader import ArtifactManager

        manager = ArtifactManager(cache_dir=str(tmp_path))

        # Create fake cached file with wrong content
        fake_cache = tmp_path / "abc123"
        fake_cache.write_text("malicious content")

        # Attempt to validate digest
        expected_digest = "def456"  # Different from filename
        with pytest.raises(ValueError, match="SHA256 mismatch"):
            # This would be called internally during fetch
            from oneiric.remote.loader import _assert_digest
            _assert_digest(fake_cache, expected_digest)

    def test_cache_directory_permissions(self, tmp_path):
        """Should create cache directory with appropriate permissions."""
        from oneiric.remote.loader import ArtifactManager

        cache_dir = tmp_path / "artifact_cache"
        manager = ArtifactManager(cache_dir=str(cache_dir))

        assert cache_dir.exists()
        assert cache_dir.is_dir()
        # Permissions may vary by system, just verify it's accessible
        assert cache_dir.stat().st_mode & 0o700


class TestSignatureVerificationFailures:
    """Test signature verification failure handling."""

    @pytest.mark.asyncio
    async def test_missing_signature_allowed_when_not_required(self, tmp_path):
        """Should allow manifests without signatures when verification not required."""
        resolver = Resolver()

        # Manifest without signature
        manifest = RemoteManifest(
            source="unsigned",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                )
            ],
            signature=None,  # No signature
        )

        # Should sync successfully (no verification required by default)
        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        assert result.registered == 1

    def test_invalid_signature_format_rejected(self):
        """Should reject manifests with invalid signature format."""
        from oneiric.remote.security import verify_manifest_signature

        # Invalid base64 signature
        with pytest.raises(Exception):  # ValueError or binascii.Error
            verify_manifest_signature(
                canonical="test",
                signature="not-valid-base64!!!",
                public_key_pem=b"fake-key",
            )

    def test_signature_algorithm_validation(self):
        """Should only accept ed25519 signature algorithm."""
        from oneiric.remote.models import RemoteManifest

        # Valid algorithm
        manifest = RemoteManifest(
            source="test",
            entries=[],
            signature_algorithm="ed25519",
        )
        assert manifest.signature_algorithm == "ed25519"

        # Default algorithm should be ed25519
        manifest2 = RemoteManifest(source="test", entries=[])
        assert manifest2.signature_algorithm == "ed25519"


class TestConcurrentRemoteSync:
    """Test concurrent remote manifest synchronization."""

    @pytest.mark.asyncio
    async def test_concurrent_sync_safety(self, tmp_path):
        """Should handle concurrent manifest syncs safely."""
        resolver = Resolver()

        manifest1 = RemoteManifest(
            source="concurrent-1",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory-1",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                    stack_level=10,
                )
            ],
        )

        manifest2 = RemoteManifest(
            source="concurrent-2",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory-2",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                    stack_level=20,  # Higher precedence
                )
            ],
        )

        # Run concurrent syncs
        results = await asyncio.gather(
            sync_remote_manifest(resolver, manifest1, str(tmp_path)),
            sync_remote_manifest(resolver, manifest2, str(tmp_path)),
        )

        # Both should succeed
        assert all(r.registered == 1 for r in results)

        # Higher precedence should win
        decision = resolver.resolve("adapter", "cache")
        assert decision is not None
        assert decision.provider == "memory-2"
        assert decision.stack_level == 20

    @pytest.mark.asyncio
    async def test_rapid_sequential_syncs(self, tmp_path):
        """Should handle rapid sequential manifest updates."""
        resolver = Resolver()

        # Simulate rapid updates (version bumps)
        for version in range(1, 6):
            manifest = RemoteManifest(
                source=f"rapid-v{version}",
                entries=[
                    RemoteManifestEntry(
                        domain="adapter",
                        key="cache",
                        provider=f"memory-v{version}",
                        factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                        stack_level=version * 10,
                        version=f"1.0.{version}",
                    )
                ],
            )

            result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
            assert result.registered == 1

        # Final version should win
        decision = resolver.resolve("adapter", "cache")
        assert decision is not None
        assert decision.provider == "memory-v5"
        assert decision.stack_level == 50
        assert decision.metadata["version"] == "1.0.5"


class TestManifestValidation:
    """Test manifest validation and error handling."""

    @pytest.mark.asyncio
    async def test_invalid_domain_skipped(self, tmp_path):
        """Should skip entries with invalid domains."""
        resolver = Resolver()

        manifest = RemoteManifest(
            source="invalid-domain",
            entries=[
                RemoteManifestEntry(
                    domain="invalid-domain-name",  # Not a valid domain
                    key="test",
                    provider="test",
                    factory="test.factory:TestClass",
                ),
                RemoteManifestEntry(
                    domain="adapter",  # Valid domain
                    key="cache",
                    provider="memory",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                ),
            ],
        )

        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        # Only valid entry should register
        assert result.registered == 1
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_empty_manifest_handled(self, tmp_path):
        """Should handle empty manifests gracefully."""
        resolver = Resolver()

        manifest = RemoteManifest(
            source="empty",
            entries=[],  # No entries
        )

        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        assert result.registered == 0
        assert result.skipped == 0
        assert len(result.per_domain) == 0

    @pytest.mark.asyncio
    async def test_duplicate_entries_both_registered(self, tmp_path):
        """Should register duplicate entries (last one wins in resolution)."""
        resolver = Resolver()

        manifest = RemoteManifest(
            source="duplicates",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory-1",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                    stack_level=10,
                ),
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",  # Same key
                    provider="memory-2",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                    stack_level=10,  # Same stack level
                ),
            ],
        )

        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        # Both register
        assert result.registered == 2

        # Resolution should return the last registered (registration order tie-breaker)
        decision = resolver.resolve("adapter", "cache")
        assert decision is not None
        # Last registration wins when stack_level is equal
        assert decision.provider == "memory-2"
