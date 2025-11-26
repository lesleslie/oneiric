"""Tests for remote manifest data models."""

from __future__ import annotations

import pytest

from oneiric.remote.models import RemoteManifest, RemoteManifestEntry


class TestRemoteManifestEntry:
    """Test RemoteManifestEntry Pydantic model."""

    def test_entry_minimal_fields(self):
        """RemoteManifestEntry requires domain, key, provider, factory."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="myapp.adapters:RedisCache",
        )

        assert entry.domain == "adapter"
        assert entry.key == "cache"
        assert entry.provider == "redis"
        assert entry.factory == "myapp.adapters:RedisCache"
        assert entry.uri is None
        assert entry.sha256 is None
        assert entry.stack_level is None
        assert entry.priority is None
        assert entry.version is None
        assert entry.metadata == {}

    def test_entry_all_fields(self):
        """RemoteManifestEntry supports all optional fields."""
        entry = RemoteManifestEntry(
            domain="service",
            key="payment",
            provider="stripe",
            factory="myapp.services:StripePayment",
            uri="https://cdn.example.com/stripe-v1.0.0.whl",
            sha256="abc123def456",
            stack_level=10,
            priority=5,
            version="1.0.0",
            metadata={"region": "us-east-1", "tier": "production"},
        )

        assert entry.uri == "https://cdn.example.com/stripe-v1.0.0.whl"
        assert entry.sha256 == "abc123def456"
        assert entry.stack_level == 10
        assert entry.priority == 5
        assert entry.version == "1.0.0"
        assert entry.metadata == {"region": "us-east-1", "tier": "production"}

    def test_entry_validation_requires_domain(self):
        """RemoteManifestEntry requires domain field."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            RemoteManifestEntry(
                key="cache",
                provider="redis",
                factory="myapp.adapters:RedisCache",
            )

    def test_entry_validation_requires_key(self):
        """RemoteManifestEntry requires key field."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            RemoteManifestEntry(
                domain="adapter",
                provider="redis",
                factory="myapp.adapters:RedisCache",
            )

    def test_entry_validation_requires_provider(self):
        """RemoteManifestEntry requires provider field."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            RemoteManifestEntry(
                domain="adapter",
                key="cache",
                factory="myapp.adapters:RedisCache",
            )

    def test_entry_validation_requires_factory(self):
        """RemoteManifestEntry requires factory field."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            RemoteManifestEntry(
                domain="adapter",
                key="cache",
                provider="redis",
            )


class TestRemoteManifest:
    """Test RemoteManifest Pydantic model."""

    def test_manifest_minimal(self):
        """RemoteManifest can be created with no entries."""
        manifest = RemoteManifest()

        assert manifest.source == "remote"
        assert manifest.entries == []
        assert manifest.signature is None
        assert manifest.signature_algorithm == "ed25519"

    def test_manifest_with_entries(self):
        """RemoteManifest supports list of entries."""
        entry1 = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="myapp.adapters:RedisCache",
        )
        entry2 = RemoteManifestEntry(
            domain="service",
            key="payment",
            provider="stripe",
            factory="myapp.services:StripePayment",
        )

        manifest = RemoteManifest(
            source="production",
            entries=[entry1, entry2],
        )

        assert manifest.source == "production"
        assert len(manifest.entries) == 2
        assert manifest.entries[0].domain == "adapter"
        assert manifest.entries[1].domain == "service"

    def test_manifest_with_signature(self):
        """RemoteManifest supports signature fields."""
        manifest = RemoteManifest(
            source="signed",
            signature="base64-encoded-signature-here",
            signature_algorithm="ed25519",
        )

        assert manifest.signature == "base64-encoded-signature-here"
        assert manifest.signature_algorithm == "ed25519"

    def test_manifest_entry_serialization(self):
        """RemoteManifestEntry serializes to dict."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="myapp.adapters:RedisCache",
            stack_level=10,
            metadata={"timeout": 30},
        )

        data = entry.model_dump()

        assert data["domain"] == "adapter"
        assert data["key"] == "cache"
        assert data["provider"] == "redis"
        assert data["factory"] == "myapp.adapters:RedisCache"
        assert data["stack_level"] == 10
        assert data["metadata"] == {"timeout": 30}

    def test_manifest_serialization(self):
        """RemoteManifest serializes to dict."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="myapp.adapters:RedisCache",
        )
        manifest = RemoteManifest(
            source="test",
            entries=[entry],
            signature="test-signature",
        )

        data = manifest.model_dump()

        assert data["source"] == "test"
        assert len(data["entries"]) == 1
        assert data["entries"][0]["domain"] == "adapter"
        assert data["signature"] == "test-signature"
        assert data["signature_algorithm"] == "ed25519"
