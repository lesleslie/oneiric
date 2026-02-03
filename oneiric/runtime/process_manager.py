import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any


class ProcessManager:
    def __init__(self, pid_file: str | Path | None = None):
        self.pid_file = Path(pid_file or "./.oneiric.pid")
        self.pid: int | None = None

    def is_running(self) -> bool:
        if not self.pid_file.exists():
            return False

        try:
            with self.pid_file.open() as f:
                pid = int(f.read().strip())
                self.pid = pid
        except (ValueError, FileNotFoundError):
            return False

        try:
            os.kill(pid, 0)
            return True
        except OSError:
            self.pid_file.unlink(missing_ok=True)
            return False

    def _build_orchestrate_command(
        self,
        config_path: str | None = None,
        profile: str | None = None,
        manifest: str | None = None,
        refresh_interval: float | None = None,
        no_remote: bool = False,
        workflow_checkpoints: str | None = None,
        no_workflow_checkpoints: bool = False,
        http_port: int | None = None,
        http_host: str = "0.0.0.0",
        no_http: bool = False,
    ) -> list[str]:
        cmd = [sys.executable, "-m", "oneiric.cli", "orchestrate"]

        value_args = {
            "--config": config_path,
            "--profile": profile,
            "--manifest": manifest,
            "--refresh-interval": str(refresh_interval)
            if refresh_interval is not None
            else None,
            "--workflow-checkpoints": workflow_checkpoints,
            "--http-port": str(http_port) if http_port is not None else None,
            "--http-host": http_host if http_host != "0.0.0.0" else None,
        }

        for flag, value in value_args.items():
            if value:
                cmd.extend([flag, value])

        if no_remote:
            cmd.append("--no-remote")
        if no_workflow_checkpoints:
            cmd.append("--no-workflow-checkpoints")
        if no_http:
            cmd.append("--no-http")

        return cmd

    def start_process(
        self,
        config_path: str | None = None,
        profile: str | None = None,
        manifest: str | None = None,
        refresh_interval: float | None = None,
        no_remote: bool = False,
        workflow_checkpoints: str | None = None,
        no_workflow_checkpoints: bool = False,
        http_port: int | None = None,
        http_host: str = "0.0.0.0",
        no_http: bool = False,
    ) -> bool:
        if self.is_running():
            print(f"Orchestrator is already running (PID: {self.pid})")
            return False

        cmd = self._build_orchestrate_command(
            config_path=config_path,
            profile=profile,
            manifest=manifest,
            refresh_interval=refresh_interval,
            no_remote=no_remote,
            workflow_checkpoints=workflow_checkpoints,
            no_workflow_checkpoints=no_workflow_checkpoints,
            http_port=http_port,
            http_host=http_host,
            no_http=no_http,
        )

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={
                **os.environ,
                "ONEIRIC_BACKGROUND": "1",
                "ONEIRIC_PID_FILE": str(self.pid_file),
            },
        )

        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.pid_file, "w") as f:
            f.write(str(process.pid))

        print(f"Orchestrator started in background with PID: {process.pid}")
        return True

    def stop_process(self) -> bool:
        if not self.is_running():
            print("Orchestrator is not running")
            return False

        if self.pid is None:
            print("PID is not available")
            return False

        try:
            os.kill(self.pid, signal.SIGTERM)

            for _ in range(10):
                try:
                    os.kill(self.pid, 0)
                    asyncio.run(asyncio.sleep(1))
                except OSError:
                    break

            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass

            self.pid_file.unlink(missing_ok=True)
            print(f"Orchestrator (PID: {self.pid}) stopped")
            return True
        except OSError as e:
            print(f"Failed to stop orchestrator: {e}")
            return False

    def get_status(self) -> dict[str, Any]:
        running = self.is_running()
        status = {
            "running": running,
            "pid": self.pid if running else None,
            "pid_file": str(self.pid_file),
            "pid_file_exists": self.pid_file.exists(),
        }

        return status
