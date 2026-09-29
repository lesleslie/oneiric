"""Unit tests for OneiricAdapterRegistry.set_runtime_facts_async.

REQ-RCR-008: caller must have an existing catalog entry; runtime_facts
is sanitized server-side before persistence (secret-shaped keys → "<redacted>",
URL userinfo scrubbed, redacted_secrets list attached).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oneiric.mcp.adapter_registry import (
    OneiricAdapterRegistry,
    _sanitize_runtime_facts,
)


class TestSanitizeRuntimeFacts:
    """Pure-function tests for the redaction helper (no I/O)."""

    def test_redacts_secret_shaped_keys(self) -> None:
        out = _sanitize_runtime_facts({"access_token": "sk-1234", "user": "alice"})
        assert out["access_token"] == "<redacted>"
        assert out["user"] == "alice"
        assert out["redacted_secrets"] == ["access_token"]

    def test_redacts_recursively_nested(self) -> None:
        out = _sanitize_runtime_facts(
            {"nested": {"api_key": "k", "host": "h"}}
        )
        assert out["nested"]["api_key"] == "<redacted>"
        assert out["nested"]["host"] == "h"
        assert "nested.api_key" in out["redacted_secrets"]

    def test_redacts_in_list_items(self) -> None:
        out = _sanitize_runtime_facts({"items": [{"password": "p"}, {"safe": "v"}]})
        assert out["items"][0]["password"] == "<redacted>"
        assert out["items"][1]["safe"] == "v"

    def test_scrubs_url_userinfo(self) -> None:
        out = _sanitize_runtime_facts({"endpoint": "https://u:p@example.com/x"})
        assert out["endpoint"] == "https://***@example.com/x"
        # No secret keys here, so redacted_secrets should NOT be set.
        assert "redacted_secrets" not in out

    def test_passes_through_non_secret_data(self) -> None:
        out = _sanitize_runtime_facts({"version": "1.0", "count": 42})
        assert out == {"version": "1.0", "count": 42}

    def test_returns_new_dict_does_not_mutate_input(self) -> None:
        original = {"token": "abc", "x": "y"}
        snapshot = dict(original)
        _sanitize_runtime_facts(original)
        assert original == snapshot


class TestSetRuntimeFactsAsync:
    """End-to-end behavior of OneiricAdapterRegistry.set_runtime_facts_async."""

    @pytest.mark.asyncio
    async def test_persists_runtime_facts_on_existing_adapter(
        self, tmp_path: Path
    ) -> None:
        registry = OneiricAdapterRegistry(root=tmp_path)
        await registry.store_adapter_async(
            domain="adapter",
            key="demo",
            provider="local",
            version="1.0.0",
            factory_path="oneiric.adapters.demo:build",
            config={},
            dependencies=[],
            capabilities=["read"],
            metadata={"category": "demo"},
        )
        adapter_id = await registry.set_runtime_facts_async(
            domain="adapter",
            key="demo",
            provider="local",
            runtime_facts={"healthy": True, "version": "1.0"},
        )
        assert adapter_id == "adapter:demo:local"
        record = await registry.get_adapter_async(
            domain="adapter", key="demo", provider="local"
        )
        assert record is not None
        assert record["runtime_facts"]["healthy"] is True

    @pytest.mark.asyncio
    async def test_raises_keyerror_when_adapter_missing(
        self, tmp_path: Path
    ) -> None:
        registry = OneiricAdapterRegistry(root=tmp_path)
        with pytest.raises(KeyError, match="Adapter not found"):
            await registry.set_runtime_facts_async(
                domain="adapter",
                key="never",
                provider="local",
                runtime_facts={"x": 1},
            )

    @pytest.mark.asyncio
    async def test_sanitizes_runtime_facts_before_persistence(
        self, tmp_path: Path
    ) -> None:
        registry = OneiricAdapterRegistry(root=tmp_path)
        await registry.store_adapter_async(
            domain="adapter",
            key="svc",
            provider="local",
            version="1.0.0",
            factory_path="oneiric.adapters.demo:build",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )
        await registry.set_runtime_facts_async(
            domain="adapter",
            key="svc",
            provider="local",
            runtime_facts={
                "access_token": "sk-secret",
                "endpoint": "https://u:p@example.com",
                "version": "1.0",
            },
        )
        record = await registry.get_adapter_async(
            domain="adapter", key="svc", provider="local"
        )
        assert record is not None
        rf = record["runtime_facts"]
        assert rf["access_token"] == "<redacted>"
        assert rf["endpoint"] == "https://***@example.com"
        assert rf["version"] == "1.0"
        assert rf["redacted_secrets"] == ["access_token"]

    @pytest.mark.asyncio
    async def test_to_dict_includes_runtime_facts_field(
        self, tmp_path: Path
    ) -> None:
        registry = OneiricAdapterRegistry(root=tmp_path)
        await registry.store_adapter_async(
            domain="adapter",
            key="k",
            provider="local",
            version="1.0.0",
            factory_path="oneiric.adapters.demo:build",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )
        record = await registry.get_adapter_async(
            domain="adapter", key="k", provider="local"
        )
        assert record is not None
        assert "runtime_facts" in record
        assert record["runtime_facts"] == {}
