"""Base IPython magic commands for admin shell."""

from typing import Any

from IPython.core.magic import Magics, line_magic, magics_class


@magics_class
class BaseMagics(Magics):
    """Base magic commands for admin shell.

    Provides basic magic commands that can be extended by
    application-specific implementations.
    """

    def __init__(self, shell):
        """Initialize magics.

        Args:
            shell: IPython shell instance
        """
        super().__init__(shell)
        self.app = None

    def set_app(self, app: Any) -> None:
        """Set application reference.

        Args:
            app: Application instance
        """
        self.app = app

    @line_magic
    def help_shell(self, line: str) -> None:
        """Show shell help information.

        Args:
            line: Command arguments (unused)
        """
        print("Admin Shell Commands:")
        print("  %help_shell - Show help")
        print("  %status - Show status")

    @line_magic
    def status(self, line: str) -> None:
        """Show shell and application status.

        Args:
            line: Command arguments (unused)
        """
        print("Shell Status:")
        print(f"  Application: {self.app.__class__.__name__ if self.app else 'None'}")
        shell_version = getattr(self.shell, "__version__", "unknown")
        print(f"  Shell: IPython {shell_version}")
