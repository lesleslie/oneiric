import atexit
import asyncio
import logging
import threading
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

        # Session tracking (initialized to None, will be created if available)
        self.session_tracker: Any = None
        self.session_id: str | None = None

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
        """Start the shell with session tracking."""
        ipython_config = load_default_config()
        ipython_config.TerminalInteractiveShell.colors = "Linux"

        self.shell = InteractiveShellEmbed(
            config=ipython_config,
            banner1=self._get_banner(),
            user_ns=self.namespace,
            confirm_exit=False,
        )

        # Notify session start (fire-and-forget, don't block startup)
        self._notify_session_start_async()

        # Register exit hook for session end (using atexit)
        atexit.register(self._sync_session_end)

        self._register_magics()

        logger.info("Starting admin shell...")
        self.shell()

    def _notify_session_start_async(self) -> None:
        """Notify session start asynchronously without blocking shell startup."""
        try:
            loop = asyncio.get_running_loop()
            # Create task in existing loop
            asyncio.create_task(self._notify_session_start())
        except RuntimeError:
            # No running loop, safe to use run()
            asyncio.run(self._notify_session_start())

    async def _notify_session_start(self) -> None:
        """Notify Session-Buddy of session start."""
        # Try to import SessionEventEmitter
        if self.session_tracker is None:
            try:
                from .session_tracker import SessionEventEmitter

                self.session_tracker = SessionEventEmitter(
                    component_name=self._get_component_name() or "unknown",
                )
            except ImportError:
                logger.debug("SessionEventEmitter not available - session tracking disabled")
                return

        if self.session_tracker:
            shell_type = self.__class__.__name__
            metadata = {
                "component_version": self._get_component_version(),
                "adapters": self._get_adapters_info(),
            }
            self.session_id = await self.session_tracker.emit_session_start(
                shell_type=shell_type,
                metadata=metadata,
            )

    async def _notify_session_end(self) -> None:
        """Notify Session-Buddy of session end."""
        if self.session_id and self.session_tracker:
            await self.session_tracker.emit_session_end(
                session_id=self.session_id,
                metadata={"duration_seconds": None},  # Calculated by Session-Buddy
            )

    def _sync_session_end(self) -> None:
        """Synchronous session end handler (runs in thread)."""
        if self.session_id and self.session_tracker:
            def emit_in_thread():
                """Emit session end in background thread."""
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self._notify_session_end())
                except Exception as e:
                    logger.error(f"Session end emission failed: {e}")
                finally:
                    loop.close()

            thread = threading.Thread(target=emit_in_thread, daemon=True)
            thread.start()
            # Don't join - fire and forget

    def _get_component_name(self) -> str | None:
        """Get component name (to be overridden by subclasses)."""
        return None

    def _get_component_version(self) -> str:
        """Get component version (to be overridden)."""
        try:
            import importlib.metadata as importlib_metadata

            component_name = self._get_component_name()
            if component_name:
                return importlib_metadata.version(component_name)
            return "unknown"
        except Exception:
            return "unknown"

    def _get_adapters_info(self) -> list[str]:
        """Get enabled adapters (to be overridden)."""
        return []  # Base implementation

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
