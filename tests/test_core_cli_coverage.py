"""Tests for oneiric/core/cli.py — MCPServerCLIFactory and MCPServerBase."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from oneiric.core.cli import MCPServerBase, MCPServerCLIFactory

# ---------------------------------------------------------------------------
# MCPServerBase
# ---------------------------------------------------------------------------


class TestMCPServerBase:
    def test_init_stores_config(self):
        config = MagicMock()
        base = MCPServerBase(config)
        assert base.config is config

    def test_startup_is_noop(self):
        base = MCPServerBase(MagicMock())
        # startup is a no-op coroutine
        import asyncio

        asyncio.run(base.startup())

    def test_shutdown_is_noop(self):
        base = MCPServerBase(MagicMock())
        import asyncio

        asyncio.run(base.shutdown())

    def test_get_app_raises_not_implemented(self):
        base = MCPServerBase(MagicMock())
        with pytest.raises(NotImplementedError, match="get_app"):
            base.get_app()


# ---------------------------------------------------------------------------
# MCPServerCLIFactory — constructor and command registration
# ---------------------------------------------------------------------------


class TestCLIFactoryInit:
    def test_init_registers_start_command(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        assert "start" in [cmd.name for cmd in factory.app.registered_commands]

    def test_init_registers_stop_command(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        assert "stop" in [cmd.name for cmd in factory.app.registered_commands]

    def test_init_registers_restart_command(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        assert "restart" in [cmd.name for cmd in factory.app.registered_commands]

    def test_init_registers_status_command(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        assert "status" in [cmd.name for cmd in factory.app.registered_commands]

    def test_init_registers_health_command(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        assert "health" in [cmd.name for cmd in factory.app.registered_commands]

    def test_init_no_config_with_legacy_flags(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
            legacy_flags=True,
        )
        names = [cmd.name for cmd in factory.app.registered_commands]
        assert "config" not in names

    def test_init_registers_config_without_legacy(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
            legacy_flags=False,
        )
        names = [cmd.name for cmd in factory.app.registered_commands]
        assert "config" in names


# ---------------------------------------------------------------------------
# _check_health — branches for server with and without health_check
# ---------------------------------------------------------------------------


class TestCheckHealth:
    def test_health_check_without_method(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        # MCPServerBase has no health_check method, should log healthy
        factory._check_health()

    def test_health_check_with_method(self):
        class HealthyServer(MCPServerBase):
            async def health_check(self):
                return MagicMock(to_dict=lambda: {"status": "healthy"})

        factory = MCPServerCLIFactory(
            server_class=HealthyServer,
            config_class=MagicMock,
            name="test",
        )
        factory._check_health()

    def test_health_check_exception_handling(self):
        class BrokenServer(MCPServerBase):
            async def health_check(self):
                raise RuntimeError("health check failed")

        factory = MCPServerCLIFactory(
            server_class=BrokenServer,
            config_class=MagicMock,
            name="test",
        )
        # Should not raise — catches exception and logs error
        factory._check_health()


# ---------------------------------------------------------------------------
# _initialize_runtime_components and _cleanup_runtime_components
# ---------------------------------------------------------------------------


class TestRuntimeComponents:
    def test_initialize_with_snapshot_manager(self):
        from unittest.mock import AsyncMock

        class ServerWithSnapshot(MCPServerBase):
            snapshot_manager = MagicMock()

        ServerWithSnapshot.snapshot_manager.initialize = AsyncMock()
        factory = MCPServerCLIFactory(
            server_class=ServerWithSnapshot,
            config_class=MagicMock,
            name="test",
        )
        server = ServerWithSnapshot(MagicMock())
        factory._initialize_runtime_components(server)
        ServerWithSnapshot.snapshot_manager.initialize.assert_called_once()

    def test_cleanup_with_snapshot_manager(self):
        from unittest.mock import AsyncMock

        class ServerWithSnapshot(MCPServerBase):
            snapshot_manager = MagicMock()

        ServerWithSnapshot.snapshot_manager.cleanup = AsyncMock()
        factory = MCPServerCLIFactory(
            server_class=ServerWithSnapshot,
            config_class=MagicMock,
            name="test",
        )
        server = ServerWithSnapshot(MagicMock())
        factory._cleanup_runtime_components(server)
        ServerWithSnapshot.snapshot_manager.cleanup.assert_called_once()

    def test_initialize_with_cache_manager(self):
        from unittest.mock import AsyncMock

        class ServerWithCache(MCPServerBase):
            cache_manager = MagicMock()

        ServerWithCache.cache_manager.initialize = AsyncMock()
        factory = MCPServerCLIFactory(
            server_class=ServerWithCache,
            config_class=MagicMock,
            name="test",
        )
        server = ServerWithCache(MagicMock())
        factory._initialize_runtime_components(server)
        ServerWithCache.cache_manager.initialize.assert_called_once()

    def test_cleanup_with_cache_manager(self):
        from unittest.mock import AsyncMock

        class ServerWithCache(MCPServerBase):
            cache_manager = MagicMock()

        ServerWithCache.cache_manager.cleanup = AsyncMock()
        factory = MCPServerCLIFactory(
            server_class=ServerWithCache,
            config_class=MagicMock,
            name="test",
        )
        server = ServerWithCache(MagicMock())
        factory._cleanup_runtime_components(server)
        ServerWithCache.cache_manager.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# _log_health_results
# ---------------------------------------------------------------------------


class TestLogHealthResults:
    def test_log_health_with_dict_and_status(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        health = MagicMock(to_dict=lambda: {"status": "ok", "details": "fine"})
        factory._log_health_results(health)

    def test_log_health_with_dict_no_status(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        health = MagicMock(to_dict=lambda: {"info": "no status key"})
        factory._log_health_results(health)

    def test_log_health_with_non_dict(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        health = "just a string"
        factory._log_health_results(health)

    def test_log_health_with_no_to_dict(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        health = MagicMock(spec=[])  # no to_dict
        factory._log_health_results(health)


# ---------------------------------------------------------------------------
# _stop_server and _restart_server
# ---------------------------------------------------------------------------


class TestStopRestart:
    def test_stop_server(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        factory._stop_server()  # Should not raise

    def test_show_config(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        factory._show_config()  # Should not raise

    def test_check_status(self):
        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        factory._check_status()  # Should not raise

    def test_restart_server_delegates(self):
        from unittest.mock import patch

        factory = MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )
        with patch.object(factory, "_start_server") as mock_start:
            factory._restart_server()
        mock_start.assert_called_once()

    def test_start_server_keyboard_interrupt_triggers_shutdown(self):
        import asyncio as stdlib_asyncio
        from unittest.mock import patch

        class AppServer(MCPServerBase):
            def get_app(self):
                return MagicMock()

        factory = MCPServerCLIFactory(
            server_class=AppServer,
            config_class=MagicMock,
            name="test",
        )
        sync_sleep = MagicMock(side_effect=KeyboardInterrupt)
        with patch.object(stdlib_asyncio, "run", return_value=None):
            with patch.object(stdlib_asyncio, "sleep", new=sync_sleep):
                factory._start_server()  # Should catch KeyboardInterrupt, not raise


# ---------------------------------------------------------------------------
# CLI command closures — invoked via typer CliRunner (lines 53, 57, 61, 65, 69, 75)
# ---------------------------------------------------------------------------


class TestCLICommandClosures:
    def _make_factory(self):
        return MCPServerCLIFactory(
            server_class=MCPServerBase,
            config_class=MagicMock,
            name="test",
        )

    def test_stop_command_invokes_stop_server(self):
        from typer.testing import CliRunner
        from unittest.mock import patch

        factory = self._make_factory()
        runner = CliRunner()

        with patch.object(factory, "_stop_server") as mock_stop:
            result = runner.invoke(factory.app, ["stop"])
        assert result.exit_code == 0
        mock_stop.assert_called_once()

    def test_restart_command_invokes_restart_server(self):
        from typer.testing import CliRunner
        from unittest.mock import patch

        factory = self._make_factory()
        runner = CliRunner()

        with patch.object(factory, "_restart_server") as mock_restart:
            result = runner.invoke(factory.app, ["restart"])
        assert result.exit_code == 0
        mock_restart.assert_called_once()

    def test_status_command_invokes_check_status(self):
        from typer.testing import CliRunner
        from unittest.mock import patch

        factory = self._make_factory()
        runner = CliRunner()

        with patch.object(factory, "_check_status") as mock_status:
            result = runner.invoke(factory.app, ["status"])
        assert result.exit_code == 0
        mock_status.assert_called_once()

    def test_health_command_invokes_check_health(self):
        from typer.testing import CliRunner
        from unittest.mock import patch

        factory = self._make_factory()
        runner = CliRunner()

        with patch.object(factory, "_check_health") as mock_health:
            result = runner.invoke(factory.app, ["health"])
        assert result.exit_code == 0
        mock_health.assert_called_once()

    def test_config_command_invokes_show_config(self):
        from typer.testing import CliRunner
        from unittest.mock import patch

        factory = self._make_factory()
        runner = CliRunner()

        with patch.object(factory, "_show_config") as mock_config:
            result = runner.invoke(factory.app, ["config"])
        assert result.exit_code == 0
        mock_config.assert_called_once()

    def test_start_command_invokes_start_server(self):
        from typer.testing import CliRunner
        from unittest.mock import patch

        factory = self._make_factory()
        runner = CliRunner()

        with patch.object(factory, "_start_server") as mock_start:
            result = runner.invoke(factory.app, ["start"])
        assert result.exit_code == 0
        mock_start.assert_called_once()

    def test_run_invokes_app(self):
        from unittest.mock import patch

        factory = self._make_factory()
        with patch.object(factory, "app") as mock_app:
            factory.run()
        mock_app.assert_called_once()
