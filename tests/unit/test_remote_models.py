"""Tests for oneiric.remote.models data structures."""

from __future__ import annotations

import pytest

from oneiric.remote.models import (
    CapabilityDescriptor,
    CapabilitySecurityProfile,
    ManifestSignature,
    RemoteManifest,
    RemoteManifestEntry,
)

# ---------------------------------------------------------------------------
# CapabilitySecurityProfile
# ---------------------------------------------------------------------------

class TestCapabilitySecurityProfile:
    def test_defaults(self) -> None:
        p = CapabilitySecurityProfile()
        assert p.classification is None
        assert p.auth_required is True
        assert p.scopes == []
        assert p.signature_required is False
        assert p.audience == []

    def test_custom(self) -> None:
        p = CapabilitySecurityProfile(
            classification="confidential",
            scopes=["read", "write"],
            encryption="aes256",
        )
        assert p.classification == "confidential"
        assert p.scopes == ["read", "write"]


# ---------------------------------------------------------------------------
# CapabilityDescriptor
# ---------------------------------------------------------------------------

class TestCapabilityDescriptor:
    def test_minimal(self) -> None:
        d = CapabilityDescriptor(name="health_check")
        assert d.name == "health_check"
        assert d.description is None
        assert d.event_types == []
        assert d.metadata == {}

    def test_full(self) -> None:
        security = CapabilitySecurityProfile(classification="public")
        d = CapabilityDescriptor(
            name="cache",
            description="Redis cache adapter",
            event_types=["cache.hit", "cache.miss"],
            payload_schema={"type": "object"},
            schema_format="json-schema",
            security=security,
        )
        assert d.security.classification == "public"

    def test_from_dict(self) -> None:
        d = CapabilityDescriptor(
            name="test",
            description="A test capability",
            metadata={"key": "val"},
        )
        assert d.description == "A test capability"


# ---------------------------------------------------------------------------
# RemoteManifestEntry
# ---------------------------------------------------------------------------

class TestRemoteManifestEntry:
    def test_minimal(self) -> None:
        e = RemoteManifestEntry(
            domain="adapter", key="cache", provider="redis", factory="oneiric.adapters:RedisAdapter",
        )
        assert e.domain == "adapter"
        assert e.key == "cache"
        assert e.capabilities == []
        assert e.requires == []

    def test_full(self) -> None:
        e = RemoteManifestEntry(
            domain="service", key="auth", provider="google",
            factory="oneiric.services:AuthService",
            version="2.0.0", priority=10, stack_level=1,
            capabilities=[CapabilityDescriptor(name="oauth")],
            requires=["cache"], conflicts_with=["legacy"],
            python_version=">=3.11",
        )
        assert e.capability_names == ["oauth"]
        assert e.requires == ["cache"]
        assert e.conflicts_with == ["legacy"]

    def test_capability_normalization_from_string(self) -> None:
        e = RemoteManifestEntry(
            domain="adapter", key="x", provider="p", factory="f:f",
            capabilities=["cap_a", "cap_b"],
        )
        assert e.capability_names == ["cap_a", "cap_b"]
        assert all(isinstance(c, CapabilityDescriptor) for c in e.capabilities)

    def test_capability_normalization_from_dict(self) -> None:
        e = RemoteManifestEntry(
            domain="adapter", key="x", provider="p", factory="f:f",
            capabilities=[{"name": "a", "description": "b"}],
        )
        assert e.capability_names == ["a"]

    def test_capability_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="missing 'name'"):
            RemoteManifestEntry(
                domain="adapter", key="x", provider="p", factory="f:f",
                capabilities=[{"description": "no name"}],
            )

    def test_capability_none(self) -> None:
        e = RemoteManifestEntry(
            domain="adapter", key="x", provider="p", factory="f:f",
            capabilities=None,
        )
        assert e.capabilities == []

    def test_capability_invalid_type_raises(self) -> None:
        with pytest.raises(TypeError, match="capabilities must be"):
            RemoteManifestEntry(
                domain="adapter", key="x", provider="p", factory="f:f",
                capabilities=[42],
            )

    def test_capability_payloads(self) -> None:
        e = RemoteManifestEntry(
            domain="adapter", key="x", provider="p", factory="f:f",
            capabilities=[
                CapabilityDescriptor(name="a", description="desc"),
                "bare_string",
            ],
        )
        payloads = e.capability_payloads()
        assert len(payloads) == 2
        assert payloads[0]["name"] == "a"
        assert payloads[0]["description"] == "desc"
        assert payloads[1]["name"] == "bare_string"


# ---------------------------------------------------------------------------
# ManifestSignature
# ---------------------------------------------------------------------------

class TestManifestSignature:
    def test_defaults(self) -> None:
        s = ManifestSignature(signature="abc123")
        assert s.signature == "abc123"
        assert s.algorithm == "ed25519"
        assert s.key_id is None

    def test_custom(self) -> None:
        s = ManifestSignature(signature="sig", algorithm="rsa", key_id="key1")
        assert s.algorithm == "rsa"
        assert s.key_id == "key1"


# ---------------------------------------------------------------------------
# RemoteManifest
# ---------------------------------------------------------------------------

class TestRemoteManifest:
    def test_defaults(self) -> None:
        m = RemoteManifest()
        assert m.source == "remote"
        assert m.entries == []
        assert m.signatures == []

    def test_with_entries(self) -> None:
        entry = RemoteManifestEntry(
            domain="adapter", key="cache", provider="redis", factory="f:f",
        )
        m = RemoteManifest(entries=[entry])
        assert len(m.entries) == 1
        assert m.entries[0].domain == "adapter"

    def test_with_signatures(self) -> None:
        sig = ManifestSignature(signature="s1")
        m = RemoteManifest(signatures=[sig])
        assert len(m.signatures) == 1
        assert m.signatures[0].signature == "s1"
