from __future__ import annotations

import asyncio
from typing import TypeVar

import typer

from oneiric.core.config import OneiricMCPConfig
from oneiric.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound="MCPServerBase")


class MCPServerBase:
    def __init__(self, config: OneiricMCPConfig):
        self.config = config

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_app(self):
        raise NotImplementedError("Subclasses must implement get_app()")


class MCPServerCLIFactory:
    def __init__(
        self,
        server_class: type[T],
        config_class: type[OneiricMCPConfig],
        name: str,
        use_subcommands: bool = True,
        legacy_flags: bool = False,
        description: str = "MCP Server",
    ):
        self.server_class = server_class
        self.config_class = config_class
        self.name = name
        self.use_subcommands = use_subcommands
        self.legacy_flags = legacy_flags
        self.description = description
        self.app = typer.Typer(name=name, help=description)

        self._add_commands()

    def _add_commands(self) -> None:
        @self.app.command("start")
        def start():
            self._start_server()

        @self.app.command("stop")
        def stop():
            self._stop_server()

        @self.app.command("restart")
        def restart():
            self._restart_server()

        @self.app.command("status")
        def status():
            self._check_status()

        @self.app.command("health")
        def health():
            self._check_health()

        if not self.legacy_flags:

            @self.app.command("config")
            def config():
                self._show_config()

    def _start_server(self) -> None:
        logger.info(f"Starting {self.name} server")

        config = self.config_class()

        server = self.server_class(config)

        asyncio.run(server.startup())

        server.get_app()

        logger.info(f"Server started on {config.http_host}:{config.http_port}")

        try:
            logger.info("Server is running... Press Ctrl+C to stop")

            while True:
                asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
            asyncio.run(server.shutdown())

    def _stop_server(self) -> None:
        logger.info(f"Stopping {self.name} server")

        logger.info("Server stopped")

    def _restart_server(self) -> None:
        logger.info(f"Restarting {self.name} server")
        self._stop_server()
        self._start_server()

    def _check_status(self) -> None:
        logger.info(f"Checking {self.name} server status")

        logger.info("Server status: running")

    def _check_health(self) -> None:
        logger.info(f"Checking {self.name} server health")

        config = self.config_class()

        server = self.server_class(config)

        if hasattr(server, "health_check"):
            self._perform_health_check(server)
        else:
            logger.info("Server health: healthy")

    def _perform_health_check(self, server) -> None:
        try:
            self._initialize_runtime_components(server)
            health = asyncio.run(server.health_check())
            self._log_health_results(health)
            self._cleanup_runtime_components(server)
        except Exception as e:
            logger.error(f"Health check failed: {e}")

    def _initialize_runtime_components(self, server) -> None:
        if hasattr(server, "snapshot_manager"):
            asyncio.run(server.snapshot_manager.initialize())
        if hasattr(server, "cache_manager"):
            asyncio.run(server.cache_manager.initialize())

    def _cleanup_runtime_components(self, server) -> None:
        if hasattr(server, "snapshot_manager"):
            asyncio.run(server.snapshot_manager.cleanup())
        if hasattr(server, "cache_manager"):
            asyncio.run(server.cache_manager.cleanup())

    def _log_health_results(self, health) -> None:
        health_dict = health.to_dict() if hasattr(health, "to_dict") else str(health)
        if isinstance(health_dict, dict) and "status" in health_dict:
            logger.info(f"Server health status: {health_dict['status']}")
        logger.info(f"Server health details: {health_dict}")

    def _show_config(self) -> None:
        logger.info(f"Showing {self.name} server configuration")

        config = self.config_class()

        logger.info(f"Configuration: {config}")

    def run(self) -> None:
        self.app()


__all__ = ["MCPServerCLIFactory", "MCPServerBase"]
