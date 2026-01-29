"""Base formatters for admin shell display."""

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
    """Table column specification.

    Attributes:
        name: Column header name
        width: Optional fixed width (None for auto)
        justify: Text justification (left, center, right)
        style: Optional Rich style string
    """

    name: str
    width: int | None = None
    justify: str = "left"  # type: ignore[assignment]
    style: str | None = None


class BaseTableFormatter:
    """Format data as Rich tables.

    Provides consistent table formatting for shell output with
    support for custom column specifications and styling.
    """

    def __init__(self, console: Optional["Console"] = None, max_width: int = 120):
        """Initialize table formatter.

        Args:
            console: Optional Rich Console instance
            max_width: Maximum table width
        """
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
        """Display a table.

        Args:
            title: Table title
            columns: List of column specifications
            rows: List of row data dictionaries
        """
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
        """Fallback table formatting without Rich.

        Args:
            title: Table title
            columns: List of column specifications
            rows: List of row data dictionaries
        """
        print(f"\n{title}")
        print("=" * 80)

        # Print header
        header = " | ".join(col.name for col in columns)
        print(header)
        print("-" * len(header))

        # Print rows
        for row in rows:
            row_str = " | ".join(str(row.get(col.name, "")) for col in columns)
            print(row_str)


class BaseLogFormatter:
    """Format log entries for display.

    Provides colored log output with support for filtering
    by log level and limiting output lines.
    """

    def __init__(self, console: Optional["Console"] = None):
        """Initialize log formatter.

        Args:
            console: Optional Rich Console instance
        """
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
        """Display log entries with optional filtering.

        Args:
            logs: List of log entry dictionaries
            level: Optional log level filter (ERROR, WARNING, INFO)
            tail: Number of most recent lines to display
        """
        if not logs:
            print("No logs to display")
            return

        # Filter by level
        if level:
            logs = [log for log in logs if log.get("level") == level]

        # Get last N lines
        logs = logs[-tail:]

        if RICH_AVAILABLE and self.console:
            self._format_logs_rich(logs)
        else:
            self._format_logs_fallback(logs)

    def _format_logs_rich(self, logs: list[dict[str, Any]]) -> None:
        """Format logs with Rich colors.

        Args:
            logs: List of log entries
        """
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
        """Format logs without Rich.

        Args:
            logs: List of log entries
        """
        for log in logs:
            timestamp = log.get("timestamp", "")[:19]
            level = log.get("level", "INFO")
            message = log.get("message", "")
            print(f"{timestamp} [{level}] {message}")


class BaseProgressFormatter:
    """Format progress indicators for long-running operations.

    Provides spinners and progress bars for async operations.
    """

    def __init__(self, console: Optional["Console"] = None):
        """Initialize progress formatter.

        Args:
            console: Optional Rich Console instance
        """
        if not RICH_AVAILABLE:
            self.console = None
        elif console:
            self.console = console
        else:
            self.console = Console()

    def create_progress(self) -> Any:
        """Create a Rich Progress object.

        Returns:
            Progress object or None if Rich unavailable
        """
        if not RICH_AVAILABLE or not self.console:
            return None

        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=self.console,
        )

    def format_progress(self, message: str) -> None:
        """Display a simple progress message.

        Args:
            message: Progress message to display
        """
        if RICH_AVAILABLE and self.console:
            self.console.print(f"[dim]⠋ {message}[/dim]")
        else:
            print(f"... {message}")
