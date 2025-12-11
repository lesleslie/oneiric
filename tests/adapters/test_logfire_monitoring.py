from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from oneiric.adapters.monitoring.logfire import (
    LogfireMonitoringAdapter,
    LogfireMonitoringSettings,
)


@pytest.mark.asyncio
async def test_logfire_adapter_configures_with_token(monkeypatch) -> None:
    fake_logfire = MagicMock()
    fake_logfire.configure = MagicMock()
    fake_logfire.instrument_system_metrics = MagicMock()
    fake_logfire.instrument_httpx = MagicMock()
    fake_logfire.instrument_pydantic = MagicMock()
    with patch("oneiric.adapters.monitoring.logfire.logfire", fake_logfire):
        adapter = LogfireMonitoringAdapter(LogfireMonitoringSettings(token=None))
        monkeypatch.setenv("LOGFIRE_TOKEN", "abc123")
        await adapter.init()
        assert await adapter.health() is True
        fake_logfire.configure.assert_called_once()
        await adapter.cleanup()
        fake_logfire.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_logfire_adapter_missing_token(monkeypatch) -> None:
    fake_logfire = MagicMock()
    with patch("oneiric.adapters.monitoring.logfire.logfire", fake_logfire):
        adapter = LogfireMonitoringAdapter(LogfireMonitoringSettings(token=None))
        monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
        with pytest.raises(Exception):
            await adapter.init()
