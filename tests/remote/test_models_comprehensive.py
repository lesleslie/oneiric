"""Comprehensive tests for oneiric.remote.models data structures.

This file is intentionally a NEW companion to tests/unit/test_remote_models.py
and the legacy tests/remote/test_models.py. It expands coverage of:

- CapabilitySecurityProfile defaults and JSON round-trip
- CapabilityDescriptor schema/metadata/security optional fields
- RemoteManifestEntry: every optional field, the capabilities validator's
  accepted and rejected shapes, the capability_names property, and
  capability_payloads() payload-cleansing behaviour
- ManifestSignature defaults
- RemoteManifest single/multi-entry/multi-signature JSON round-trip

Property-based tests (hypothesis) verify normalization idempotence and
entry round-trip.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
        assert p.encryption is None
        assert p.signature_required is False
        assert p.audience == []
        assert p.notes is None

    def test_custom_values(self) -> None:
        p = CapabilitySecurityProfile(
            classification="confidential",
            auth_required=False,
            scopes=["read", "write"],
            encryption="aes-256-gcm",
            signature_required=True,
            audience=["service-a", "service-b"],
            notes="restricted to internal callers",
        )
        assert p.classification == "confidential"
        assert p.auth_required is False
        assert p.scopes == ["read", "write"]
        assert p.encryption == "aes-256-gcm"
        assert p.signature_required is True
        assert p.audience == ["service-a", "service-b"]
        assert p.notes == "restricted to internal callers"

    def test_scopes_and_audience_default_to_independent_lists(self) -> None:
        # Field default_factory=[] must NOT share state between instances.
        a = CapabilitySecurityProfile()
        b = CapabilitySecurityProfile()
        a.scopes.append("x")
        a.audience.append("y")
        assert b.scopes == []
        assert b.audience == []

    def test_json_round_trip(self) -> None:
        original = CapabilitySecurityProfile(
            classification="internal",
            scopes=["s1", "s2"],
            audience=["aud-a"],
            notes="test",
        )
        encoded = original.model_dump_json()
        decoded = CapabilitySecurityProfile.model_validate_json(encoded)
        assert decoded == original
        assert decoded.classification == "internal"
        assert decoded.scopes == ["s1", "s2"]
        assert decoded.audience == ["aud-a"]
        assert decoded.notes == "test"

    def test_signature_required_default_is_false(self) -> None:
        # spot-check the spec entry that signature_required defaults to False
        p = CapabilitySecurityProfile()
        assert p.signature_required is False

    def test_encryption_default_is_none(self) -> None:
        # spec says encryption=None
        p = CapabilitySecurityProfile()
        assert p.encryption is None


# ---------------------------------------------------------------------------
# CapabilityDescriptor
# ---------------------------------------------------------------------------


class TestCapabilityDescriptor:
    def test_minimal_construction(self) -> None:
        d = CapabilityDescriptor(name="health_check")
        assert d.name == "health_check"
        assert d.description is None
        assert d.event_types == []
        assert d.payload_schema is None
        assert d.schema_format is None
        assert d.security is None
        assert d.metadata == {}

    def test_payload_schema_dict_form(self) -> None:
        schema = {"type": "object", "required": ["x"]}
        d = CapabilityDescriptor(name="x", payload_schema=schema)
        assert d.payload_schema == schema
        assert isinstance(d.payload_schema, dict)

    def test_payload_schema_string_form(self) -> None:
        # payload_schema is typed dict|str|None; a string is valid
        d = CapabilityDescriptor(name="x", payload_schema="json-schema-blob")
        assert d.payload_schema == "json-schema-blob"

    def test_metadata_default_is_empty_dict(self) -> None:
        d = CapabilityDescriptor(name="x")
        assert d.metadata == {}
        d2 = CapabilityDescriptor(name="y")
        d.metadata["k"] = "v"
        # default_factory isolation
        assert d2.metadata == {}

    def test_security_none(self) -> None:
        d = CapabilityDescriptor(name="x", security=None)
        assert d.security is None

    def test_security_present(self) -> None:
        sec = CapabilitySecurityProfile(classification="public")
        d = CapabilityDescriptor(name="x", security=sec)
        assert d.security is not None
        assert d.security.classification == "public"

    def test_full_construction(self) -> None:
        sec = CapabilitySecurityProfile(scopes=["read"])
        d = CapabilityDescriptor(
            name="cache",
            description="Cache adapter",
            event_types=["cache.hit", "cache.miss"],
            payload_schema={"type": "object"},
            schema_format="json-schema",
            security=sec,
            metadata={"team": "platform"},
        )
        assert d.name == "cache"
        assert d.description == "Cache adapter"
        assert d.event_types == ["cache.hit", "cache.miss"]
        assert d.payload_schema == {"type": "object"}
        assert d.schema_format == "json-schema"
        assert d.security is not None
        assert d.security.scopes == ["read"]
        assert d.metadata == {"team": "platform"}


# ---------------------------------------------------------------------------
# RemoteManifestEntry
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    domain: str = "adapter",
    key: str = "cache",
    provider: str = "redis",
    factory: str = "oneiric.adapters:RedisAdapter",
    **kwargs: object,
) -> RemoteManifestEntry:
    """Factory producing a fresh RemoteManifestEntry for mutation-safety."""
    return RemoteManifestEntry(
        domain=domain,
        key=key,
        provider=provider,
        factory=factory,
        **kwargs,
    )


class TestRemoteManifestEntry:
    def test_minimal(self) -> None:
        e = _make_entry()
        assert e.domain == "adapter"
        assert e.key == "cache"
        assert e.provider == "redis"
        assert e.factory == "oneiric.adapters:RedisAdapter"
        assert e.uri is None
        assert e.sha256 is None
        assert e.stack_level is None
        assert e.priority is None
        assert e.version is None
        assert e.metadata == {}
        assert e.capabilities == []
        assert e.owner is None
        assert e.requires_secrets is False
        assert e.settings_model is None
        assert e.side_effect_free is False
        assert e.timeout_seconds is None
        assert e.retry_policy is None
        assert e.requires == []
        assert e.conflicts_with == []
        assert e.python_version is None
        # os_platform is list[str] | None — NOT defaulted to []
        assert e.os_platform is None
        assert e.license is None
        assert e.documentation_url is None
        assert e.event_topics is None
        assert e.event_max_concurrency is None
        assert e.event_filters is None
        assert e.event_priority is None
        assert e.event_fanout_policy is None
        assert e.dag is None

    def test_uri_and_sha256(self) -> None:
        e = _make_entry(
            uri="https://cdn.example.com/pkg-1.0.whl",
            sha256="abcdef0123456789",
        )
        assert e.uri == "https://cdn.example.com/pkg-1.0.whl"
        assert e.sha256 == "abcdef0123456789"

    def test_stack_level_and_priority_and_version(self) -> None:
        e = _make_entry(stack_level=3, priority=100, version="1.2.3")
        assert e.stack_level == 3
        assert e.priority == 100
        assert e.version == "1.2.3"

    def test_metadata(self) -> None:
        e = _make_entry(metadata={"region": "us-east-1", "tier": "prod"})
        assert e.metadata == {"region": "us-east-1", "tier": "prod"}

    def test_owner_requires_secrets_settings_model(self) -> None:
        e = _make_entry(
            owner="platform-team",
            requires_secrets=True,
            settings_model="myapp.settings:Settings",
        )
        assert e.owner == "platform-team"
        assert e.requires_secrets is True
        assert e.settings_model == "myapp.settings:Settings"

    def test_side_effect_free_timeout_retry(self) -> None:
        e = _make_entry(
            side_effect_free=True,
            timeout_seconds=12.5,
            retry_policy={"max_attempts": 3, "backoff": "exponential"},
        )
        assert e.side_effect_free is True
        assert e.timeout_seconds == 12.5
        assert e.retry_policy == {"max_attempts": 3, "backoff": "exponential"}

    def test_requires_and_conflicts_with(self) -> None:
        e = _make_entry(requires=["db", "cache"], conflicts_with=["legacy"])
        assert e.requires == ["db", "cache"]
        assert e.conflicts_with == ["legacy"]

    def test_python_version_and_os_platform(self) -> None:
        # os_platform must be settable as a list (not silently defaulting)
        e = _make_entry(
            python_version=">=3.11",
            os_platform=["linux", "darwin"],
        )
        assert e.python_version == ">=3.11"
        assert e.os_platform == ["linux", "darwin"]

    def test_os_platform_default_is_none(self) -> None:
        # hazard: do not confuse with audience/scopes which default to []
        e = _make_entry()
        assert e.os_platform is None
        # ...while requires/conflicts_with do default to []
        assert e.requires == []
        assert e.conflicts_with == []

    def test_license_and_documentation_url(self) -> None:
        e = _make_entry(
            license="Apache-2.0",
            documentation_url="https://docs.example.com/cache",
        )
        assert e.license == "Apache-2.0"
        assert e.documentation_url == "https://docs.example.com/cache"

    def test_event_fields(self) -> None:
        e = _make_entry(
            event_topics=["topic.a", "topic.b"],
            event_max_concurrency=4,
            event_filters=[{"type": "match", "key": "x"}],
            event_priority=50,
            event_fanout_policy="broadcast",
        )
        assert e.event_topics == ["topic.a", "topic.b"]
        assert e.event_max_concurrency == 4
        assert e.event_filters == [{"type": "match", "key": "x"}]
        assert e.event_priority == 50
        assert e.event_fanout_policy == "broadcast"

    def test_event_field_defaults_are_none(self) -> None:
        # All event_* fields default to None, not []
        e = _make_entry()
        assert e.event_topics is None
        assert e.event_max_concurrency is None
        assert e.event_filters is None
        assert e.event_priority is None
        assert e.event_fanout_policy is None

    def test_dag(self) -> None:
        dag = {"deps": ["a", "b"], "parallel": True}
        e = _make_entry(dag=dag)
        assert e.dag == dag

    # ---- capability normalization (validator accepted forms) ----------------

    def test_capability_normalization_from_none(self) -> None:
        e = _make_entry(capabilities=None)
        assert e.capabilities == []
        assert e.capability_names == []

    def test_capability_normalization_from_single_descriptor(self) -> None:
        cap = CapabilityDescriptor(name="x", description="d")
        e = _make_entry(capabilities=[cap])
        assert e.capabilities == [cap]
        assert e.capability_names == ["x"]

    def test_capability_normalization_from_single_string(self) -> None:
        e = _make_entry(capabilities=["only_one"])
        assert len(e.capabilities) == 1
        assert isinstance(e.capabilities[0], CapabilityDescriptor)
        assert e.capabilities[0].name == "only_one"
        assert e.capabilities[0].description is None
        assert e.capability_names == ["only_one"]

    def test_capability_normalization_from_single_dict(self) -> None:
        e = _make_entry(capabilities=[{"name": "from_dict", "description": "hi"}])
        assert len(e.capabilities) == 1
        assert isinstance(e.capabilities[0], CapabilityDescriptor)
        assert e.capabilities[0].name == "from_dict"
        assert e.capabilities[0].description == "hi"
        assert e.capability_names == ["from_dict"]

    def test_capability_normalization_from_mixed_list(self) -> None:
        e = _make_entry(
            capabilities=[
                "string_cap",
                {"name": "dict_cap"},
                CapabilityDescriptor(name="descriptor_cap"),
            ],
        )
        assert e.capability_names == ["string_cap", "dict_cap", "descriptor_cap"]
        for c in e.capabilities:
            assert isinstance(c, CapabilityDescriptor)

    # ---- capability normalization (validator rejected forms) ----------------

    def test_capability_normalization_empty_string_accepted_as_descriptor(
        self,
    ) -> None:
        # Spec deviation note: the validator does NOT reject "" (it wraps it
        # in CapabilityDescriptor(name="")). Only dicts missing 'name' raise.
        # This test pins the current (lenient) behaviour.
        e = _make_entry(capabilities=[""])
        assert len(e.capabilities) == 1
        assert e.capabilities[0].name == ""

    def test_capability_normalization_rejects_dict_missing_name(self) -> None:
        with pytest.raises(ValueError, match="missing 'name'"):
            _make_entry(capabilities=[{"description": "no name field"}])

    def test_capability_normalization_rejects_int(self) -> None:
        with pytest.raises(TypeError, match="capabilities must be"):
            _make_entry(capabilities=[42])

    def test_capability_normalization_rejects_none_item(self) -> None:
        with pytest.raises(TypeError, match="capabilities must be"):
            _make_entry(capabilities=[None])

    # ---- capability_names + capability_payloads ---------------------------

    def test_capability_names_returns_list_of_names(self) -> None:
        e = _make_entry(
            capabilities=[
                "a",
                {"name": "b"},
                CapabilityDescriptor(name="c"),
            ],
        )
        names = e.capability_names
        assert isinstance(names, list)
        assert names == ["a", "b", "c"]

    def test_capability_payloads_excludes_none_and_empty(self) -> None:
        e = _make_entry(
            capabilities=[
                # bare string -> only name set, everything else None/empty
                "bare",
                # explicitly empty description/event_types/payload_schema/metadata
                CapabilityDescriptor(
                    name="empty_caps",
                    description=None,
                    event_types=[],
                    payload_schema=None,
                    schema_format=None,
                    metadata={},
                ),
            ],
        )
        payloads = e.capability_payloads()
        assert len(payloads) == 2

        # bare descriptor should only contain "name" (and no other key)
        assert payloads[0] == {"name": "bare"}

        # empty descriptor — name must remain; description/event_types/
        # payload_schema/schema_format/metadata are dropped when None/empty
        assert "name" in payloads[1]
        assert payloads[1]["name"] == "empty_caps"
        assert "description" not in payloads[1]
        assert "event_types" not in payloads[1]
        assert "payload_schema" not in payloads[1]
        assert "schema_format" not in payloads[1]
        assert "metadata" not in payloads[1]
        assert "security" not in payloads[1]

    def test_capability_payloads_includes_security_when_present(self) -> None:
        sec = CapabilitySecurityProfile(classification="public", scopes=["read"])
        e = _make_entry(
            capabilities=[
                CapabilityDescriptor(
                    name="with_security",
                    description="d",
                    security=sec,
                ),
            ],
        )
        payloads = e.capability_payloads()
        assert len(payloads) == 1
        assert payloads[0]["name"] == "with_security"
        assert payloads[0]["description"] == "d"
        assert "security" in payloads[0]
        assert payloads[0]["security"]["classification"] == "public"
        assert payloads[0]["security"]["scopes"] == ["read"]

    def test_capability_payloads_omits_security_when_none(self) -> None:
        # capability_payloads pops security when descriptor.security is None
        e = _make_entry(
            capabilities=[CapabilityDescriptor(name="no_security")],
        )
        payloads = e.capability_payloads()
        assert payloads[0] == {"name": "no_security"}
        assert "security" not in payloads[0]


# ---------------------------------------------------------------------------
# ManifestSignature
# ---------------------------------------------------------------------------


class TestManifestSignature:
    def test_defaults(self) -> None:
        s = ManifestSignature(signature="abc")
        assert s.signature == "abc"
        assert s.algorithm == "ed25519"
        assert s.key_id is None

    def test_custom_algorithm(self) -> None:
        s = ManifestSignature(signature="sig", algorithm="rsa-pss")
        assert s.algorithm == "rsa-pss"

    def test_custom_key_id(self) -> None:
        s = ManifestSignature(signature="sig", key_id="key-2026-01")
        assert s.key_id == "key-2026-01"

    def test_signature_field_is_required(self) -> None:
        with pytest.raises(Exception):
            ManifestSignature()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# RemoteManifest
# ---------------------------------------------------------------------------


class TestRemoteManifest:
    def test_empty_entries_default(self) -> None:
        m = RemoteManifest()
        assert m.source == "remote"
        assert m.entries == []
        assert m.signature is None
        assert m.signature_algorithm == "ed25519"
        assert m.signatures == []
        assert m.signed_at is None
        assert m.expires_at is None

    def test_single_entry(self) -> None:
        entry = _make_entry()
        m = RemoteManifest(entries=[entry])
        assert len(m.entries) == 1
        assert m.entries[0].domain == "adapter"

    def test_multi_entry(self) -> None:
        e1 = _make_entry(key="cache", provider="redis")
        e2 = _make_entry(domain="service", key="auth", provider="google", factory="f:Auth")
        e3 = _make_entry(
            domain="adapter",
            key="queue",
            provider="rabbit",
            factory="f:Rabbit",
        )
        m = RemoteManifest(entries=[e1, e2, e3])
        assert len(m.entries) == 3
        assert [e.domain for e in m.entries] == ["adapter", "service", "adapter"]
        assert [e.key for e in m.entries] == ["cache", "auth", "queue"]
        assert [e.provider for e in m.entries] == ["redis", "google", "rabbit"]

    def test_multi_signature(self) -> None:
        sigs = [
            ManifestSignature(signature="s1", algorithm="ed25519", key_id="k1"),
            ManifestSignature(signature="s2", algorithm="rsa-pss", key_id="k2"),
        ]
        m = RemoteManifest(signatures=sigs)
        assert len(m.signatures) == 2
        assert m.signatures[0].signature == "s1"
        assert m.signatures[0].algorithm == "ed25519"
        assert m.signatures[0].key_id == "k1"
        assert m.signatures[1].key_id == "k2"

    def test_source_default_is_remote(self) -> None:
        m = RemoteManifest()
        assert m.source == "remote"

    def test_signature_algorithm_default_is_ed25519(self) -> None:
        m = RemoteManifest()
        assert m.signature_algorithm == "ed25519"

    def test_source_override(self) -> None:
        m = RemoteManifest(source="local-mirror")
        assert m.source == "local-mirror"

    def test_signature_algorithm_override(self) -> None:
        m = RemoteManifest(signature_algorithm="rsa-pss")
        assert m.signature_algorithm == "rsa-pss"

    def test_json_round_trip(self) -> None:
        original = RemoteManifest(
            source="production",
            entries=[_make_entry(), _make_entry(key="auth", provider="google", factory="f:Auth")],
            signature="base64-sig",
            signature_algorithm="ed25519",
            signatures=[
                ManifestSignature(signature="s1", key_id="k1"),
            ],
            signed_at="2026-06-05T00:00:00Z",
            expires_at="2026-07-05T00:00:00Z",
        )
        encoded = original.model_dump_json()
        decoded = RemoteManifest.model_validate_json(encoded)
        assert decoded == original
        assert decoded.source == "production"
        assert len(decoded.entries) == 2
        assert decoded.entries[0].key == "cache"
        assert decoded.entries[1].key == "auth"
        assert decoded.signature == "base64-sig"
        assert decoded.signed_at == "2026-06-05T00:00:00Z"
        assert decoded.expires_at == "2026-07-05T00:00:00Z"
        assert len(decoded.signatures) == 1
        assert decoded.signatures[0].signature == "s1"

    def test_signed_at_and_expires_at_are_iso_strings(self) -> None:
        m = RemoteManifest(
            signed_at="2026-06-05T12:34:56Z",
            expires_at="2026-12-05T00:00:00Z",
        )
        assert m.signed_at == "2026-06-05T12:34:56Z"
        assert m.expires_at == "2026-12-05T00:00:00Z"
        # Round-trip through plain json.dumps to ensure strings, not datetime
        blob = json.loads(m.model_dump_json())
        assert blob["signed_at"] == "2026-06-05T12:34:56Z"
        assert blob["expires_at"] == "2026-12-05T00:00:00Z"

    def test_serialization_includes_all_top_level_keys(self) -> None:
        m = RemoteManifest(entries=[_make_entry()])
        blob = json.loads(m.model_dump_json())
        assert set(blob.keys()) == {
            "source",
            "entries",
            "signature",
            "signature_algorithm",
            "signatures",
            "signed_at",
            "expires_at",
        }


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestManifestIntegration:
    def test_three_distinct_entries_preserved(self) -> None:
        e1 = _make_entry(domain="adapter", key="cache", provider="redis", factory="f:Cache")
        e2 = _make_entry(
            domain="service",
            key="auth",
            provider="google",
            factory="f:Auth",
        )
        e3 = _make_entry(
            domain="adapter",
            key="queue",
            provider="rabbit",
            factory="f:Queue",
        )
        manifest = RemoteManifest(
            source="prod",
            entries=[e1, e2, e3],
            signatures=[
                ManifestSignature(signature="sig-a", key_id="key-a"),
            ],
            signed_at="2026-06-05T00:00:00Z",
        )
        assert len(manifest.entries) == 3
        # entry list preserved with distinct (domain, key, provider) tuples
        tuples = [(e.domain, e.key, e.provider) for e in manifest.entries]
        assert tuples == [
            ("adapter", "cache", "redis"),
            ("service", "auth", "google"),
            ("adapter", "queue", "rabbit"),
        ]
        # aggregation of capability_names across entries
        for e in manifest.entries:
            e.capabilities.append(CapabilityDescriptor(name=f"{e.key}.check"))
        all_names = [name for e in manifest.entries for name in e.capability_names]
        assert all_names == ["cache.check", "auth.check", "queue.check"]

    def test_capability_names_aggregate_across_entries(self) -> None:
        e1 = _make_entry(
            domain="adapter",
            key="a",
            provider="p1",
            factory="f:A",
            capabilities=["a.health", "a.metrics"],
        )
        e2 = _make_entry(
            domain="adapter",
            key="b",
            provider="p2",
            factory="f:B",
            capabilities=[{"name": "b.health"}],
        )
        e3 = _make_entry(
            domain="service",
            key="c",
            provider="p3",
            factory="f:C",
            capabilities=[CapabilityDescriptor(name="c.health")],
        )
        manifest = RemoteManifest(entries=[e1, e2, e3])
        aggregated = [name for e in manifest.entries for name in e.capability_names]
        assert aggregated == [
            "a.health",
            "a.metrics",
            "b.health",
            "c.health",
        ]


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

# Strategies reused by both property tests.

_valid_capability_inputs = st.lists(
    st.one_of(
        st.text(min_size=1, max_size=20).map(lambda n: {"name": n}),
        st.just("a_string_capability"),
    ),
    max_size=5,
)


class TestPropertyBased:
    @given(_valid_capability_inputs)
    @settings(max_examples=30)
    def test_capability_normalization_idempotent(self, inputs: list[object]) -> None:
        """Normalizing entry.capabilities a second time yields the same list.

        Build an entry from arbitrary (but valid) inputs, capture the resulting
        list of CapabilityDescriptor instances, then "renormalize" by feeding
        that list through the validator path and check it round-trips.
        """
        entry = _make_entry(capabilities=inputs)  # type: ignore[arg-type]
        normalized_first = list(entry.capabilities)

        # Re-feed the list of descriptors through the validator (mode='before')
        # by constructing a new entry with capabilities=normalized_first.
        entry2 = _make_entry(capabilities=normalized_first)
        normalized_second = list(entry2.capabilities)

        assert len(normalized_first) == len(normalized_second)
        for a, b in zip(normalized_first, normalized_second, strict=True):
            assert isinstance(a, CapabilityDescriptor)
            assert isinstance(b, CapabilityDescriptor)
            assert a.name == b.name

    @given(
        stack_level=st.integers(min_value=0, max_value=1000),
        priority=st.integers(min_value=0, max_value=1000),
        version=st.text(min_size=1, max_size=10),
    )
    @settings(max_examples=30)
    def test_entry_round_trip(
        self,
        stack_level: int,
        priority: int,
        version: str,
    ) -> None:
        """RemoteManifestEntry(...).model_dump() -> RemoteManifestEntry(**dump)."""
        original = _make_entry(
            stack_level=stack_level,
            priority=priority,
            version=version,
            metadata={"k": "v"},
        )
        dumped = original.model_dump()
        # Re-construct and compare — the round-trip must preserve the data
        # that the user supplied. Pydantic v2 may add defaults for unset
        # fields, so we compare the dumped model against the rebuilt one.
        rebuilt = RemoteManifestEntry(**dumped)
        assert rebuilt.model_dump() == dumped
        # And the user-supplied values survive
        assert rebuilt.stack_level == stack_level
        assert rebuilt.priority == priority
        assert rebuilt.version == version
        assert rebuilt.metadata == {"k": "v"}
