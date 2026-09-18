"""Tests for the ``oneiric mcp`` CLI subcommand (REQ-007).

Verifies the Typer app shape (``mcp_app`` is registered with the four
expected subcommands) and the help output is human-readable. The actual
lifecycle helpers (``_resolve_pid_file``, ``_is_pid_alive``, etc.) are
exercised in tests/cli/test_http_cli.py — those modules share the same
template so we don't duplicate the same shapes here.
"""

from __future__ import annotations

import socket

import pytest
import typer
from typer.testing import CliRunner

from oneiric.cli.mcp import (
    _build_provider_factories,
    _enforce_public_network_auth_safety,
    _is_loopback_host,
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


class TestIsLoopbackHost:
    """``_is_loopback_host`` correctly classifies loopback vs public bindings.

    Spec §8 Q3: the FastMCP transport defaults to loopback, so the only way
    the public-network-auth gap opens is via an explicit non-loopback bind.
    The classifier must reject wildcard addresses (``0.0.0.0``, ``::``) and
    all non-127/8 IPv4 + non-::1 IPv6 forms.
    """

    def test_ipv4_loopback(self) -> None:
        assert _is_loopback_host("127.0.0.1") is True
        assert _is_loopback_host("127.0.0.2") is True  # 127.0.0.0/8 is all-loopback

    def test_ipv4_unspecified_is_not_loopback(self) -> None:
        # 0.0.0.0 binds all interfaces — must NOT be treated as loopback.
        assert _is_loopback_host("0.0.0.0") is False

    def test_ipv4_public_is_not_loopback(self) -> None:
        assert _is_loopback_host("8.8.8.8") is False
        assert _is_loopback_host("192.168.1.1") is False
        assert _is_loopback_host("10.0.0.1") is False

    def test_ipv6_loopback(self) -> None:
        assert _is_loopback_host("::1") is True

    def test_ipv6_unspecified_is_not_loopback(self) -> None:
        assert _is_loopback_host("::") is False

    def test_localhost_symbolic(self) -> None:
        # ``localhost`` must resolve to a loopback address on the test host.
        # If the test machine has ``localhost`` configured to a non-loopback
        # IP (a misconfigured /etc/hosts), skip rather than fail spuriously.
        try:
            infos = socket.getaddrinfo("localhost", None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            pytest.skip("localhost is not resolvable on this test machine")
        resolved_addrs = {info[4][0] for info in infos if info[4]}
        result = _is_loopback_host("localhost")
        # The classifier is conservative: every resolved address must be loopback.
        # This means ``localhost`` only classifies as loopback if all its
        # addresses (including any dual-stack fallbacks) are loopback.
        for addr in resolved_addrs:
            ip = addr.split("%")[0]  # drop IPv6 zone
            assert addr.startswith("127.") or ip == "::1"
        assert result is True

    def test_unresolvable_host_returns_false(self) -> None:
        # Defensive: an unresolvable hostname is not safe to assume is loopback.
        assert _is_loopback_host("definitely-not-a-real-host.invalid") is False


class TestEnforcePublicNetworkAuthSafety:
    """Guard raises on non-loopback bind WITHOUT auth (per spec §8 Q3).

    Four-cell matrix; the only illegal cell is (non-loopback, auth=False).
    """

    def test_loopback_with_auth_disabled_passes(self) -> None:
        # 127.0.0.1 + no auth = safe (trusted-network default).
        _enforce_public_network_auth_safety(host="127.0.0.1", auth_enabled=False)

    def test_loopback_with_auth_enabled_passes(self) -> None:
        _enforce_public_network_auth_safety(host="127.0.0.1", auth_enabled=True)

    def test_non_loopback_with_auth_enabled_passes(self) -> None:
        # 0.0.0.0 + auth=true = public bind with guard.
        _enforce_public_network_auth_safety(host="0.0.0.0", auth_enabled=True)

    def test_non_loopback_with_auth_disabled_raises(self) -> None:
        # 0.0.0.0 + auth=false = the loophole; guard refuses.
        with pytest.raises(typer.BadParameter) as exc_info:
            _enforce_public_network_auth_safety(host="0.0.0.0", auth_enabled=False)
        # BadParameter exposes ``param_hint`` so the operator sees the flag
        # in the usage-shaped error message.
        assert exc_info.value.param_hint == "--host"
        assert "non-loopback" in str(exc_info.value)

    def test_public_ipv4_with_auth_disabled_raises(self) -> None:
        with pytest.raises(typer.BadParameter):
            _enforce_public_network_auth_safety(host="192.168.1.1", auth_enabled=False)


__all__ = [
    "_build_provider_factories",
    "_enforce_public_network_auth_safety",
    "_is_loopback_host",
    "_load_auth_from_settings",
    "mcp_app",
]
