from dataclasses import dataclass
from typing import Any, Optional

try:
    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


@dataclass
class TableColumn:
    name: str
    width: int | None = None
    justify: str = "left"  # type: ignore[assignment]
    style: str | None = None


class BaseTableFormatter:
    def __init__(self, console: Optional["Console"] = None, max_width: int = 120):
        if not RICH_AVAILABLE:
            self.console = None
        elif console:
            self.console = console
        else:
            self.console = Console(width=max_width)

    def format_table(
        self,
        title: str,
        columns: list[TableColumn],
        rows: list[dict[str, Any]],
    ) -> None:
        if not RICH_AVAILABLE or not self.console:
            self._format_table_fallback(title, columns, rows)
            return

        table = Table(title=title)
        for col in columns:
            table.add_column(
                col.name,
                width=col.width,
                justify=col.justify,  # type: ignore[arg-type]
                style=col.style,
            )

        for row in rows:
            table.add_row(*[str(row.get(col.name, "")) for col in columns])

        self.console.print(table)

    def _format_table_fallback(
        self, title: str, columns: list[TableColumn], rows: list[dict[str, Any]]
    ) -> None:
        print(f"\n{title}")
        print("=" * 80)

        header = " | ".join(col.name for col in columns)
        print(header)
        print("-" * len(header))

        for row in rows:
            row_str = " | ".join(str(row.get(col.name, "")) for col in columns)
            print(row_str)


class BaseLogFormatter:
    def __init__(self, console: Optional["Console"] = None):
        if not RICH_AVAILABLE:
            self.console = None
        elif console:
            self.console = console
        else:
            self.console = Console()

    def format_logs(
        self,
        logs: list[dict[str, Any]],
        level: str | None = None,
        tail: int = 50,
    ) -> None:
        if not logs:
            print("No logs to display")
            return

        if level:
            logs = [log for log in logs if log.get("level") == level]

        logs = logs[-tail:]

        if RICH_AVAILABLE and self.console:
            self._format_logs_rich(logs)
        else:
            self._format_logs_fallback(logs)

    def _format_logs_rich(self, logs: list[dict[str, Any]]) -> None:
        for log in logs:
            level = log.get("level", "INFO")
            style = {
                "ERROR": "bold red",
                "WARNING": "bold yellow",
                "INFO": "blue",
                "DEBUG": "dim",
            }.get(level, "")

            timestamp = log.get("timestamp", "")[:19]
            message = log.get("message", "")

            if self.console:
                self.console.print(f"[{timestamp}] [{level}] {message}", style=style)

    def _format_logs_fallback(self, logs: list[dict[str, Any]]) -> None:
        for log in logs:
            timestamp = log.get("timestamp", "")[:19]
            level = log.get("level", "INFO")
            message = log.get("message", "")
            print(f"{timestamp} [{level}] {message}")


class BaseProgressFormatter:
    def __init__(self, console: Optional["Console"] = None):
        if not RICH_AVAILABLE:
            self.console = None
        elif console:
            self.console = console
        else:
            self.console = Console()

    def create_progress(self) -> Any:
        if not RICH_AVAILABLE or not self.console:
            return None

        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=self.console,
        )

    def format_progress(self, message: str) -> None:
        if RICH_AVAILABLE and self.console:
            self.console.print(f"[dim]⠋ {message}[/dim]")
        else:
            print(f"... {message}")
