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
        settings = SentryMonitoringSettings(dsn=None, environment="prod", traces_sample_rate=1.0)
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
