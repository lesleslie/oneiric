"""Core admin shell implementation using IPython."""

import asyncio
import logging
from typing import Any

from IPython.terminal.embed import InteractiveShellEmbed
from IPython.terminal.ipapp import load_default_config

from .config import ShellConfig
from .magics import BaseMagics

logger = logging.getLogger(__name__)


class AdminShell:
    """Base IPython admin shell for service administration.

    Provides an interactive IPython shell with pre-configured namespace,
    convenience imports, and magic commands. Can be extended by subclasses
    for application-specific functionality.

    Example:
        >>> from oneiric.shell import AdminShell, ShellConfig
        >>> config = ShellConfig(banner="My App Shell")
        >>> shell = AdminShell(app, config)
        >>> shell.start()
    """

    def __init__(self, app: Any, config: ShellConfig | None = None) -> None:
        """Initialize admin shell.

        Args:
            app: Application instance to expose in shell namespace
            config: Optional shell configuration
        """
        self.app = app
        self.config = config or ShellConfig()
        self.shell: InteractiveShellEmbed | None = None
        self._build_namespace()

    def _build_namespace(self) -> None:
        """Build shell namespace with common imports and helpers.

        Creates a dictionary of objects available in the shell,
        including the application instance, asyncio utilities,
        logging, and optional Rich formatting tools.
        """
        self.namespace: dict[str, Any] = {
            # Application
            "app": self.app,
            # Async utilities
            "asyncio": asyncio,
            "run": asyncio.run,
            # Logging
            "logger": logger,
            # Optional Rich support
            "Console": self._try_import("rich.console", "Console"),
            "Table": self._try_import("rich.table", "Table"),
        }

    def _try_import(self, module_name: str, attr_name: str) -> Any:
        """Safely import optional dependencies.

        Args:
            module_name: Python module path
            attr_name: Attribute name to import

        Returns:
            Imported object or None if unavailable
        """
        try:
            module = __import__(module_name, fromlist=[attr_name])
            return getattr(module, attr_name)
        except (ImportError, AttributeError):
            return None

    def start(self) -> None:
        """Start the interactive shell.

        Initializes IPython configuration, creates the embedded shell,
        registers magic commands, and starts the interactive loop.
        """
        # Load IPython config
        ipython_config = load_default_config()
        ipython_config.TerminalInteractiveShell.colors = "Linux"

        # Create embedded shell
        self.shell = InteractiveShellEmbed(
            config=ipython_config,
            banner1=self._get_banner(),
            user_ns=self.namespace,
            confirm_exit=False,
        )

        # Register magic commands
        self._register_magics()

        logger.info("Starting admin shell...")
        self.shell()

    def _get_banner(self) -> str:
        """Get shell banner.

        Returns:
            Banner string for shell startup
        """
        return f"""
{self.config.banner}
{"=" * 60}
Type 'help()' for Python help or %help_shell for shell commands.
{"=" * 60}
"""

    def _register_magics(self) -> None:
        """Register IPython magic commands.

        Can be overridden in subclasses to register custom magics.
        Base implementation registers basic help and status commands.
        """
        magics = BaseMagics(self.shell)
        magics.set_app(self.app)
        if self.shell:
            self.shell.register_magics(magics)

    def add_helper(self, name: str, func: Any) -> None:
        """Add a helper function to shell namespace.

        Args:
            name: Helper function name
            func: Helper function or callable object
        """
        self.namespace[name] = func
        logger.debug(f"Added helper '{name}' to shell namespace")

    def add_object(self, name: str, obj: Any) -> None:
        """Add an object to shell namespace.

        Args:
            name: Object name
            obj: Any Python object
        """
        self.namespace[name] = obj
        logger.debug(f"Added object '{name}' to shell namespace")
