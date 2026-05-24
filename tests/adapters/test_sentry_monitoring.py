from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from oneiric.adapters.monitoring.sentry import (
    SentryMonitoringAdapter,
    SentryMonitoringSettings,
)
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_sentry_adapter_initializes_with_env(monkeypatch) -> None:
    fake_sdk = MagicMock()
    fake_sdk.init = MagicMock()
    fake_sdk.flush = MagicMock()
    with patch("oneiric.adapters.monitoring.sentry.sentry_sdk", fake_sdk):
        settings = SentryMonitoringSettings(
            dsn=None, environment="prod", traces_sample_rate=1.0
        )
        adapter = SentryMonitoringAdapter(settings)
        monkeypatch.setenv("SENTRY_DSN", "https://example@sentry")
        await adapter.init()
        assert await adapter.health() is True
        fake_sdk.init.assert_called_once()
        await adapter.cleanup()
        fake_sdk.flush.assert_called_once()


@pytest.mark.asyncio
async def test_sentry_adapter_requires_dsn(monkeypatch) -> None:
    fake_sdk = MagicMock()
    with patch("oneiric.adapters.monitoring.sentry.sentry_sdk", fake_sdk):
        adapter = SentryMonitoringAdapter(SentryMonitoringSettings(dsn=None))
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        with pytest.raises(LifecycleError):
            await adapter.init()


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_when_sdk_none() -> None:
    """cleanup() returns early when sentry_sdk is None (line 100)."""
    with patch("oneiric.adapters.monitoring.sentry.sentry_sdk", None):
        adapter = SentryMonitoringAdapter(SentryMonitoringSettings())
        adapter._configured = True
        await adapter.cleanup()
        # should not raise; _configured still True because early-return path was taken
        assert adapter._configured is True


def test_resolve_dsn_from_settings() -> None:
    """_resolve_dsn returns DSN from settings when set (line 112)."""
    from pydantic import SecretStr

    settings = SentryMonitoringSettings(dsn=SecretStr("https://key@sentry.io/123"))
    adapter = SentryMonitoringAdapter(settings)
    assert adapter._resolve_dsn() == "https://key@sentry.io/123"


def test_require_sdk_raises_when_none() -> None:
    """_require_sdk raises LifecycleError when sentry_sdk is None (line 120)."""
    with patch("oneiric.adapters.monitoring.sentry.sentry_sdk", None):
        adapter = SentryMonitoringAdapter(SentryMonitoringSettings())
        with pytest.raises(LifecycleError, match="sentry-sdk-missing"):
            adapter._require_sdk()


def test_before_send_with_context_tags() -> None:
    """_before_send applies context tags and fingerprint (lines 126-129)."""
    settings = SentryMonitoringSettings(include_context_tags=True)
    adapter = SentryMonitoringAdapter(settings)
    event: dict = {
        "tags": {
            "oneiric.domain": "adapter",
            "oneiric.key": "nosql",
            "oneiric.provider": "mongo",
        }
    }
    result = adapter._before_send(event, {})
    assert result is event
    assert "fingerprint" in result


def test_before_send_no_context_tags() -> None:
    """_before_send skips tag application when include_context_tags=False (lines 126-129)."""
    settings = SentryMonitoringSettings(include_context_tags=False)
    adapter = SentryMonitoringAdapter(settings)
    event: dict = {}
    result = adapter._before_send(event, {})
    assert result is event
    assert "tags" not in result


def test_before_send_transaction() -> None:
    """_before_send_transaction applies context tags when enabled (lines 134-136)."""
    settings = SentryMonitoringSettings(include_context_tags=True)
    adapter = SentryMonitoringAdapter(settings)
    event: dict = {"tags": {"oneiric.domain": "adapter"}}
    result = adapter._before_send_transaction(event, {})
    assert result is event


def test_apply_context_tags_with_active_context() -> None:
    """_apply_context_tags merges structlog contextvars into event (lines 139-158)."""
    from structlog.contextvars import bind_contextvars, clear_contextvars

    clear_contextvars()
    bind_contextvars(domain="adapter", key="nosql", provider="mongo", workflow="wf1")
    try:
        adapter = SentryMonitoringAdapter(SentryMonitoringSettings())
        event: dict = {}
        adapter._apply_context_tags(event)
        assert event["tags"]["oneiric.domain"] == "adapter"
        assert event["tags"]["oneiric.provider"] == "mongo"
        assert "oneiric" in event["extra"]
    finally:
        clear_contextvars()


def test_apply_context_tags_empty_context() -> None:
    """_apply_context_tags returns early when context is empty (line 141)."""
    from structlog.contextvars import clear_contextvars

    clear_contextvars()
    adapter = SentryMonitoringAdapter(SentryMonitoringSettings())
    event: dict = {}
    adapter._apply_context_tags(event)
    assert "tags" not in event


def test_apply_fingerprint_with_all_fields() -> None:
    """_apply_fingerprint builds fingerprint list from event tags (lines 164-185)."""
    adapter = SentryMonitoringAdapter(SentryMonitoringSettings())
    event: dict = {
        "tags": {
            "oneiric.domain": "adapter",
            "oneiric.key": "nosql",
            "oneiric.provider": "mongo",
        },
        "exception": {"values": [{"type": "ValueError"}]},
    }
    adapter._apply_fingerprint(event)
    assert event["fingerprint"] == [
        "oneiric",
        "adapter",
        "nosql",
        "mongo",
        "ValueError",
    ]


def test_apply_fingerprint_already_set() -> None:
    """_apply_fingerprint returns early when fingerprint already set (line 164)."""
    adapter = SentryMonitoringAdapter(SentryMonitoringSettings())
    event: dict = {"fingerprint": ["custom"]}
    adapter._apply_fingerprint(event)
    assert event["fingerprint"] == ["custom"]


def test_apply_fingerprint_no_tags() -> None:
    """_apply_fingerprint returns early when no oneiric tags (line 171)."""
    adapter = SentryMonitoringAdapter(SentryMonitoringSettings())
    event: dict = {}
    adapter._apply_fingerprint(event)
    assert "fingerprint" not in event
