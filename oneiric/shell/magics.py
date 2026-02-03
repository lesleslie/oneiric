from typing import Any

from IPython.core.magic import Magics, line_magic, magics_class


@magics_class
class BaseMagics(Magics):
    def __init__(self, shell):
        super().__init__(shell)
        self.app = None

    def set_app(self, app: Any) -> None:
        self.app = app

    @line_magic
    def help_shell(self, line: str) -> None:
        print("Admin Shell Commands:")
        print("  %help_shell - Show help")
        print("  %status - Show status")

    @line_magic
    def status(self, line: str) -> None:
        print("Shell Status:")
        print(f"  Application: {self.app.__class__.__name__ if self.app else 'None'}")
        shell_version = getattr(self.shell, "__version__", "unknown")
        print(f"  Shell: IPython {shell_version}")
