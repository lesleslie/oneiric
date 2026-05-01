"""Tests for shell formatters."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from oneiric.shell.formatters import (
    BaseLogFormatter,
    BaseProgressFormatter,
    BaseTableFormatter,
    TableColumn,
)


class TestTableColumn:
    def test_defaults(self):
        col = TableColumn(name="test")
        assert col.name == "test"
        assert col.width is None
        assert col.justify == "left"
        assert col.style is None

    def test_custom(self):
        col = TableColumn(name="id", width=10, justify="right", style="bold")
        assert col.name == "id"
        assert col.width == 10
        assert col.justify == "right"
        assert col.style == "bold"


class TestBaseTableFormatter:
    def test_format_table_with_console(self):
        mock_console = MagicMock()
        fmt = BaseTableFormatter(console=mock_console)
        columns = [TableColumn(name="a"), TableColumn(name="b")]
        rows = [{"a": "1", "b": "2"}]
        fmt.format_table("Test", columns, rows)
        mock_console.print.assert_called_once()

    def test_format_table_fallback_no_console(self):
        fmt = BaseTableFormatter(console=None)
        with patch("oneiric.shell.formatters.RICH_AVAILABLE", False):
            # Re-init to pick up the patched flag
            fmt2 = BaseTableFormatter.__new__(BaseTableFormatter)
            fmt2.console = None
            fmt2._format_table_fallback = fmt._format_table_fallback
            with patch("builtins.print") as mock_print:
                fmt2._format_table_fallback("Title", [TableColumn(name="c")], [{"c": "x"}])
                mock_print.assert_called()

    def test_format_table_fallback_empty_rows(self):
        fmt = BaseTableFormatter.__new__(BaseTableFormatter)
        fmt.console = None
        with patch("builtins.print") as mock_print:
            fmt._format_table_fallback("Empty", [TableColumn(name="c")], [])
            printed = [str(c) for c in mock_print.call_args_list]
            assert any("Empty" in p for p in printed)

    def test_format_table_missing_column_value(self):
        mock_console = MagicMock()
        fmt = BaseTableFormatter(console=mock_console)
        columns = [TableColumn(name="a"), TableColumn(name="b")]
        rows = [{"a": "1"}]  # 'b' missing
        fmt.format_table("Test", columns, rows)
        mock_console.print.assert_called_once()

    def test_max_width_passed_to_console(self):
        with patch("oneiric.shell.formatters.Console") as mock_console_cls:
            fmt = BaseTableFormatter(max_width=80)
            mock_console_cls.assert_called_once_with(width=80)


class TestBaseLogFormatter:
    def test_format_logs_empty(self, capsys):
        fmt = BaseLogFormatter(console=None)
        with patch("oneiric.shell.formatters.RICH_AVAILABLE", False):
            fmt2 = BaseLogFormatter.__new__(BaseLogFormatter)
            fmt2.console = None
            fmt2.format_logs = fmt.format_logs
            fmt2.format_logs([])
            assert "No logs" in capsys.readouterr().out

    def test_format_logs_level_filter(self, capsys):
        logs = [
            {"level": "INFO", "timestamp": "2026-01-01T00:00:00", "message": "info msg"},
            {"level": "ERROR", "timestamp": "2026-01-01T00:00:01", "message": "err msg"},
        ]
        fmt = BaseLogFormatter.__new__(BaseLogFormatter)
        fmt.console = None
        fmt.format_logs(logs, level="ERROR")
        output = capsys.readouterr().out
        assert "err msg" in output
        assert "info msg" not in output

    def test_format_logs_tail(self, capsys):
        logs = [{"level": "INFO", "timestamp": f"2026-01-01T00:0{i}:00", "message": f"msg{i}"} for i in range(10)]
        fmt = BaseLogFormatter.__new__(BaseLogFormatter)
        fmt.console = None
        fmt.format_logs(logs, tail=3)
        output = capsys.readouterr().out
        assert "msg7" in output
        assert "msg0" not in output

    def test_format_logs_fallback(self, capsys):
        logs = [
            {"level": "WARNING", "timestamp": "2026-01-01T00:00:00.123456", "message": "warn msg"},
            {"level": "DEBUG", "timestamp": "2026-01-01T00:00:01", "message": "debug msg"},
        ]
        fmt = BaseLogFormatter.__new__(BaseLogFormatter)
        fmt.console = None
        fmt._format_logs_fallback(logs)
        output = capsys.readouterr().out
        assert "warn msg" in output
        assert "debug msg" in output

    def test_format_logs_rich_with_console(self):
        mock_console = MagicMock()
        fmt = BaseLogFormatter(console=mock_console)
        logs = [
            {"level": "ERROR", "timestamp": "2026-01-01T00:00:00", "message": "err"},
        ]
        fmt._format_logs_rich(logs)
        mock_console.print.assert_called_once()

    def test_format_logs_unknown_level(self):
        mock_console = MagicMock()
        fmt = BaseLogFormatter(console=mock_console)
        logs = [
            {"level": "CUSTOM", "timestamp": "2026-01-01T00:00:00", "message": "custom"},
        ]
        fmt._format_logs_rich(logs)
        mock_console.print.assert_called_once()

    def test_log_timestamp_truncation(self):
        mock_console = MagicMock()
        fmt = BaseLogFormatter(console=mock_console)
        logs = [
            {"level": "INFO", "timestamp": "2026-01-01T00:00:00.123456789", "message": "test"},
        ]
        fmt._format_logs_rich(logs)
        call_args = mock_console.print.call_args[0][0]
        # Timestamp should be truncated to 19 chars
        assert "2026-01-01T00:00:00" in call_args

    def test_log_missing_fields(self):
        mock_console = MagicMock()
        fmt = BaseLogFormatter(console=mock_console)
        logs = [
            {"message": "no level or timestamp"},
        ]
        fmt._format_logs_rich(logs)
        mock_console.print.assert_called_once()


class TestBaseProgressFormatter:
    def test_create_progress_no_rich(self):
        with patch("oneiric.shell.formatters.RICH_AVAILABLE", False):
            fmt = BaseProgressFormatter.__new__(BaseProgressFormatter)
            fmt.console = None
            result = fmt.create_progress()
            assert result is None

    def test_create_progress_no_console(self):
        with patch("oneiric.shell.formatters.RICH_AVAILABLE", True):
            fmt = BaseProgressFormatter.__new__(BaseProgressFormatter)
            fmt.console = None
            result = fmt.create_progress()
            assert result is None

    def test_create_progress_with_console(self):
        mock_console = MagicMock()
        with patch("oneiric.shell.formatters.RICH_AVAILABLE", True), \
             patch("oneiric.shell.formatters.Progress") as mock_progress:
            fmt = BaseProgressFormatter(console=mock_console)
            result = fmt.create_progress()
            assert result is not None
            mock_progress.assert_called_once()

    def test_format_progress_rich(self):
        mock_console = MagicMock()
        fmt = BaseProgressFormatter(console=mock_console)
        fmt.format_progress("loading...")
        mock_console.print.assert_called_once()

    def test_format_progress_fallback(self, capsys):
        fmt = BaseProgressFormatter.__new__(BaseProgressFormatter)
        fmt.console = None
        fmt.format_progress("loading...")
        assert "loading..." in capsys.readouterr().out
