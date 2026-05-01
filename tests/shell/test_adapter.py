"""Tests for OneiricShell adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.core.config import OneiricSettings
from oneiric.shell.adapter import OneiricShell


@pytest.fixture
def settings():
    return OneiricSettings()


@pytest.fixture
def shell(settings):
    with patch("oneiric.shell.adapter.SessionEventEmitter", MagicMock()):
        yield OneiricShell(settings)


class TestOneiricShellInit:
    def test_extends_admin_shell(self, settings):
        shell = OneiricShell(settings)
        assert hasattr(shell, "app")
        assert hasattr(shell, "namespace")

    def test_namespace_has_oneiric_objects(self, settings):
        shell = OneiricShell(settings)
        from oneiric.core.config import OneiricSettings as SettingsCls
        assert shell.namespace["OneiricSettings"] is SettingsCls
        assert shell.namespace["config"] is settings

    def test_namespace_has_convenience_functions(self, settings):
        shell = OneiricShell(settings)
        assert "reload_settings" in shell.namespace
        assert "show_layers" in shell.namespace
        assert "validate_config" in shell.namespace


class TestGetComponentName:
    def test_returns_oneiric(self, shell):
        assert shell._get_component_name() == "oneiric"


class TestGetComponentVersion:
    def test_returns_version_on_success(self, shell):
        with patch("importlib.metadata.version", return_value="2.0.0"):
            assert shell._get_component_version() == "2.0.0"

    def test_returns_unknown_on_failure(self, shell):
        with patch("importlib.metadata.version", side_effect=ImportError):
            assert shell._get_component_version() == "unknown"


class TestGetAdaptersInfo:
    def test_returns_empty(self, shell):
        assert shell._get_adapters_info() == []


class TestGetBanner:
    def test_banner_contains_version(self, shell):
        with patch.object(shell, "_get_component_version", return_value="1.5.0"):
            banner = shell._get_banner()
            assert "1.5.0" in banner
            assert "Oneiric Admin Shell" in banner
            assert "reload_settings" in banner
            assert "show_layers" in banner
            assert "validate_config" in banner


class TestReloadSettings:
    @pytest.mark.asyncio
    async def test_reload_settings(self, shell):
        new_settings = OneiricSettings()
        with patch("oneiric.core.config.load_settings", return_value=new_settings):
            await shell._reload_settings()
        assert shell.app is new_settings
        assert shell.namespace["config"] is new_settings


class TestShowConfigLayers:
    @pytest.mark.asyncio
    async def test_show_config_layers(self, shell):
        with patch("rich.console.Console") as mock_console_cls, \
             patch("rich.table.Table") as mock_table_cls:
            mock_console = MagicMock()
            mock_console_cls.return_value = mock_console
            mock_table = MagicMock()
            mock_table_cls.return_value = mock_table

            await shell._show_config_layers()

            mock_console.print.assert_called_once_with(mock_table)
            mock_table.add_column.assert_called()
            assert mock_table.add_row.call_count == 4


class TestValidateConfig:
    @pytest.mark.asyncio
    async def test_validate_config_success(self, shell):
        with patch("rich.console.Console") as mock_console_cls:
            mock_console = MagicMock()
            mock_console_cls.return_value = mock_console

            await shell._validate_config()

            printed = mock_console.print.call_args[0][0]
            assert "valid" in printed.lower()

    @pytest.mark.asyncio
    async def test_validate_config_failure(self, shell):
        with patch("rich.console.Console") as mock_console_cls, \
             patch.object(OneiricSettings, "model_validate", side_effect=ValueError("bad")):
            mock_console = MagicMock()
            mock_console_cls.return_value = mock_console

            await shell._validate_config()

            printed = mock_console.print.call_args[0][0]
            assert "error" in printed.lower() or "bad" in printed.lower()


class TestEmitSessionStart:
    @pytest.mark.asyncio
    async def test_emit_session_start_success(self, shell):
        shell.session_tracker = MagicMock()
        shell.session_tracker.emit_session_start = AsyncMock(return_value="sess-abc")
        shell._get_component_version = MagicMock(return_value="1.0")

        await shell._emit_session_start()

        assert shell._session_id == "sess-abc"
        shell.session_tracker.emit_session_start.assert_called_once()
        call_kwargs = shell.session_tracker.emit_session_start.call_args
        assert call_kwargs.kwargs["shell_type"] == "OneiricShell"
        metadata = call_kwargs.kwargs["metadata"]
        assert metadata["component_type"] == "foundation"

    @pytest.mark.asyncio
    async def test_emit_session_start_tracker_unavailable(self, shell):
        shell.session_tracker = MagicMock()
        shell.session_tracker.emit_session_start = AsyncMock(return_value=None)
        shell._get_component_version = MagicMock(return_value="1.0")

        await shell._emit_session_start()

        assert shell._session_id is None

    @pytest.mark.asyncio
    async def test_emit_session_start_error(self, shell):
        shell.session_tracker = MagicMock()
        shell.session_tracker.emit_session_start = AsyncMock(side_effect=RuntimeError("fail"))

        await shell._emit_session_start()

        assert shell._session_id is None


class TestEmitSessionEnd:
    @pytest.mark.asyncio
    async def test_emit_session_end_no_session(self, shell):
        shell._session_id = None
        shell.session_tracker = MagicMock()

        await shell._emit_session_end()

        shell.session_tracker.emit_session_end.assert_not_called()

    @pytest.mark.asyncio
    async def test_emit_session_end_success(self, shell):
        shell._session_id = "sess-abc"
        shell.session_tracker = MagicMock()
        shell.session_tracker.emit_session_end = AsyncMock()

        await shell._emit_session_end()

        shell.session_tracker.emit_session_end.assert_called_once_with(
            session_id="sess-abc",
            metadata={},
        )
        assert shell._session_id is None

    @pytest.mark.asyncio
    async def test_emit_session_end_clears_id_on_error(self, shell):
        shell._session_id = "sess-abc"
        shell.session_tracker = MagicMock()
        shell.session_tracker.emit_session_end = AsyncMock(side_effect=RuntimeError("fail"))

        await shell._emit_session_end()

        assert shell._session_id is None


class TestClose:
    @pytest.mark.asyncio
    async def test_close(self, shell):
        shell._session_id = "sess-abc"
        shell.session_tracker = MagicMock()
        shell.session_tracker.emit_session_end = AsyncMock()
        shell.session_tracker.close = AsyncMock()

        await shell.close()

        shell.session_tracker.emit_session_end.assert_called_once()
        shell.session_tracker.close.assert_called_once()
