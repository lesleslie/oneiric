"""Tests for the UUID7 identifier substrate (oneiric.core.ids).

Covers the public surface:
    generate_id, is_uuid7, is_valid_id,
    extract_timestamp_ms, extract_timestamp_seconds,
    ConfigTraceability.

The legacy 26-char ULID read-time acceptance path was removed in the
UUID7-only migration (Phase 2 / REQ-012): the substrate is UUID7-only, so a
legacy ULID must be re-encoded before it is passed in. The tests below pin
that rejection rather than the acceptance the module used to offer.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from oneiric.core.ids import (
    ConfigTraceability,
    extract_timestamp_ms,
    extract_timestamp_seconds,
    generate_id,
    is_uuid7,
    is_valid_id,
)

# Crockford Base32 alphabet: 0-9, A-H, J-K, M-N, P-T, V-Z (32 chars,
# no I/L/O/U). Uppercase, the conventional ULID rendering.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _ulid_rendering(value: int) -> str:
    """Render a 128-bit int as a 26-char Crockford Base32 ULID."""
    out: list[str] = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def _real_ulid_hex() -> str:
    """Build a real 26-char Crockford ULID from a uuid7 int (same bit layout)."""
    from uuid import uuid7

    return _ulid_rendering(uuid7().int)


_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


class TestGenerateId:
    def test_returns_32_lowercase_hex(self) -> None:
        gid = generate_id()
        assert len(gid) == 32
        assert _HEX_RE.match(gid), f"not 32 lowercase hex: {gid!r}"

    def test_version_is_7(self) -> None:
        gid = generate_id()
        assert UUID(gid).version == 7

    def test_two_calls_produce_different_values(self) -> None:
        # High-entropy rand bits make collisions astronomically unlikely.
        assert generate_id() != generate_id()


class TestIsUuid7:
    def test_accepts_canonical_uuid7(self) -> None:
        assert is_uuid7(generate_id())

    def test_rejects_legacy_ulid(self) -> None:
        assert not is_uuid7(_real_ulid_hex())

    def test_rejects_plan_example_short_ulid(self) -> None:
        # The plan's example "01ARZ3NDEKTS6PQRYF" is 18 chars, not a real
        # ULID (which is 26) and not a UUID7 (which is 32). It is neither.
        assert not is_uuid7("01ARZ3NDEKTS6PQRYF")

    def test_rejects_non_string(self) -> None:
        assert not is_uuid7(123)
        assert not is_uuid7(None)
        assert not is_uuid7(b"018f3e7a5b1c4d2e9f0a8b7c6d5e4f3a")

    def test_rejects_empty(self) -> None:
        assert not is_uuid7("")

    def test_rejects_wrong_length(self) -> None:
        assert not is_uuid7("a" * 31)
        assert not is_uuid7("a" * 33)

    def test_rejects_non_hex_characters(self) -> None:
        # 32 chars but with non-hex; also note 'g' is not in hex alphabet.
        assert not is_uuid7("g" * 32)
        # UUIDs with capital letters (canonical UUID7 hex is lowercase).
        assert not is_uuid7(generate_id().upper())

    def test_rejects_uuid_with_v4_version_nibble(self) -> None:
        # Hand-rolled v4-style UUID7 (version nibble 4) is rejected.
        assert not is_uuid7("018f3e7a5b1c4d2e9f0a8b7c6d5e4f3a")


class TestIsValidId:
    def test_accepts_uuid7(self) -> None:
        assert is_valid_id(generate_id())

    def test_rejects_legacy_ulid(self) -> None:
        # UUID7-only substrate: the read-time ULID acceptance path was
        # removed in the Phase 2 migration (b48fe18). A legacy ULID must
        # be re-encoded to UUID7 before it is passed in.
        assert not is_valid_id(_real_ulid_hex())

    def test_rejects_short_ulid_example(self) -> None:
        # 18-char placeholder from the plan is not a valid ULID.
        assert not is_valid_id("01ARZ3NDEKTS6PQRYF")

    def test_rejects_garbage(self) -> None:
        assert not is_valid_id("not-an-id")
        assert not is_valid_id("")
        assert not is_valid_id(None)
        assert not is_valid_id(42)


class TestExtractTimestampMs:
    def test_uuid7_returns_recent_timestamp(self) -> None:
        gid = generate_id()
        ts = extract_timestamp_ms(gid)
        assert isinstance(ts, int)
        assert ts > 1_700_000_000_000  # after 2023-11

    def test_ulid_rendering_of_a_uuid7_is_rejected(self) -> None:
        # The two encodings share a bit layout, but only UUID7 is accepted.
        from uuid import uuid7

        u7 = uuid7()
        ulid_str = _ulid_rendering(u7.int)
        with pytest.raises(ValueError, match="invalid id"):
            extract_timestamp_ms(ulid_str)

    def test_legacy_ulid_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid id"):
            extract_timestamp_ms(_real_ulid_hex())

    def test_invalid_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="invalid id"):
            extract_timestamp_ms("not-an-id")
        with pytest.raises(ValueError, match="invalid id"):
            extract_timestamp_ms("")


class TestExtractTimestampSeconds:
    def test_seconds_is_ms_divided_by_thousand(self) -> None:
        gid = generate_id()
        ms = extract_timestamp_ms(gid)
        s = extract_timestamp_seconds(gid)
        assert s == pytest.approx(ms / 1000.0)

    def test_seconds_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            extract_timestamp_seconds("not-an-id")


class TestConfigTraceability:
    def test_default_constructor_generates_uuid7_entity_id(self) -> None:
        ct = ConfigTraceability()
        assert UUID(ct.entity_id).version == 7
        assert ct.source == "oneiric"
        assert ct.change_type == "unknown"
        assert ct.metadata == {}

    def test_accepts_explicit_uuid7_entity_id(self) -> None:
        gid = generate_id()
        ct = ConfigTraceability(entity_id=gid, source="akosha", change_type="create")
        assert ct.entity_id == gid
        assert ct.source == "akosha"
        assert ct.change_type == "create"
        assert ct.timestamp_ms == extract_timestamp_ms(gid)

    def test_accepts_metadata(self) -> None:
        ct = ConfigTraceability(metadata={"k": "v", "n": 1})
        assert ct.metadata == {"k": "v", "n": 1}

    def test_metadata_property_returns_copy(self) -> None:
        # External mutation of the returned dict must not affect internal state.
        ct = ConfigTraceability(metadata={"a": 1})
        view = ct.metadata
        view["a"] = 999
        assert ct.metadata == {"a": 1}

    def test_rejects_non_uuid7_entity_id(self) -> None:
        with pytest.raises(ValueError, match="UUID7"):
            ConfigTraceability(entity_id="not-a-uuid7")
        with pytest.raises(ValueError, match="UUID7"):
            ConfigTraceability(entity_id=_real_ulid_hex())
        with pytest.raises(ValueError, match="UUID7"):
            ConfigTraceability(entity_id="01ARZ3NDEKTS6PQRYF")

    def test_timestamp_ms_and_seconds_match(self) -> None:
        ct = ConfigTraceability()
        assert ct.timestamp_ms > 0
        assert ct.timestamp_seconds == ct.timestamp_ms / 1000.0

    def test_correlates_with_self(self) -> None:
        ct = ConfigTraceability()
        # Within 1 second of itself; the helpers should agree.
        assert ct.correlates_with(ct.entity_id)

    def test_does_not_correlate_with_legacy_ulid(self) -> None:
        # correlates_with returns False for a non-UUID7 id rather than
        # raising — a legacy ULID is not a correlation target any more.
        from uuid import uuid7

        u7 = uuid7()
        ulid_str = _ulid_rendering(u7.int)
        ct = ConfigTraceability(entity_id=u7.hex)
        assert not ct.correlates_with(ulid_str)

    def test_correlates_with_old_timestamp_returns_false(self) -> None:
        # A non-UUID7 id is not a correlation target; the helper answers
        # False rather than raising.
        ct = ConfigTraceability()
        assert not ct.correlates_with("not-a-valid-id")

    def test_repr_includes_entity_id_source_change_type(self) -> None:
        ct = ConfigTraceability(entity_id=generate_id(), source="x", change_type="y")
        r = repr(ct)
        assert "ConfigTraceability" in r
        assert ct.entity_id in r
        assert "x" in r
        assert "y" in r

    def test_to_dict_round_trip_keys(self) -> None:
        gid = generate_id()
        ct = ConfigTraceability(
            entity_id=gid,
            source="akosha",
            change_type="update",
            metadata={"k": "v"},
        )
        d = ct.to_dict()
        assert d == {
            "entity_id": gid,
            "source": "akosha",
            "change_type": "update",
            "timestamp_ms": ct.timestamp_ms,
            "timestamp_seconds": ct.timestamp_seconds,
            "metadata": {"k": "v"},
        }
