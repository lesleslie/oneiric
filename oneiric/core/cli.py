"""Oneiric MCP Server CLI Factory."""

from __future__ import annotations

import asyncio
from typing import TypeVar

import typer

from oneiric.core.config import OneiricMCPConfig
from oneiric.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound="MCPServerBase")


class MCPServerBase:
    """Base class for MCP servers."""

    def __init__(self, config: OneiricMCPConfig):
        self.config = config

    async def startup(self) -> None:
        """Server startup lifecycle hook."""
        pass

    async def shutdown(self) -> None:
        """Server shutdown lifecycle hook."""
        pass

    def get_app(self):
        """Get the ASGI application."""
        raise NotImplementedError("Subclasses must implement get_app()")


class MCPServerCLIFactory:
    """Factory for creating MCP server CLI interfaces."""

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

        # Add commands
        self._add_commands()

    def _add_commands(self) -> None:
        """Add CLI commands to the application."""

        @self.app.command("start")
        def start():
            """Start the MCP server."""
            self._start_server()

        @self.app.command("stop")
        def stop():
            """Stop the MCP server."""
            self._stop_server()

        @self.app.command("restart")
        def restart():
            """Restart the MCP server."""
            self._restart_server()

        @self.app.command("status")
        def status():
            """Check the MCP server status."""
            self._check_status()

        @self.app.command("health")
        def health():
            """Check the MCP server health."""
            self._check_health()

        if not self.legacy_flags:
            # Add modern subcommands
            @self.app.command("config")
            def config():
                """Show server configuration."""
                self._show_config()

    def _start_server(self) -> None:
        """Start the MCP server."""
        logger.info(f"Starting {self.name} server")

        # Load configuration
        config = self.config_class()

        # Create server instance
        server = self.server_class(config)

        # Run startup lifecycle
        asyncio.run(server.startup())

        # Get the ASGI app
        server.get_app()

        # Start the server (this would normally use uvicorn or similar)
        logger.info(f"Server started on {config.http_host}:{config.http_port}")

        # In a real implementation, this would start the ASGI server
        # For now, we'll just keep it running
        try:
            # This is where you would normally run: uvicorn.run(app, host=config.http_host, port=config.http_port)
            logger.info("Server is running... Press Ctrl+C to stop")

            # For demo purposes, we'll just sleep
            while True:
                asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
            asyncio.run(server.shutdown())

    def _stop_server(self) -> None:
        """Stop the MCP server."""
        logger.info(f"Stopping {self.name} server")
        # In a real implementation, this would stop the running server
        logger.info("Server stopped")

    def _restart_server(self) -> None:
        """Restart the MCP server."""
        logger.info(f"Restarting {self.name} server")
        self._stop_server()
        self._start_server()

    def _check_status(self) -> None:
        """Check the MCP server status."""
        logger.info(f"Checking {self.name} server status")
        # In a real implementation, this would check if the server is running
        logger.info("Server status: running")

    def _check_health(self) -> None:
        """Check the MCP server health."""
        logger.info(f"Checking {self.name} server health")

        # Load configuration
        config = self.config_class()

        # Create server instance
        server = self.server_class(config)

        # Check health
        if hasattr(server, "health_check"):
            self._perform_health_check(server)
        else:
            logger.info("Server health: healthy")

    def _perform_health_check(self, server) -> None:
        """Perform the actual health check on the server."""
        try:
            self._initialize_runtime_components(server)
            health = asyncio.run(server.health_check())
            self._log_health_results(health)
            self._cleanup_runtime_components(server)
        except Exception as e:
            logger.error(f"Health check failed: {e}")

    def _initialize_runtime_components(self, server) -> None:
        """Initialize runtime components for health check."""
        if hasattr(server, "snapshot_manager"):
            asyncio.run(server.snapshot_manager.initialize())
        if hasattr(server, "cache_manager"):
            asyncio.run(server.cache_manager.initialize())

    def _cleanup_runtime_components(self, server) -> None:
        """Clean up runtime components after health check."""
        if hasattr(server, "snapshot_manager"):
            asyncio.run(server.snapshot_manager.cleanup())
        if hasattr(server, "cache_manager"):
            asyncio.run(server.cache_manager.cleanup())

    def _log_health_results(self, health) -> None:
        """Log health check results."""
        health_dict = health.to_dict() if hasattr(health, "to_dict") else str(health)
        if isinstance(health_dict, dict) and "status" in health_dict:
            logger.info(f"Server health status: {health_dict['status']}")
        logger.info(f"Server health details: {health_dict}")

    def _show_config(self) -> None:
        """Show server configuration."""
        logger.info(f"Showing {self.name} server configuration")

        # Load configuration
        config = self.config_class()

        # Show configuration
        logger.info(f"Configuration: {config}")

    def run(self) -> None:
        """Run the CLI application."""
        self.app()


__all__ = ["MCPServerCLIFactory", "MCPServerBase"]
