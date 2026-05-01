"""Tests for AdminShell core."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.shell.config import ShellConfig
from oneiric.shell.core import AdminShell


@pytest.fixture
def mock_app():
    return MagicMock()


@pytest.fixture
def shell(mock_app):
    with patch("oneiric.shell.core.load_default_config", return_value=MagicMock()):
        with patch("oneiric.shell.core.InteractiveShellEmbed", return_value=MagicMock()):
            yield AdminShell(mock_app)


class TestAdminShellInit:
    def test_default_config(self, mock_app):
        shell = AdminShell(mock_app)
        assert shell.config.banner is not None
        assert shell.app is mock_app
        assert shell.session_tracker is None
        assert shell.session_id is None

    def test_custom_config(self, mock_app):
        cfg = ShellConfig(banner="Custom")
        shell = AdminShell(mock_app, config=cfg)
        assert shell.config.banner == "Custom"

    def test_namespace_has_app(self, mock_app):
        shell = AdminShell(mock_app)
        assert shell.namespace["app"] is mock_app

    def test_namespace_has_asyncio(self, mock_app):
        shell = AdminShell(mock_app)
        assert shell.namespace["asyncio"] is asyncio

    def test_namespace_has_run(self, mock_app):
        shell = AdminShell(mock_app)
        assert shell.namespace["run"] is asyncio.run

    def test_namespace_has_logger(self, mock_app):
        shell = AdminShell(mock_app)
        assert "logger" in shell.namespace


class TestTryImport:
    def test_valid_import(self, mock_app):
        shell = AdminShell(mock_app)
        result = shell._try_import("os.path", "join")
        from os.path import join
        assert result is join

    def test_invalid_import(self, mock_app):
        shell = AdminShell(mock_app)
        result = shell._try_import("nonexistent_module_xyz", "attr")
        assert result is None

    def test_valid_module_invalid_attr(self, mock_app):
        shell = AdminShell(mock_app)
        result = shell._try_import("os", "nonexistent_attr_xyz")
        assert result is None


class TestAddHelper:
    def test_add_helper(self, mock_app):
        shell = AdminShell(mock_app)
        def my_helper():
            pass
        shell.add_helper("my_helper", my_helper)
        assert shell.namespace["my_helper"] is my_helper


class TestAddObject:
    def test_add_object(self, mock_app):
        shell = AdminShell(mock_app)
        shell.add_object("my_obj", 42)
        assert shell.namespace["my_obj"] == 42


class TestGetComponentName:
    def test_base_returns_none(self, mock_app):
        shell = AdminShell(mock_app)
        assert shell._get_component_name() is None


class TestGetComponentVersion:
    def test_returns_unknown_when_no_component(self, mock_app):
        shell = AdminShell(mock_app)
        assert shell._get_component_version() == "unknown"

    def test_returns_unknown_on_import_error(self, mock_app):
        shell = AdminShell(mock_app)
        # Make _get_component_name return something
        shell._get_component_name = lambda: "fake"
        with patch("importlib.metadata.version", side_effect=ImportError):
            assert shell._get_component_version() == "unknown"


class TestGetAdaptersInfo:
    def test_base_returns_empty(self, mock_app):
        shell = AdminShell(mock_app)
        assert shell._get_adapters_info() == []


class TestGetBanner:
    def test_banner_contains_config_text(self, mock_app):
        shell = AdminShell(mock_app)
        banner = shell._get_banner()
        assert shell.config.banner in banner
        assert "help()" in banner


class TestNotifySessionStart:
    def test_no_tracker_still_succeeds(self, mock_app):
        """_notify_session_start handles missing tracker gracefully."""
        shell = AdminShell(mock_app)
        shell.session_tracker = None
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(shell._notify_session_start())
        finally:
            loop.close()

    def test_import_error_sets_tracker_none(self, mock_app):
        """If SessionEventEmitter import fails, tracker stays None."""
        shell = AdminShell(mock_app)
        shell.session_tracker = None
        with patch.dict("sys.modules", {"oneiric.shell.session_tracker": None}):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(shell._notify_session_start())
            finally:
                loop.close()
        assert shell.session_tracker is None

    def test_with_tracker_emits(self, mock_app):
        """Tracker emits session start with correct metadata."""
        shell = AdminShell(mock_app)
        shell.session_id = None
        mock_tracker = MagicMock()
        mock_tracker.emit_session_start = AsyncMock(return_value="sess-123")
        shell.session_tracker = mock_tracker
        shell._get_component_name = lambda: "test-comp"
        shell._get_component_version = lambda: "1.0.0"
        shell._get_adapters_info = lambda: ["adapter1"]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(shell._notify_session_start())
        finally:
            loop.close()

        mock_tracker.emit_session_start.assert_called_once()
        call_kwargs = mock_tracker.emit_session_start.call_args
        assert call_kwargs.kwargs["shell_type"] == "AdminShell"
        assert shell.session_id == "sess-123"


class TestNotifySessionEnd:
    def test_no_session_id(self, mock_app):
        shell = AdminShell(mock_app)
        shell.session_id = None
        shell.session_tracker = MagicMock()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(shell._notify_session_end())
        finally:
            loop.close()
        shell.session_tracker.emit_session_end.assert_not_called()

    def test_with_session_id(self, mock_app):
        shell = AdminShell(mock_app)
        shell.session_id = "sess-123"
        mock_tracker = MagicMock()
        mock_tracker.emit_session_end = AsyncMock()
        shell.session_tracker = mock_tracker

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(shell._notify_session_end())
        finally:
            loop.close()

        mock_tracker.emit_session_end.assert_called_once_with(
            session_id="sess-123",
            metadata={"duration_seconds": None},
        )


class TestSyncSessionEnd:
    def test_no_session_id(self, mock_app):
        shell = AdminShell(mock_app)
        shell.session_id = None
        shell.session_tracker = MagicMock()
        shell._sync_session_end()
        # Should not start any thread

    def test_with_session_id(self, mock_app):
        shell = AdminShell(mock_app)
        shell.session_id = "sess-123"
        mock_tracker = MagicMock()
        mock_tracker.emit_session_end = AsyncMock()
        shell.session_tracker = mock_tracker
        shell._sync_session_end()
        # Thread runs in background - give it a moment
        import time
        time.sleep(0.1)


class TestNotifySessionStartAsync:
    def test_with_running_loop(self, mock_app):
        """When a loop is already running, creates a task."""
        shell = AdminShell(mock_app)
        shell.session_tracker = None

        async def test_body():
            with patch.object(shell, "_notify_session_start", new_callable=AsyncMock):
                shell._notify_session_start_async()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(test_body())
        finally:
            loop.close()

    def test_without_running_loop(self, mock_app):
        """When no loop is running, uses asyncio.run()."""
        shell = AdminShell(mock_app)
        shell.session_tracker = None

        shell._notify_session_start_async()
