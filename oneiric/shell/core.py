import asyncio
import logging
from typing import Any

from IPython.terminal.embed import InteractiveShellEmbed
from IPython.terminal.ipapp import load_default_config

from .config import ShellConfig
from .magics import BaseMagics

logger = logging.getLogger(__name__)


class AdminShell:
    def __init__(self, app: Any, config: ShellConfig | None = None) -> None:
        self.app = app
        self.config = config or ShellConfig()
        self.shell: InteractiveShellEmbed | None = None
        self._build_namespace()

    def _build_namespace(self) -> None:
        self.namespace: dict[str, Any] = {
            "app": self.app,
            "asyncio": asyncio,
            "run": asyncio.run,
            "logger": logger,
            "Console": self._try_import("rich.console", "Console"),
            "Table": self._try_import("rich.table", "Table"),
        }

    def _try_import(self, module_name: str, attr_name: str) -> Any:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            return getattr(module, attr_name)
        except (ImportError, AttributeError):
            return None

    def start(self) -> None:
        ipython_config = load_default_config()
        ipython_config.TerminalInteractiveShell.colors = "Linux"

        self.shell = InteractiveShellEmbed(
            config=ipython_config,
            banner1=self._get_banner(),
            user_ns=self.namespace,
            confirm_exit=False,
        )

        self._register_magics()

        logger.info("Starting admin shell...")
        self.shell()

    def _get_banner(self) -> str:
        return f"""
{self.config.banner}
{"=" * 60}
Type 'help()' for Python help or %help_shell for shell commands.
{"=" * 60}
"""

    def _register_magics(self) -> None:
        magics = BaseMagics(self.shell)
        magics.set_app(self.app)
        if self.shell:
            self.shell.register_magics(magics)

    def add_helper(self, name: str, func: Any) -> None:
        self.namespace[name] = func
        logger.debug(f"Added helper '{name}' to shell namespace")

    def add_object(self, name: str, obj: Any) -> None:
        self.namespace[name] = obj
        logger.debug(f"Added object '{name}' to shell namespace")
