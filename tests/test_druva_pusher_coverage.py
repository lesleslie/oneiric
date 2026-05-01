"""Tests for oneiric/adapters/druva_pusher.py — DruvaAdapterPusher, push_adapters_on_startup, main."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from oneiric.adapters.druva_pusher import (
    DruvaAdapterPusher,
    main,
    push_adapters_on_startup,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_metadata(category="cache", provider="redis", version="1.0.0"):
    """Create a mock AdapterMetadata."""
    m = MagicMock()
    m.category = category
    m.provider = provider
    m.version = version
    m.description = f"{category} adapter"
    m.owner = "oneiric"
    m.capabilities = ["kv"]
    m.requires_secrets = False
    m.factory = lambda: None
    return m


# ---------------------------------------------------------------------------
# DruvaAdapterPusher.__init__
# ---------------------------------------------------------------------------


class TestPusherInit:
    def test_init_defaults(self):
        p = DruvaAdapterPusher()
        assert p.druva_url == "http://127.0.0.1:8683"
        assert p.timeout == 30.0

    def test_init_custom_url(self):
        p = DruvaAdapterPusher(druva_url="http://example.com:9999")
        assert p.druva_url == "http://example.com:9999"

    def test_init_strips_trailing_slash(self):
        p = DruvaAdapterPusher(druva_url="http://example.com:9999/")
        assert p.druva_url == "http://example.com:9999"

    def test_init_custom_timeout(self):
        p = DruvaAdapterPusher(timeout=60.0)
        assert p.timeout == 60.0

    def test_init_creates_httpx_client(self):
        p = DruvaAdapterPusher()
        assert isinstance(p.client, httpx.Client)


# ---------------------------------------------------------------------------
# _make_adapter_id
# ---------------------------------------------------------------------------


class TestMakeAdapterId:
    def test_make_adapter_id(self):
        p = DruvaAdapterPusher()
        m = _fake_metadata("cache", "redis")
        assert p._make_adapter_id(m) == "adapter:cache:redis"

    def test_make_adapter_id_storage(self):
        p = DruvaAdapterPusher()
        m = _fake_metadata("storage", "s3")
        assert p._make_adapter_id(m) == "adapter:storage:s3"


# ---------------------------------------------------------------------------
# _push_single_adapter
# ---------------------------------------------------------------------------


class TestPushSingleAdapter:
    def test_success_with_callable_factory(self):
        p = DruvaAdapterPusher()
        m = _fake_metadata()
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        with patch.object(p.client, "post", return_value=mock_response) as mock_post:
            result = p._push_single_adapter(m)

        assert result["success"] is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://127.0.0.1:8683/tools/store_adapter"

    def test_success_with_string_factory(self):
        p = DruvaAdapterPusher()
        m = _fake_metadata()
        m.factory = "my.module:my_factory"
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        with patch.object(p.client, "post", return_value=mock_response):
            result = p._push_single_adapter(m)

        assert result["success"] is True

    def test_http_error(self):
        p = DruvaAdapterPusher()
        m = _fake_metadata()

        with patch.object(
            p.client,
            "post",
            side_effect=httpx.HTTPError("connection refused"),
        ):
            result = p._push_single_adapter(m)

        assert result["success"] is False
        assert "HTTP error" in result["error"]

    def test_generic_exception(self):
        p = DruvaAdapterPusher()
        m = _fake_metadata()

        with patch.object(
            p.client, "post", side_effect=ValueError("bad data")
        ):
            result = p._push_single_adapter(m)

        assert result["success"] is False
        assert "bad data" in result["error"]

    def test_adapter_data_structure(self):
        p = DruvaAdapterPusher()
        m = _fake_metadata("cache", "redis", "2.0.0")
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        with patch.object(p.client, "post", return_value=mock_response) as mock_post:
            p._push_single_adapter(m)

        posted_data = mock_post.call_args[1]["json"]
        assert posted_data["domain"] == "adapter"
        assert posted_data["key"] == "cache"
        assert posted_data["provider"] == "redis"
        assert posted_data["version"] == "2.0.0"
        assert "lambda" in posted_data["factory_path"]
        assert posted_data["dependencies"] == []
        assert posted_data["metadata"]["source"] == "builtin"


# ---------------------------------------------------------------------------
# push_builtin_adapters
# ---------------------------------------------------------------------------


class TestPushBuiltinAdapters:
    def test_all_success(self):
        p = DruvaAdapterPusher()
        adapters = [_fake_metadata("cache", "redis"), _fake_metadata("cache", "memcached")]

        with patch.object(p, "_push_single_adapter", return_value={"success": True}):
            results = p.push_builtin_adapters(adapters)

        assert results["total"] == 2
        assert results["success"] == 2
        assert results["errors"] == 0
        assert len(results["details"]) == 2

    def test_mixed_success_and_failure(self):
        p = DruvaAdapterPusher()
        adapters = [_fake_metadata("cache", "redis"), _fake_metadata("cache", "memcached")]

        call_count = 0

        def alternating_result(metadata):
            nonlocal call_count
            call_count += 1
            return {"success": call_count == 1}

        with patch.object(p, "_push_single_adapter", side_effect=alternating_result):
            results = p.push_builtin_adapters(adapters)

        assert results["success"] == 1
        assert results["errors"] == 1

    def test_exception_in_push(self):
        p = DruvaAdapterPusher()
        adapters = [_fake_metadata("cache", "redis")]

        with patch.object(
            p, "_push_single_adapter", side_effect=RuntimeError("boom")
        ):
            results = p.push_builtin_adapters(adapters)

        assert results["errors"] == 1
        assert results["details"][0]["status"] == "exception"

    def test_empty_adapter_list(self):
        p = DruvaAdapterPusher()
        results = p.push_builtin_adapters([])
        assert results["total"] == 0
        assert results["success"] == 0


# ---------------------------------------------------------------------------
# push_adapters_on_startup
# ---------------------------------------------------------------------------


class TestPushAdaptersOnStartup:
    def test_calls_builtin_and_closes(self):
        with patch(
            "oneiric.adapters.bootstrap.builtin_adapter_metadata",
            return_value=lambda: [_fake_metadata()],
        ), patch.object(
            DruvaAdapterPusher,
            "push_builtin_adapters",
            return_value={"total": 1, "success": 1, "errors": 0, "details": []},
        ):
            results = push_adapters_on_startup()

        assert results["success"] == 1

    def test_closes_client_even_on_error(self):
        with patch(
            "oneiric.adapters.bootstrap.builtin_adapter_metadata",
            side_effect=RuntimeError("bootstrap failed"),
        ):
            with pytest.raises(RuntimeError):
                push_adapters_on_startup()


# ---------------------------------------------------------------------------
# main (CLI entry point)
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_success(self):
        with patch(
            "oneiric.adapters.druva_pusher.push_adapters_on_startup",
            return_value={"total": 2, "success": 2, "errors": 0, "details": []},
        ) as mock_push:
            with patch("sys.argv", ["druva_pusher"]):
                result = main()
        assert result == 0

    def test_main_with_errors(self):
        with patch(
            "oneiric.adapters.druva_pusher.push_adapters_on_startup",
            return_value={
                "total": 2,
                "success": 1,
                "errors": 1,
                "details": [
                    {"adapter_id": "a", "status": "success"},
                    {"adapter_id": "b", "status": "error", "error": "fail"},
                ],
            },
        ):
            with patch("sys.argv", ["druva_pusher"]):
                result = main()
        assert result == 1

    def test_main_custom_url(self):
        with patch(
            "oneiric.adapters.druva_pusher.push_adapters_on_startup",
            return_value={"total": 0, "success": 0, "errors": 0, "details": []},
        ) as mock_push:
            with patch("sys.argv", ["druva_pusher", "--druva-url", "http://custom:9999"]):
                main()
        mock_push.assert_called_once_with(druva_url="http://custom:9999")


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close(self):
        p = DruvaAdapterPusher()
        p.close()
