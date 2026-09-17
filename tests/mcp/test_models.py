from __future__ import annotations

import pytest
from pydantic import ValidationError

from oneiric.mcp.models import BoundedMetadata, BoundedPrimitive


class TestBoundedPrimitive:
    def test_accepts_str(self) -> None:
        v = BoundedPrimitive.model_validate("hello")
        assert v.root == "hello"

    def test_accepts_int(self) -> None:
        v = BoundedPrimitive.model_validate(42)
        assert v.root == 42

    def test_accepts_none(self) -> None:
        v = BoundedPrimitive.model_validate(None)
        assert v.root is None

    def test_rejects_dict(self) -> None:
        with pytest.raises(ValidationError):
            BoundedPrimitive.model_validate({"nested": "dict"})

    def test_rejects_list(self) -> None:
        with pytest.raises(ValidationError):
            BoundedPrimitive.model_validate([1, 2, 3])


class TestBoundedMetadata:
    def test_accepts_primitives(self) -> None:
        m = BoundedMetadata.model_validate({"version": "1.0", "count": 3})
        assert m.root == {"version": "1.0", "count": 3}

    def test_rejects_value_too_long(self) -> None:
        with pytest.raises(ValidationError):
            BoundedMetadata.model_validate({"k": "x" * 1025})

    def test_rejects_key_too_long(self) -> None:
        with pytest.raises(ValidationError):
            BoundedMetadata.model_validate({("x" * 257): "v"})

    def test_rejects_nested_dict(self) -> None:
        with pytest.raises(ValidationError):
            BoundedMetadata.model_validate({"k": {"nested": "dict"}})

    def test_rejects_nested_list(self) -> None:
        with pytest.raises(ValidationError):
            BoundedMetadata.model_validate({"k": [1, 2]})

    def test_rejects_too_many_entries(self) -> None:
        with pytest.raises(ValidationError):
            BoundedMetadata.model_validate({f"k{i}": i for i in range(65)})

    def test_accepts_exactly_max_value_length(self) -> None:
        m = BoundedMetadata.model_validate({"k": "x" * 1024})
        assert m.root["k"] == "x" * 1024

    def test_accepts_empty_dict(self) -> None:
        m = BoundedMetadata.model_validate({})
        assert m.root == {}

    def test_none_is_allowed(self) -> None:
        # BoundedMetadata is optional in input models; None is the default.
        assert BoundedMetadata.model_validate(None) is None

    # --- pr-test-analyzer boundary coverage (T1) ---

    def test_accepts_exactly_max_key_length(self) -> None:
        m = BoundedMetadata.model_validate({("x" * 256): "v"})
        assert ("x" * 256) in m.root

    def test_rejects_empty_string_key(self) -> None:
        with pytest.raises(ValidationError):
            BoundedMetadata.model_validate({"": "v"})

    def test_accepts_exactly_max_entries(self) -> None:
        m = BoundedMetadata.model_validate({f"k{i}": i for i in range(64)})
        assert len(m.root) == 64

    def test_accepts_none_value(self) -> None:
        m = BoundedMetadata.model_validate({"k": None})
        assert m.root["k"] is None
