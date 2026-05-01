"""Tests for core ULID traceability and detection functions."""

from __future__ import annotations

import time

import pytest

from oneiric.core.ulid import (
    ConfigTraceability,
    DHURUVA_AVAILABLE,
    ULID,
    detect_ulid_in_config,
    extract_timestamp,
    generate,
    generate_config_id,
    get_timestamp,
    is_ulid,
    is_config_ulid,
    parse_config_ulid,
)


class TestULIDFallback:
    """Tests for the fallback ULID implementation (when druva is not installed)."""

    def test_generate_returns_26_chars(self):
        result = generate()
        assert len(result) == 26

    def test_generate_is_unique(self):
        results = {generate() for _ in range(100)}
        assert len(results) == 100

    def test_generate_all_valid_base32(self):
        for _ in range(50):
            result = generate()
            assert all(c in "0123456789abcdefghjkmnpqrstvwxyz" for c in result.lower())

    def test_get_timestamp_from_string(self):
        before = int(time.time() * 1000)
        ulid_str = generate()
        after = int(time.time() * 1000)
        ts = get_timestamp(ulid_str)
        assert before <= ts <= after

    def test_get_timestamp_from_ulid_instance(self):
        ulid = ULID()
        ts = get_timestamp(ulid)
        assert ts > 0

    def test_is_ulid_valid(self):
        ulid_str = generate()
        assert is_ulid(ulid_str) is True

    def test_is_ulid_wrong_length(self):
        assert is_ulid("too-short") is False

    def test_is_ulid_invalid_chars(self):
        assert is_ulid("iu!@#$%^&*()_+qrsjklm") is False

    def test_is_ulid_non_string(self):
        assert is_ulid(123) is False
        assert is_ulid(None) is False

    def test_ulid_from_string(self):
        original = generate()
        ulid = ULID(original)
        assert str(ulid) == original

    def test_ulid_from_string_invalid(self):
        with pytest.raises(ValueError):
            ULID("invalid")

    def test_ulid_from_bytes_invalid(self):
        with pytest.raises(ValueError):
            ULID(b"\x00\x01")

    def test_ulid_from_bytes(self):
        ulid = ULID(generate())
        ulid2 = ULID(ulid._bytes)
        assert str(ulid) == str(ulid2)

    def test_ulid_equality(self):
        ulid_str = generate()
        assert ULID(ulid_str) == ULID(ulid_str)
        assert ULID(ulid_str) == ulid_str

    def test_ulid_inequality(self):
        ulid1 = ULID()
        ulid2 = ULID()
        assert ulid1 != ulid2

    def test_ulid_hash(self):
        ulid = ULID()
        assert hash(ulid) == hash(ULID(str(ulid)))

    def test_ulid_repr(self):
        ulid = ULID()
        assert "ULID(" in repr(ulid)


class TestConfigFunctions:
    def test_generate_config_id(self):
        cid = generate_config_id()
        assert len(cid) == 26

    def test_is_config_ulid(self):
        cid = generate_config_id()
        assert is_config_ulid(cid) is True
        assert is_config_ulid("not-a-ulid") is False

    def test_extract_timestamp(self):
        cid = generate_config_id()
        ts = extract_timestamp(cid)
        assert ts > 0

    def test_parse_config_ulid_from_string(self):
        cid = generate_config_id()
        parsed = parse_config_ulid(cid)
        assert str(parsed) == cid

    def test_parse_config_ulid_from_ulid(self):
        cid = generate_config_id()
        ulid = ULID(cid)
        parsed = parse_config_ulid(ulid)
        assert str(parsed) == cid


class TestConfigTraceability:
    def test_auto_generate_id(self):
        trace = ConfigTraceability()
        assert len(trace.config_id) == 26

    def test_explicit_id(self):
        cid = generate_config_id()
        trace = ConfigTraceability(config_id=cid)
        assert trace.config_id == cid

    def test_invalid_id_raises(self):
        with pytest.raises(ValueError, match="Invalid config ULID"):
            ConfigTraceability(config_id="not-valid")

    def test_source(self):
        trace = ConfigTraceability(source="mahavishnu")
        assert trace.source == "mahavishnu"

    def test_change_type(self):
        trace = ConfigTraceability(change_type="update")
        assert trace.change_type == "update"

    def test_timestamp_ms(self):
        before = int(time.time() * 1000)
        trace = ConfigTraceability()
        after = int(time.time() * 1000)
        assert before <= trace.timestamp_ms <= after

    def test_timestamp_seconds(self):
        trace = ConfigTraceability()
        assert trace.timestamp_seconds == trace.timestamp_ms / 1000.0

    def test_metadata(self):
        trace = ConfigTraceability(metadata={"key": "value"})
        assert trace.metadata == {"key": "value"}
        # Metadata should be a copy
        trace.metadata["key2"] = "value2"
        assert "key2" not in ConfigTraceability(config_id=trace.config_id).metadata

    def test_default_metadata(self):
        trace = ConfigTraceability()
        assert trace.metadata == {}

    def test_correlates_with(self):
        before = int(time.time() * 1000)
        cid1 = generate_config_id()
        cid2 = generate_config_id()
        after = int(time.time() * 1000)

        trace = ConfigTraceability(config_id=cid1)
        # Generated within same second, should correlate
        assert trace.correlates_with(cid2) is True

    def test_correlates_with_invalid_ulid(self):
        trace = ConfigTraceability()
        assert trace.correlates_with("invalid") is False

    def test_repr(self):
        trace = ConfigTraceability(source="test", change_type="create")
        r = repr(trace)
        assert "ConfigTraceability" in r
        assert "test" in r
        assert "create" in r

    def test_to_dict(self):
        trace = ConfigTraceability(source="oneiric", change_type="update", metadata={"env": "dev"})
        d = trace.to_dict()
        assert d["source"] == "oneiric"
        assert d["change_type"] == "update"
        assert d["metadata"] == {"env": "dev"}
        assert "timestamp_ms" in d
        assert "timestamp_seconds" in d


class TestDetectULIDInConfig:
    def test_detect_in_string(self):
        cid = generate_config_id()
        result = detect_ulid_in_config(cid)
        assert cid in result

    def test_detect_in_dict(self):
        cid = generate_config_id()
        config = {"ref": cid, "name": "test"}
        result = detect_ulid_in_config(config)
        assert cid in result

    def test_detect_in_nested_dict(self):
        cid1 = generate_config_id()
        cid2 = generate_config_id()
        config = {"outer": {"inner": cid1}, "other": cid2}
        result = detect_ulid_in_config(config)
        assert cid1 in result
        assert cid2 in result

    def test_detect_in_list(self):
        cid = generate_config_id()
        config = [cid, "not-a-ulid", {"nested": cid}]
        result = detect_ulid_in_config(config)
        assert result.count(cid) == 2

    def test_detect_no_ulids(self):
        result = detect_ulid_in_config({"key": "value"})
        assert result == []

    def test_detect_in_tuple(self):
        cid = generate_config_id()
        result = detect_ulid_in_config((cid, "other"))
        assert cid in result

    def test_detect_in_set(self):
        cid = generate_config_id()
        result = detect_ulid_in_config({cid})
        assert cid in result

    def test_detect_in_non_string_scalar(self):
        result = detect_ulid_in_config(42)
        assert result == []
