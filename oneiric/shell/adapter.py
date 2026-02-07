"""Oneiric admin shell adapter.

This module provides Oneiric-specific admin shell functionality extending
the base AdminShell with Oneiric-specific features:

- Component resolution and lifecycle management
- Adapter management
- Configuration layer inspection
- Session tracking via Session-Buddy MCP
"""

from __future__ import annotations

import asyncio
import logging

# Use relative imports to avoid circular dependency
from .core import AdminShell
from .config import ShellConfig
from .session_tracker import SessionEventEmitter
from oneiric.core.config import OneiricSettings

logger = logging.getLogger(__name__)


class OneiricShell(AdminShell):
    """Oneiric-specific admin shell.

    Extends the base AdminShell with Oneiric-specific namespace,
    formatters, helpers, and magic commands for component resolution
    and lifecycle management.

    Features:
    - Universal component resolution
    - Configuration layer inspection
    - Adapter management
    - Lifecycle state queries
    - Session tracking via Session-Buddy MCP

    Example:
        >>> from oneiric.shell.adapter import OneiricShell
        >>> from oneiric.core.config import load_settings
        >>> config = load_settings()
        >>> shell = OneiricShell(config)
        >>> shell.start()
    """

    def __init__(self, app: OneiricSettings, config: ShellConfig | None = None) -> None:
        """Initialize Oneiric shell.

        Args:
            app: OneiricSettings instance (configuration object)
            config: Optional shell configuration
        """
        super().__init__(app, config)
        self._add_oneiric_namespace()

        # Override session tracker with Oneiric-specific metadata
        # SessionEventEmitter tracks shell sessions via Session-Buddy MCP
        self.session_tracker = SessionEventEmitter(
            component_name="oneiric",
        )
        self._session_id: str | None = None

    def _add_oneiric_namespace(self) -> None:
        """Add Oneiric-specific objects to shell namespace."""
        self.namespace.update(
            {
                # Configuration class
                "OneiricSettings": OneiricSettings,
                # Convenience helper for config inspection
                "config": self.app,
                # Async helpers
                "reload_settings": lambda: asyncio.run(self._reload_settings()),
                "show_layers": lambda: asyncio.run(self._show_config_layers()),
                "validate_config": lambda: asyncio.run(self._validate_config()),
            }
        )

    def _get_component_name(self) -> str | None:
        """Return Oneiric component name for session tracking.

        Overrides base class method to provide component-specific name.

        Returns:
            Component name "oneiric" for session tracking
        """
        return "oneiric"

    def _get_component_version(self) -> str:
        """Get Oneiric package version.

        Overrides base class method to provide component-specific version
        for session tracking metadata.

        Returns:
            Oneiric version string or "unknown" if unavailable
        """
        try:
            import importlib.metadata as importlib_metadata

            return importlib_metadata.version("oneiric")
        except Exception:
            return "unknown"

    def _get_adapters_info(self) -> list[str]:
        """Get Oneiric adapter information.

        Oneiric is the foundation component that provides configuration
        and lifecycle management to all other components. It has no
        orchestration adapters of its own.

        Returns:
            Empty list (Oneiric is foundation, not an orchestrator)
        """
        return []

    def _get_banner(self) -> str:
        """Get Oneiric-specific banner."""
        version = self._get_component_version()

        return f"""
Oneiric Admin Shell v{version}
{'=' * 60}
Universal Component Resolution & Lifecycle Management

Session Tracking: Enabled
  Shell sessions tracked via Session-Buddy MCP
  Metadata: version, config layers, lifecycle state

Oneiric is the foundation component providing:
  - Layered configuration (defaults → yaml → local → env)
  - Component lifecycle management
  - Universal adapter system
  - Resolution and activation APIs

Convenience Functions:
  reload_settings()   - Reload configuration from all layers
  show_layers()       - Display config layer precedence
  validate_config()   - Validate current configuration

Available Objects:
  config              - Current OneiricSettings instance
  OneiricSettings     - Configuration class

Type 'help()' for Python help or %help_shell for shell commands
{'=' * 60}
"""

    async def _reload_settings(self) -> None:
        """Reload configuration from all layers.

        Helper function available in shell namespace.
        """
        from oneiric.core.config import load_settings

        self.app = load_settings()
        self.namespace["config"] = self.app
        logger.info("Settings reloaded")

    async def _show_config_layers(self) -> None:
        """Display configuration layer precedence.

        Helper function available in shell namespace.
        """
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="Configuration Layer Precedence")

        table.add_column("Layer", style="cyan")
        table.add_column("Source", style="green")
        table.add_column("Status", style="yellow")

        layers = [
            ("1. Defaults", "Pydantic field defaults", "Always active"),
            ("2. YAML", "settings/oneiric.yaml", "Committed to git"),
            ("3. Local", "settings/local.yaml", "Gitignored"),
            ("4. Environment", "ONEIRIC_* variables", "Runtime overrides"),
        ]

        for layer, source, status in layers:
            table.add_row(layer, source, status)

        console.print(table)

    async def _validate_config(self) -> None:
        """Validate current configuration.

        Helper function available in shell namespace.
        """
        from rich.console import Console

        console = Console()

        try:
            # Re-validate Pydantic model
            self.app.model_validate(self.app.model_dump())
            console.print("[green]✓ Configuration is valid[/green]")
        except Exception as e:
            console.print(f"[red]✗ Configuration error: {e}[/red]")

    async def _emit_session_start(self) -> None:
        """Emit session start event with Oneiric-specific metadata."""
        try:
            metadata = {
                "version": self._get_component_version(),
                "adapters": self._get_adapters_info(),
                "component_type": "foundation",
            }

            self._session_id = await self.session_tracker.emit_session_start(
                shell_type=self.__class__.__name__,
                metadata=metadata,
            )

            if self._session_id:
                logger.info(f"Oneiric shell session started: {self._session_id}")
            else:
                logger.debug("Session tracking unavailable (Session-Buddy MCP not reachable)")
        except Exception as e:
            logger.debug(f"Failed to emit session start: {e}")

    async def _emit_session_end(self) -> None:
        """Emit session end event."""
        if not self._session_id:
            return

        try:
            await self.session_tracker.emit_session_end(
                session_id=self._session_id,
                metadata={},
            )
            logger.info(f"Oneiric shell session ended: {self._session_id}")
        except Exception as e:
            logger.debug(f"Failed to emit session end: {e}")
        finally:
            self._session_id = None

    async def close(self) -> None:
        """Close shell and cleanup resources."""
        await self._emit_session_end()
        await self.session_tracker.close()
