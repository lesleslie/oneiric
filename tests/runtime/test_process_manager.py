"""Tests for ProcessManager."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from oneiric.runtime.process_manager import ProcessManager


@pytest.fixture
def tmp_pid(tmp_path):
    return tmp_path / "test.pid"


class TestIsRunning:
    def test_pid_file_missing(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        assert pm.is_running() is False

    def test_pid_file_contains_valid_live_pid(self, tmp_pid):
        tmp_pid.write_text("42")
        pm = ProcessManager(pid_file=tmp_pid)
        with patch("os.kill") as mock_kill:
            pm.is_running()
            mock_kill.assert_called_once_with(42, 0)
            assert pm.pid == 42

    def test_pid_file_contains_garbage(self, tmp_pid):
        tmp_pid.write_text("not-a-number")
        pm = ProcessManager(pid_file=tmp_pid)
        assert pm.is_running() is False

    def test_pid_file_contains_dead_pid_cleans_up(self, tmp_pid):
        tmp_pid.write_text("99999")
        pm = ProcessManager(pid_file=tmp_pid)
        with patch("os.kill", side_effect=OSError("ESRCH")):
            assert pm.is_running() is False
        assert not tmp_pid.exists()

    def test_pid_file_disappears_after_read(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        with patch.object(Path, "exists", side_effect=[True, False]):
            with patch.object(Path, "open", side_effect=FileNotFoundError):
                assert pm.is_running() is False

    def test_default_pid_file(self):
        pm = ProcessManager()
        assert pm.pid_file == Path("./.oneiric.pid")


class TestBuildOrchestrateCommand:
    def test_minimal_command(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command()
        assert cmd[0].endswith("python")
        assert cmd[1:3] == ["-m", "oneiric.cli"]
        assert "orchestrate" in cmd

    def test_config_path(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(config_path="/tmp/cfg.yaml")
        assert "--config" in cmd
        assert "/tmp/cfg.yaml" in cmd

    def test_profile(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(profile="dev")
        assert "--profile" in cmd
        assert "dev" in cmd

    def test_manifest(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(manifest="manifest.yaml")
        assert "--manifest" in cmd

    def test_refresh_interval(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(refresh_interval=30.0)
        assert "--refresh-interval" in cmd
        assert "30.0" in cmd

    def test_no_refresh_interval(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command()
        assert "--refresh-interval" not in cmd

    def test_no_remote_flag(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(no_remote=True)
        assert "--no-remote" in cmd

    def test_no_workflow_checkpoints_flag(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(no_workflow_checkpoints=True)
        assert "--no-workflow-checkpoints" in cmd

    def test_no_http_flag(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(no_http=True)
        assert "--no-http" in cmd

    def test_http_port(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(http_port=9000)
        assert "--http-port" in cmd
        assert "9000" in cmd

    def test_http_host_default_omitted(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(http_host="0.0.0.0")
        assert "--http-host" not in cmd

    def test_http_host_custom(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(http_host="127.0.0.1")
        assert "--http-host" in cmd
        assert "127.0.0.1" in cmd

    def test_workflow_checkpoints_path(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(workflow_checkpoints="/tmp/checkpoints")
        assert "--workflow-checkpoints" in cmd

    def test_all_flags_combined(self):
        pm = ProcessManager()
        cmd = pm._build_orchestrate_command(
            config_path="cfg.yaml",
            profile="prod",
            manifest="m.yaml",
            refresh_interval=10.0,
            no_remote=True,
            no_workflow_checkpoints=True,
            http_port=8080,
            no_http=True,
        )
        assert "--config" in cmd
        assert "--profile" in cmd
        assert "--manifest" in cmd
        assert "--refresh-interval" in cmd
        assert "--no-remote" in cmd
        assert "--no-workflow-checkpoints" in cmd
        assert "--http-port" in cmd
        assert "--no-http" in cmd


class TestStartProcess:
    def test_already_running(self, tmp_pid):
        tmp_pid.write_text("42")
        pm = ProcessManager(pid_file=tmp_pid)
        with patch.object(ProcessManager, "is_running", return_value=True):
            result = pm.start_process()
        assert result is False

    def test_start_success(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with patch.object(ProcessManager, "is_running", return_value=False), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("builtins.open", MagicMock()):
            result = pm.start_process()

        assert result is True
        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args
        assert call_kwargs.kwargs["start_new_session"] is True
        assert call_kwargs.kwargs["env"]["ONEIRIC_BACKGROUND"] == "1"

    def test_start_creates_pid_file(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        mock_proc = MagicMock()
        mock_proc.pid = 99999

        with patch.object(ProcessManager, "is_running", return_value=False), \
             patch("subprocess.Popen", return_value=mock_proc):
            pm.start_process()

        assert tmp_pid.read_text() == "99999"


class TestStopProcess:
    def test_not_running(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        with patch.object(ProcessManager, "is_running", return_value=False):
            result = pm.stop_process()
        assert result is False

    def test_pid_none(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        pm.pid = None
        with patch.object(ProcessManager, "is_running", return_value=True):
            result = pm.stop_process()
        assert result is False

    def test_stop_sends_sigterm(self, tmp_pid):
        tmp_pid.write_text("42")
        pm = ProcessManager(pid_file=tmp_pid)
        pm.pid = 42

        import oneiric.runtime.process_manager as pm_mod
        with patch.object(ProcessManager, "is_running", return_value=True), \
             patch("os.kill") as mock_kill, \
             patch.object(pm_mod.asyncio, "run"), \
             patch.object(Path, "unlink"):
            # SIGTERM succeeds, process dies on first poll, SIGKILL also dead
            mock_kill.side_effect = [None, OSError("dead"), OSError("already dead")]
            result = pm.stop_process()

        assert result is True
        mock_kill.assert_any_call(42, signal.SIGTERM)

    def test_stop_sigkill_after_timeout(self, tmp_pid):
        tmp_pid.write_text("42")
        pm = ProcessManager(pid_file=tmp_pid)
        pm.pid = 42

        kill_count = 0

        def kill_side_effect(pid, sig):
            nonlocal kill_count
            kill_count += 1
            if sig == signal.SIGTERM:
                return None
            elif sig == 0:
                if kill_count < 12:
                    return None
                raise OSError("dead")
            elif sig == signal.SIGKILL:
                raise OSError("already dead")

        import oneiric.runtime.process_manager as pm_mod
        with patch.object(ProcessManager, "is_running", return_value=True), \
             patch("os.kill", side_effect=kill_side_effect), \
             patch.object(pm_mod.asyncio, "run"), \
             patch.object(Path, "unlink"):
            result = pm.stop_process()

        assert result is True

    def test_stop_os_error(self, tmp_pid):
        tmp_pid.write_text("42")
        pm = ProcessManager(pid_file=tmp_pid)

        with patch("os.kill", side_effect=OSError("perm")), \
             patch.object(Path, "unlink"):
            result = pm.stop_process()

        assert result is False


class TestGetStatus:
    def test_running_status(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        pm.pid = 42
        with patch.object(ProcessManager, "is_running", return_value=True):
            status = pm.get_status()
        assert status["running"] is True
        assert status["pid"] == 42
        assert status["pid_file"] == str(tmp_pid)

    def test_not_running_status(self, tmp_pid):
        pm = ProcessManager(pid_file=tmp_pid)
        with patch.object(ProcessManager, "is_running", return_value=False):
            status = pm.get_status()
        assert status["running"] is False
        assert status["pid"] is None

    def test_pid_file_exists_field(self, tmp_pid):
        tmp_pid.touch()
        pm = ProcessManager(pid_file=tmp_pid)
        with patch.object(ProcessManager, "is_running", return_value=False):
            status = pm.get_status()
        assert status["pid_file_exists"] is True
