"""Tests for the ``oneiric mcp`` CLI subcommand (REQ-007).

Verifies the Typer app shape (``mcp_app`` is registered with the four
expected subcommands) and the help output is human-readable. The actual
lifecycle helpers (``_resolve_pid_file``, ``_is_pid_alive``, etc.) are
exercised in tests/cli/test_http_cli.py — those modules share the same
template so we don't duplicate the same shapes here.
"""

from __future__ import annotations

import typer
from typer.testing import CliRunner

from oneiric.cli.mcp import (
    _build_provider_factories,
    _load_auth_from_settings,
    mcp_app,
)


def test_mcp_app_is_typer_with_four_subcommands() -> None:
    """``mcp_app`` exposes start/stop/status/health (REQ-007)."""
    assert isinstance(mcp_app, typer.Typer)
    # Typer stores registered commands in ``registered_commands``.
    names = {cmd.name for cmd in mcp_app.registered_commands}
    assert names == {"start", "stop", "status", "health"}


def test_mcp_app_help_output_lists_subcommands() -> None:
    """``oneiric mcp --help`` lists all four subcommands."""
    runner = CliRunner()
    result = runner.invoke(mcp_app, ["--help"])
    assert result.exit_code == 0
    output = result.output
    for subcommand in ("start", "stop", "status", "health"):
        assert subcommand in output, f"missing '{subcommand}' in --help output"


def test_build_provider_factories_returns_empty_dict() -> None:
    """Default extension point returns ``{}``; production wires providers."""
    assert _build_provider_factories() == {}


def test_load_auth_from_settings_returns_config_when_file_missing() -> None:
    """Missing settings file -> defaults (auth disabled, no providers)."""
    config = _load_auth_from_settings(settings_path=None)  # type: ignore[arg-type]
    # ``settings_path=None`` resolves via env/default to a path that
    # usually doesn't exist in CI; load_yaml_auth_section returns ``{}``
    # so we get a disabled, empty config (REQ-006 trusted-network default).
    assert config.enabled is False
    assert config.default_provider is None
    assert config.provider_configs == {}


__all__ = [
    "_build_provider_factories",
    "_load_auth_from_settings",
    "mcp_app",
]
