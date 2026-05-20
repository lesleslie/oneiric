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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logfire_cleanup_when_logfire_none() -> None:
    """cleanup() returns early when logfire module is None (line 90)."""
    with patch("oneiric.adapters.monitoring.logfire.logfire", None):
        adapter = LogfireMonitoringAdapter()
        adapter._configured = True
        await adapter.cleanup()
        # No exception raised — early return path


def test_resolve_token_from_settings() -> None:
    """_resolve_token returns token from settings when set (line 99)."""
    from pydantic import SecretStr

    adapter = LogfireMonitoringAdapter(
        LogfireMonitoringSettings(token=SecretStr("my-token"))
    )
    assert adapter._resolve_token() == "my-token"


def test_maybe_call_skips_when_disabled() -> None:
    """_maybe_call returns early when enabled=False (line 107)."""
    fake_logfire = MagicMock()
    with patch("oneiric.adapters.monitoring.logfire.logfire", fake_logfire):
        adapter = LogfireMonitoringAdapter()
        adapter._maybe_call("instrument_httpx", False)
        fake_logfire.instrument_httpx.assert_not_called()


def test_build_config_kwargs_includes_environment_and_release() -> None:
    """_build_config_kwargs adds deployment.environment and service.version tags (lines 117, 119, 125)."""
    fake_configure = MagicMock()
    import inspect

    fake_logfire = MagicMock()
    fake_logfire.configure = fake_configure
    with patch("oneiric.adapters.monitoring.logfire.logfire", fake_logfire):
        with patch("inspect.signature") as mock_sig:
            mock_sig.return_value.parameters = {"token": None, "service_name": None, "tags": None}
            settings = LogfireMonitoringSettings(
                token=None,
                environment="production",
                release="v2.0.0",
            )
            adapter = LogfireMonitoringAdapter(settings)
            kwargs = adapter._build_config_kwargs("tok")
    assert kwargs.get("tags", {}).get("deployment.environment") == "production"
    assert kwargs.get("tags", {}).get("service.version") == "v2.0.0"


def test_build_config_kwargs_returns_early_when_configure_not_callable() -> None:
    """_build_config_kwargs returns kwargs early when configure is not callable (line 128)."""

    class _NoConfigureLogfire:
        configure = "not-a-function"

    with patch("oneiric.adapters.monitoring.logfire.logfire", _NoConfigureLogfire()):
        adapter = LogfireMonitoringAdapter(
            LogfireMonitoringSettings(token=None, environment="staging")
        )
        # _build_config_kwargs is called with a token string
        kwargs = adapter._build_config_kwargs("tok")
    assert "token" in kwargs


def test_build_config_kwargs_handles_signature_error() -> None:
    """_build_config_kwargs returns kwargs when inspect.signature raises (lines 131-132)."""
    import inspect

    fake_logfire = MagicMock()
    with patch("oneiric.adapters.monitoring.logfire.logfire", fake_logfire):
        with patch("inspect.signature", side_effect=TypeError("no sig")):
            adapter = LogfireMonitoringAdapter()
            kwargs = adapter._build_config_kwargs("tok")
    assert "token" in kwargs
