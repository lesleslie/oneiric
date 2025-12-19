"""Tests for remote manifest loader and artifact fetcher."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from oneiric.core.config import RemoteSourceConfig
from oneiric.core.resolution import CandidateSource, Resolver
from oneiric.remote.loader import (
    ArtifactManager,
    _candidate_from_entry,
    _parse_manifest,
    _validate_entry,
    sync_remote_manifest,
)
from oneiric.remote.models import RemoteManifestEntry

# Test helpers


class MockComponent:
    """Mock component for testing."""

    def __init__(self, name: str):
        self.name = name


# ArtifactManager Tests


class TestArtifactManager:
    """Test ArtifactManager artifact fetching and caching."""

    def test_init_creates_cache_directory(self, tmp_path):
        """ArtifactManager creates cache directory on init."""
        cache_dir = tmp_path / "cache"
        assert not cache_dir.exists()

        manager = ArtifactManager(str(cache_dir))

        assert cache_dir.exists()
        assert manager.cache_dir == cache_dir
        assert manager.verify_tls is True

    def test_init_with_existing_directory(self, tmp_path):
        """ArtifactManager works with existing cache directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        manager = ArtifactManager(str(cache_dir))

        assert manager.cache_dir == cache_dir

    @pytest.mark.asyncio
    async def test_fetch_local_file_with_sha256(self, tmp_path):
        """ArtifactManager fetches local file and verifies digest."""
        cache_dir = tmp_path / "cache"
        manager = ArtifactManager(
            str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )

        # Create source file
        source_file = tmp_path / "source.txt"
        source_file.write_text("test content")
        sha256 = hashlib.sha256(b"test content").hexdigest()

        # Fetch via file:// URI
        result = await manager.fetch(
            uri=f"file://{source_file}",
            sha256=sha256,
            headers={},
        )

        assert result.exists()
        assert result.read_text() == "test content"
        assert result.parent == cache_dir
        assert result.name == sha256

    @pytest.mark.asyncio
    async def test_fetch_local_file_digest_mismatch(self, tmp_path):
        """ArtifactManager raises on digest mismatch."""
        cache_dir = tmp_path / "cache"
        manager = ArtifactManager(
            str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )

        source_file = tmp_path / "source.txt"
        source_file.write_text("test content")
        wrong_sha256 = "wrong_digest_here"

        with pytest.raises(ValueError, match="Digest mismatch"):
            await manager.fetch(
                uri=f"file://{source_file}",
                sha256=wrong_sha256,
                headers={},
            )

    @pytest.mark.asyncio
    async def test_fetch_cached_artifact(self, tmp_path):
        """ArtifactManager returns cached artifact if exists."""
        cache_dir = tmp_path / "cache"
        manager = ArtifactManager(str(cache_dir))

        # Pre-populate cache
        sha256 = hashlib.sha256(b"cached content").hexdigest()
        cached_file = cache_dir / sha256
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_file.write_text("cached content")

        # Fetch should return cached file without accessing source
        result = await manager.fetch(
            uri="https://example.com/artifact.whl",  # Won't be accessed
            sha256=sha256,
            headers={},
        )

        assert result == cached_file
        assert result.read_text() == "cached content"

    @pytest.mark.asyncio
    async def test_fetch_path_traversal_protection(self, tmp_path):
        """ArtifactManager blocks path traversal attempts."""
        cache_dir = tmp_path / "cache"
        manager = ArtifactManager(str(cache_dir))

        # Attempt 1: .. in URI
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(
                uri="../etc/passwd",
                sha256=None,
                headers={},
            )

        # Attempt 2: Absolute path outside cache
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(
                uri="/etc/passwd",
                sha256=None,
                headers={},
            )

    @pytest.mark.asyncio
    async def test_fetch_invalid_uri_scheme(self, tmp_path):
        """ArtifactManager rejects unsupported URI schemes."""
        cache_dir = tmp_path / "cache"
        manager = ArtifactManager(str(cache_dir))

        with pytest.raises(ValueError, match="(Unsupported URI scheme|Path traversal)"):
            await manager.fetch(
                uri="ftp://example.com/file.txt",
                sha256=None,
                headers={},
            )

    @pytest.mark.asyncio
    async def test_fetch_file_uri_disallowed_by_default(self, tmp_path):
        """ArtifactManager blocks file URIs unless explicitly enabled."""
        cache_dir = tmp_path / "cache"
        manager = ArtifactManager(str(cache_dir))
        source_file = tmp_path / "source.txt"
        source_file.write_text("test content")

        with pytest.raises(ValueError, match="file URI access disabled"):
            await manager.fetch(
                uri=f"file://{source_file}",
                sha256=None,
                headers={},
            )

    @pytest.mark.asyncio
    async def test_fetch_file_uri_enforces_root_allowlist(self, tmp_path):
        """ArtifactManager enforces local file allowlist roots."""
        cache_dir = tmp_path / "cache"
        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()
        manager = ArtifactManager(
            str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(allowed_root)],
        )
        source_file = tmp_path / "outside.txt"
        source_file.write_text("test content")

        with pytest.raises(ValueError, match="Local path access denied"):
            await manager.fetch(
                uri=f"file://{source_file}",
                sha256=None,
                headers={},
            )

    @pytest.mark.asyncio
    async def test_fetch_http_artifact(self, tmp_path, monkeypatch):
        """ArtifactManager fetches HTTP artifacts via httpx."""
        cache_dir = tmp_path / "cache"
        manager = ArtifactManager(str(cache_dir))

        payload = b"http content"

        async def _aiter_bytes():
            yield payload

        mock_response = MagicMock()
        mock_response.aiter_bytes.return_value = _aiter_bytes()
        mock_response.raise_for_status.return_value = None

        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream.return_value = mock_stream

        monkeypatch.setattr(
            "oneiric.remote.loader.httpx.AsyncClient",
            MagicMock(return_value=mock_client),
        )

        sha256 = hashlib.sha256(payload).hexdigest()

        result = await manager.fetch(
            uri="https://example.com/artifact.whl",
            sha256=sha256,
            headers={"Authorization": "Bearer token"},
        )

        assert result.exists()
        assert result.read_text() == "http content"
        assert result.name == sha256
        mock_client.stream.assert_called_once()


# Manifest Parsing Tests


class TestManifestParsing:
    """Test manifest parsing from JSON and YAML."""

    def test_parse_json_manifest(self):
        """Parse manifest from JSON."""
        json_text = json.dumps(
            {
                "source": "test",
                "entries": [
                    {
                        "domain": "adapter",
                        "key": "cache",
                        "provider": "redis",
                        "factory": "myapp.adapters:RedisCache",
                    }
                ],
            }
        )

        manifest = _parse_manifest(json_text, verify_signature=False)

        assert manifest.source == "test"
        assert len(manifest.entries) == 1
        assert manifest.entries[0].domain == "adapter"

    def test_parse_yaml_manifest(self):
        """Parse manifest from YAML."""
        yaml_text = yaml.dump(
            {
                "source": "test",
                "entries": [
                    {
                        "domain": "service",
                        "key": "payment",
                        "provider": "stripe",
                        "factory": "myapp.services:StripePayment",
                    }
                ],
            }
        )

        manifest = _parse_manifest(yaml_text, verify_signature=False)

        assert manifest.source == "test"
        assert len(manifest.entries) == 1
        assert manifest.entries[0].domain == "service"

    def test_parse_manifest_invalid_top_level(self):
        """Parse rejects non-dict top level."""
        invalid_text = json.dumps(["list", "not", "dict"])

        with pytest.raises(ValueError, match="must be a mapping"):
            _parse_manifest(invalid_text, verify_signature=False)

    def test_parse_manifest_with_signature(self):
        """Parse manifest with signature field."""
        manifest_dict = {
            "source": "signed",
            "entries": [],
            "signature": "base64-signature",
            "signature_algorithm": "ed25519",
        }

        # Mock signature verification to succeed
        with patch(
            "oneiric.remote.loader.verify_manifest_signatures",
            return_value=(True, None, 1),
        ):
            manifest = _parse_manifest(json.dumps(manifest_dict), verify_signature=True)

        assert manifest.signature == "base64-signature"

    def test_parse_manifest_requires_signature(self):
        """Signature requirement rejects unsigned manifests."""
        manifest_dict = {"source": "unsigned", "entries": []}
        policy = RemoteSourceConfig(signature_required=True)

        with pytest.raises(ValueError, match="signature required"):
            _parse_manifest(
                json.dumps(manifest_dict),
                verify_signature=True,
                signature_policy=policy,
            )

    def test_parse_manifest_expired_signature(self):
        """Expired signatures are rejected."""
        manifest_dict = {
            "source": "expired",
            "entries": [],
            "signature": "base64-signature",
            "signature_algorithm": "ed25519",
            "signed_at": "2000-01-01T00:00:00+00:00",
            "expires_at": "2000-01-02T00:00:00+00:00",
        }
        policy = RemoteSourceConfig(signature_required=True)

        with patch(
            "oneiric.remote.loader.verify_manifest_signatures",
            return_value=(True, None, 1),
        ):
            with pytest.raises(ValueError, match="expired"):
                _parse_manifest(
                    json.dumps(manifest_dict),
                    verify_signature=True,
                    signature_policy=policy,
                )

    def test_parse_manifest_max_age_enforced(self):
        """Max age policy rejects stale signatures."""
        manifest_dict = {
            "source": "stale",
            "entries": [],
            "signature": "base64-signature",
            "signature_algorithm": "ed25519",
            "signed_at": "2000-01-01T00:00:00+00:00",
        }
        policy = RemoteSourceConfig(
            signature_required=True, signature_max_age_seconds=1
        )

        with patch(
            "oneiric.remote.loader.verify_manifest_signatures",
            return_value=(True, None, 1),
        ):
            with pytest.raises(ValueError, match="maximum age"):
                _parse_manifest(
                    json.dumps(manifest_dict),
                    verify_signature=True,
                    signature_policy=policy,
                )


# Entry Validation Tests


class TestEntryValidation:
    """Test _validate_entry input validation."""

    def test_validate_valid_entry(self):
        """Valid entry passes validation."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="oneiric.adapters.bridge:AdapterBridge",  # Use allowed module
        )

        error = _validate_entry(entry)

        assert error is None

    def test_validate_invalid_domain(self):
        """Invalid domain fails validation."""
        entry = RemoteManifestEntry(
            domain="invalid_domain",
            key="cache",
            provider="redis",
            factory="myapp.adapters:RedisCache",
        )

        error = _validate_entry(entry)

        assert error is not None
        assert "unsupported domain" in error

    def test_validate_missing_key(self):
        """Missing key fails validation."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="",
            provider="redis",
            factory="myapp.adapters:RedisCache",
        )

        error = _validate_entry(entry)

        assert error is not None
        assert "missing key" in error

    def test_validate_missing_provider(self):
        """Missing provider fails validation."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="",
            factory="myapp.adapters:RedisCache",
        )

        error = _validate_entry(entry)

        assert error is not None
        assert "missing provider" in error

    def test_validate_missing_factory(self):
        """Missing factory fails validation."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="",
        )

        error = _validate_entry(entry)

        assert error is not None
        assert "missing factory" in error

    def test_validate_path_traversal_in_uri(self):
        """URI with path traversal fails validation."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="oneiric.adapters.bridge:AdapterBridge",
            uri="../../../etc/passwd",
        )

        error = _validate_entry(entry)

        assert error is not None
        assert "path traversal" in error.lower()


# Candidate Conversion Tests


class TestCandidateConversion:
    """Test _candidate_from_entry conversion."""

    def test_candidate_from_minimal_entry(self):
        """Convert minimal entry to candidate."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="myapp.adapters:RedisCache",
            capabilities=[
                {
                    "name": "kv",
                    "description": "Key/value",
                    "event_types": ["cache.hit"],
                    "payload_schema": {"type": "object"},
                    "security": {
                        "classification": "internal",
                        "auth_required": True,
                        "scopes": ["cache.read"],
                    },
                    "metadata": {"ttl_ms": 1000},
                },
                "ttl",
            ],
        )

        candidate = _candidate_from_entry(entry, artifact_path=None)

        assert candidate.domain == "adapter"
        assert candidate.key == "cache"
        assert candidate.provider == "redis"
        assert candidate.factory == "myapp.adapters:RedisCache"
        assert candidate.source == CandidateSource.REMOTE_MANIFEST
        assert candidate.metadata["source"] == "remote"
        assert candidate.metadata["capabilities"] == ["kv", "ttl"]
        assert candidate.metadata["capability_descriptors"] == [
            {
                "name": "kv",
                "description": "Key/value",
                "event_types": ["cache.hit"],
                "payload_schema": {"type": "object"},
                "security": {
                    "classification": "internal",
                    "auth_required": True,
                    "scopes": ["cache.read"],
                },
                "metadata": {"ttl_ms": 1000},
            },
            {"name": "ttl"},
        ]

    def test_candidate_from_full_entry(self):
        """Convert full entry with all fields to candidate."""
        entry = RemoteManifestEntry(
            domain="service",
            key="payment",
            provider="stripe",
            factory="myapp.services:StripePayment",
            uri="https://cdn.example.com/stripe.whl",
            stack_level=10,
            priority=5,
            version="1.0.0",
            metadata={"region": "us-east-1"},
        )
        artifact_path = Path("/cache/abc123")

        candidate = _candidate_from_entry(entry, artifact_path=artifact_path)

        assert candidate.stack_level == 10
        assert candidate.priority == 5
        assert candidate.metadata["remote_uri"] == "https://cdn.example.com/stripe.whl"
        assert candidate.metadata["artifact_path"] == "/cache/abc123"
        assert candidate.metadata["version"] == "1.0.0"
        assert candidate.metadata["region"] == "us-east-1"

    def test_candidate_includes_event_and_dag_metadata(self):
        """Event/DAG specific fields propagate into candidate metadata."""
        entry = RemoteManifestEntry(
            domain="event",
            key="user-handler",
            provider="demo",
            factory="demo.handlers:UserHandler",
            event_topics=["user.created", "user.updated"],
            event_max_concurrency=5,
            event_filters=[{"path": "payload.region", "equals": "us"}],
            event_priority=42,
            event_fanout_policy="exclusive",
            dag={"nodes": [{"id": "sync-profile", "task": "profile-sync"}]},
        )

        candidate = _candidate_from_entry(entry, artifact_path=None)

        assert candidate.metadata["topics"] == ["user.created", "user.updated"]
        assert candidate.metadata["max_concurrency"] == 5
        assert candidate.metadata["filters"] == [
            {"path": "payload.region", "equals": "us"}
        ]
        assert candidate.metadata["event_priority"] == 42
        assert candidate.metadata["fanout_policy"] == "exclusive"
        assert candidate.metadata["dag"] == {
            "nodes": [{"id": "sync-profile", "task": "profile-sync"}]
        }


# Remote Sync Tests


class TestRemoteSync:
    """Test sync_remote_manifest end-to-end."""

    @pytest.mark.asyncio
    async def test_sync_disabled_config(self, tmp_path):
        """Sync skips if config disabled."""
        resolver = Resolver()
        config = RemoteSourceConfig(
            enabled=False,
            manifest_url="https://example.com/manifest.yaml",
            cache_dir=str(tmp_path / "cache"),
        )

        result = await sync_remote_manifest(resolver, config)

        assert result is None

    @pytest.mark.asyncio
    async def test_sync_no_manifest_url(self, tmp_path):
        """Sync skips if no manifest URL."""
        resolver = Resolver()
        config = RemoteSourceConfig(
            enabled=True,
            manifest_url="",
            cache_dir=str(tmp_path / "cache"),
        )

        result = await sync_remote_manifest(resolver, config)

        assert result is None

    @pytest.mark.asyncio
    async def test_sync_from_local_file(self, tmp_path):
        """Sync from local manifest file."""
        resolver = Resolver()
        cache_dir = tmp_path / "cache"
        manifest_file = tmp_path / "manifest.yaml"

        # Create manifest file (use oneiric module to pass allowlist)
        manifest_data = {
            "source": "local",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.adapters.bridge:AdapterBridge",
                }
            ],
        }
        manifest_file.write_text(yaml.dump(manifest_data))

        config = RemoteSourceConfig(
            enabled=True,
            manifest_url=str(manifest_file),
            cache_dir=str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )

        result = await sync_remote_manifest(resolver, config)

        assert result is not None
        assert result.registered == 1
        assert result.manifest.source == "local"
        assert result.per_domain == {"adapter": 1}
        assert result.skipped == 0

        # Verify candidate registered
        candidates = resolver.list_active("adapter")
        assert len(candidates) == 1
        assert candidates[0].domain == "adapter"
        assert candidates[0].key == "cache"

    @pytest.mark.asyncio
    async def test_sync_with_invalid_entries(self, tmp_path):
        """Sync skips invalid entries."""
        resolver = Resolver()
        manifest_file = tmp_path / "manifest.yaml"

        manifest_data = {
            "source": "test",
            "entries": [
                {
                    "domain": "invalid_domain",  # Invalid domain
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.adapters.bridge:AdapterBridge",
                },
                {
                    "domain": "adapter",
                    "key": "queue",
                    "provider": "rabbitmq",
                    "factory": "oneiric.adapters.bridge:AdapterBridge",
                },
            ],
        }
        manifest_file.write_text(yaml.dump(manifest_data))

        config = RemoteSourceConfig(
            enabled=True,
            manifest_url=str(manifest_file),
            cache_dir=str(tmp_path / "cache"),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )

        result = await sync_remote_manifest(resolver, config)

        assert result.registered == 1  # Only valid entry
        assert result.skipped == 1  # One invalid entry skipped

    @pytest.mark.asyncio
    async def test_sync_with_artifacts(self, tmp_path):
        """Sync with artifact fetching."""
        resolver = Resolver()
        cache_dir = tmp_path / "cache"
        manifest_file = tmp_path / "manifest.yaml"

        # Create artifact file
        artifact_file = tmp_path / "adapter.py"
        artifact_file.write_text("class RedisCache: pass")
        sha256 = hashlib.sha256(artifact_file.read_bytes()).hexdigest()

        manifest_data = {
            "source": "cdn",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.adapters.bridge:AdapterBridge",
                    "uri": f"file://{artifact_file}",
                    "sha256": sha256,
                }
            ],
        }
        manifest_file.write_text(yaml.dump(manifest_data))

        config = RemoteSourceConfig(
            enabled=True,
            manifest_url=str(manifest_file),
            cache_dir=str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )

        result = await sync_remote_manifest(resolver, config)

        assert result.registered == 1
        assert result.manifest.source == "cdn"

        # Verify artifact cached
        cached_artifact = cache_dir / sha256
        assert cached_artifact.exists()
        assert cached_artifact.read_text() == "class RedisCache: pass"

    @pytest.mark.asyncio
    async def test_sync_local_manifest_requires_allow_file_uris(self, tmp_path):
        """Sync rejects local manifest paths unless explicitly allowed."""
        resolver = Resolver()
        manifest_file = tmp_path / "manifest.yaml"
        manifest_data = {
            "source": "local",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.adapters.bridge:AdapterBridge",
                }
            ],
        }
        manifest_file.write_text(yaml.dump(manifest_data))

        config = RemoteSourceConfig(
            enabled=True,
            manifest_url=str(manifest_file),
            cache_dir=str(tmp_path / "cache"),
            max_retries=1,
            retry_base_delay=0.0,
        )

        with pytest.raises(ValueError, match="local manifest paths disabled"):
            await sync_remote_manifest(resolver, config)

    @pytest.mark.asyncio
    async def test_sync_telemetry_recorded(self, tmp_path):
        """Sync records telemetry."""
        resolver = Resolver()
        cache_dir = tmp_path / "cache"
        manifest_file = tmp_path / "manifest.yaml"

        manifest_data = {
            "source": "test",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.adapters.bridge:AdapterBridge",
                }
            ],
        }
        manifest_file.write_text(yaml.dump(manifest_data))

        config = RemoteSourceConfig(
            enabled=True,
            manifest_url=str(manifest_file),
            cache_dir=str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )

        await sync_remote_manifest(resolver, config)

        # Check telemetry file created
        telemetry_file = cache_dir / "remote_status.json"
        assert telemetry_file.exists()

        telemetry_data = json.loads(telemetry_file.read_text())
        assert telemetry_data["last_success_at"] is not None
        assert telemetry_data["last_registered"] == 1
        assert telemetry_data["last_source"] == "test"
        assert telemetry_data["consecutive_failures"] == 0
