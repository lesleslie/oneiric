"""Oneiric admin shell for interactive administration.

This module provides a reusable IPython-based admin shell that can be
adapted for any Oneiric-based application. It includes:

- AdminShell base class for shell initialization
- ShellConfig for configuration management
- Base formatters for tables and logs
- Base magics for IPython command extensions

Example:
    >>> from oneiric.shell import AdminShell, ShellConfig
    >>> config = ShellConfig(banner="My App Shell")
    >>> shell = AdminShell(app, config)
    >>> shell.start()
"""

from .config import ShellConfig
from .core import AdminShell
from .formatters import (
    BaseLogFormatter,
    BaseProgressFormatter,
    BaseTableFormatter,
    TableColumn,
)

__all__ = [
    "AdminShell",
    "ShellConfig",
    "BaseTableFormatter",
    "BaseProgressFormatter",
    "BaseLogFormatter",
    "TableColumn",
]
