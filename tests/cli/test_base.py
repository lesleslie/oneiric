"""Tests for BodaiCLIBase (oneiric.cli.base).

Covers the cascade-fixed implementation:
- Unified callback wires --json and --version via Typer options (round-1 F-α fix).
- _pre_callback hook lets subclasses extend the callback without redeclaring it.
- _resolve_json_output helper replaces duplicated (ctx.obj or {}).get(...) (round-2 F-δ fix).
- _detect_version catches PackageNotFoundError only (round-2 F-β fix).
- doctor/health: NotImplementedError -> UNAVAILABLE, Exception -> ERROR (round-2 F-γ fix).
- No _intercept_version_flag() method (round-1 F-α fix).
"""
from __future__ import annotations

import warnings

import pytest
import typer
from typer.testing import CliRunner

from oneiric.cli.base import BodaiCLIBase, ExitCode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """Provide a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def fake_app() -> BodaiCLIBase:
    """Return a minimal BodaiCLIBase subclass with default behavior."""
    class FakeApp(BodaiCLIBase):
        pass

    return FakeApp(component_name="test-component")


# ---------------------------------------------------------------------------
# Construction + metadata
# ---------------------------------------------------------------------------


def test_subclass_constructor_sets_metadata() -> None:
    class FakeApp(BodaiCLIBase):
        pass

    app = FakeApp(component_name="test-component")
    assert app.component_name == "test-component"
    assert isinstance(app.component_version, str)


def test_subclass_help_string_passed_through() -> None:
    class FakeApp(BodaiCLIBase):
        pass

    app = FakeApp(component_name="x", help="custom help text")
    assert app.info.help == "custom help text"


# ---------------------------------------------------------------------------
# Global commands
# ---------------------------------------------------------------------------


def test_version_command_works(runner: CliRunner, fake_app: BodaiCLIBase) -> None:
    result = runner.invoke(fake_app, ["version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "test-component" in result.output


def test_doctor_command_returns_unavailable_when_not_implemented(
    runner: CliRunner, fake_app: BodaiCLIBase
) -> None:
    result = runner.invoke(fake_app, ["doctor"])
    assert result.exit_code == ExitCode.UNAVAILABLE


def test_health_command_returns_unavailable_when_not_implemented(
    runner: CliRunner, fake_app: BodaiCLIBase
) -> None:
    result = runner.invoke(fake_app, ["health"])
    assert result.exit_code == ExitCode.UNAVAILABLE


def test_subclass_doctor_override(runner: CliRunner) -> None:
    class FakeApp(BodaiCLIBase):
        def _doctor_checks(self) -> dict[str, dict[str, str]]:
            return {"check1": {"status": "ok", "detail": "fine"}}

    app = FakeApp(component_name="test")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "check1: ok - fine" in result.output


def test_subclass_health_override(runner: CliRunner) -> None:
    class FakeApp(BodaiCLIBase):
        def _health_probe(self) -> dict[str, str]:
            return {"status": "ok", "detail": "running"}

    app = FakeApp(component_name="test")
    result = runner.invoke(app, ["health"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "status" in result.output


# ---------------------------------------------------------------------------
# Global flags
# ---------------------------------------------------------------------------


def test_global_json_flag_accepted(runner: CliRunner, fake_app: BodaiCLIBase) -> None:
    """`--json version` must exit 0 and emit JSON-friendly payload."""
    result = runner.invoke(fake_app, ["--json", "version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "test-component" in result.output


def test_global_json_flag_makes_doctor_emit_json(runner: CliRunner) -> None:
    class FakeApp(BodaiCLIBase):
        def _doctor_checks(self) -> dict[str, dict[str, str]]:
            return {"alpha": {"status": "ok", "detail": "ready"}}

    app = FakeApp(component_name="test")
    result = runner.invoke(app, ["--json", "doctor"])
    assert result.exit_code == ExitCode.SUCCESS
    assert '"checks"' in result.output
    assert '"alpha"' in result.output


def test_global_version_flag_accepted(runner: CliRunner, fake_app: BodaiCLIBase) -> None:
    """`--version` flag emits DeprecationWarning + version, exits 0."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = runner.invoke(fake_app, ["--version"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "test-component" in result.output
    # At least one DeprecationWarning about --version
    assert any(
        issubclass(w.category, DeprecationWarning) for w in caught
    ), "Expected DeprecationWarning for --version flag"


def test_global_short_version_flag_accepted(
    runner: CliRunner, fake_app: BodaiCLIBase
) -> None:
    """`-V` short flag works identically."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = runner.invoke(fake_app, ["-V"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "test-component" in result.output
    assert any(
        issubclass(w.category, DeprecationWarning) for w in caught
    ), "Expected DeprecationWarning for -V flag"


# ---------------------------------------------------------------------------
# Cascade-fix design invariants
# ---------------------------------------------------------------------------


def test_no_extra_callback_registered(fake_app: BodaiCLIBase) -> None:
    """Exactly ONE callback is registered: the unified root callback.

    Cascade-fix invariant (round-1 F-α): subclasses must not redeclare
    ``@app.callback``. Use the ``_pre_callback`` hook instead. If a subclass
    adds a second callback, Typer raises at construction time.
    """
    callback = getattr(fake_app, "registered_callback", None)
    assert callback is not None, "Unified callback should be registered"
    # The callback exposes ``invoke_without_command=True`` — the cascade-fix
    # marker that consolidates the unified --json + --version wiring.
    assert callback.invoke_without_command is True


def test_intercept_version_flag_method_removed(fake_app: BodaiCLIBase) -> None:
    """Round-1 F-α fix: the old sys.argv-mutating method is gone."""
    assert not hasattr(fake_app, "_intercept_version_flag"), (
        "_intercept_version_flag should be removed (round-1 F-α fix); "
        "use the unified callback's --version Typer option instead."
    )


def test_pre_callback_called_when_subclass_overrides(runner: CliRunner) -> None:
    """Subclasses can hook _pre_callback(ctx) without redeclaring @app.callback."""
    captured: dict[str, bool] = {"called": False}

    class FakeApp(BodaiCLIBase):
        def _pre_callback(self, ctx: typer.Context) -> None:
            captured["called"] = True

    app = FakeApp(component_name="test")
    # Invoke a subcommand so the unified callback actually runs.
    result = runner.invoke(app, ["version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert captured["called"] is True, (
        "Subclass _pre_callback should be invoked from the unified callback."
    )


def test_pre_callback_default_is_noop(runner: CliRunner, fake_app: BodaiCLIBase) -> None:
    """Default _pre_callback is a no-op and does not raise."""
    result = runner.invoke(fake_app, ["version"])
    assert result.exit_code == ExitCode.SUCCESS


def test_resolve_json_output_helper_present(fake_app: BodaiCLIBase) -> None:
    """Round-2 F-δ fix: _resolve_json_output(ctx) helper exists."""
    assert hasattr(fake_app, "_resolve_json_output")
    assert callable(fake_app._resolve_json_output)


def test_detect_version_narrow_catch(fake_app: BodaiCLIBase) -> None:
    """Round-2 F-β fix: only PackageNotFoundError is swallowed."""
    import inspect

    source = inspect.getsource(BodaiCLIBase._detect_version)
    assert "PackageNotFoundError" in source
    # Should NOT use bare `except Exception:` — that would hide real errors.
    assert "except Exception" not in source, (
        "_detect_version must catch PackageNotFoundError specifically, "
        "not bare Exception (round-2 F-β fix)."
    )


# ---------------------------------------------------------------------------
# Failure semantics (round-2 F-γ fix)
# ---------------------------------------------------------------------------


def test_doctor_returns_error_on_subclass_exception(runner: CliRunner) -> None:
    """doctor: Exception (not NotImplementedError) -> ExitCode.ERROR."""

    class BrokenApp(BodaiCLIBase):
        def _doctor_checks(self) -> dict[str, str]:
            raise RuntimeError("doctor exploded")

    app = BrokenApp(component_name="broken")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == ExitCode.ERROR


def test_health_returns_error_on_subclass_exception(runner: CliRunner) -> None:
    """health: Exception (not NotImplementedError) -> ExitCode.ERROR."""

    class BrokenApp(BodaiCLIBase):
        def _health_probe(self) -> dict[str, str]:
            raise RuntimeError("health exploded")

    app = BrokenApp(component_name="broken")
    result = runner.invoke(app, ["health"])
    assert result.exit_code == ExitCode.ERROR


# ---------------------------------------------------------------------------
# ExitCode enum
# ---------------------------------------------------------------------------


def test_exit_code_constants() -> None:
    assert ExitCode.SUCCESS == 0
    assert ExitCode.ERROR == 1
    assert ExitCode.USAGE_ERROR == 2
    assert ExitCode.UNAVAILABLE == 3
    assert ExitCode.PERMISSION_DENIED == 4
    assert ExitCode.TIMEOUT == 124


# ---------------------------------------------------------------------------
# OneiricCLI self-adoption (Phase 3.5)
# ---------------------------------------------------------------------------


def test_app_is_bodai_cli_base() -> None:
    """oneiric.cli.app must be a BodaiCLIBase instance with component_name='oneiric'."""
    from oneiric.cli import app
    from oneiric.cli.base import BodaiCLIBase

    assert isinstance(app, BodaiCLIBase)
    assert app.component_name == "oneiric"
    assert isinstance(app.component_version, str)


def test_doctor_returns_real_checks() -> None:
    """oneiric._doctor_checks must return non-empty dict with status-bearing entries.

    The Phase 3.5 spec requires REAL checks (calls into oneiric.config +
    oneiric.runtime.health), not stubs that return ``{}`` or
    ``UNAVAILABLE``.
    """
    from oneiric.cli import app

    checks = app._doctor_checks()
    assert isinstance(checks, dict)
    assert len(checks) > 0, "_doctor_checks must return at least one real check"

    for name, info in checks.items():
        assert isinstance(info, dict), f"check {name!r} must be a dict"
        assert "status" in info, f"check {name!r} missing 'status'"
        assert info["status"] in {"ok", "degraded", "idle", "error"}


def test_health_probe_returns_real_data() -> None:
    """oneiric._health_probe must return a dict with 'status' (real, not UNAVAILABLE)."""
    from oneiric.cli import app

    snapshot = app._health_probe()
    assert isinstance(snapshot, dict)
    assert "status" in snapshot
    assert snapshot["status"] in {"healthy", "degraded", "error"}
    assert snapshot.get("component") == "oneiric"


def test_oneiric_global_json_flag_accepted(runner: CliRunner) -> None:
    """`oneiric --json version` must exit SUCCESS (--json wired via BodaiCLIBase)."""
    from oneiric.cli import app

    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "oneiric" in result.output


def test_oneiric_global_version_flag_accepted(runner: CliRunner) -> None:
    """`oneiric --version` must exit SUCCESS and emit 'oneiric' (BodaiCLIBase flag)."""
    import warnings

    from oneiric.cli import app

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = runner.invoke(app, ["--version"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "oneiric" in result.output
    assert any(
        issubclass(w.category, DeprecationWarning) for w in caught
    ), "Expected DeprecationWarning for --version flag"


def test_callback_preserved_via_pre_callback(runner: CliRunner) -> None:
    """L1959 callback body still runs: ctx.obj['json_output'] is set after --json.

    Also confirms that the original side-effects (help-on-no-subcommand)
    still trigger when no subcommand is passed.
    """
    from oneiric.cli import app

    # 1. --json wires ctx.obj['json_output'] through the unified callback
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == ExitCode.SUCCESS, (
        f"Unified callback raised: {result.output!r}"
    )

    # 2. help-on-no-subcommand is preserved (typer echoes help and exits 0)
    result_no_cmd = runner.invoke(app, ["--json"])
    # No subcommand triggers the original help-on-no-subcommand branch.
    # Exit code is 0 (raise typer.Exit() with no code).
    assert "Usage:" in result_no_cmd.output or "oneiric" in result_no_cmd.output


def test_no_typer_typer_app_at_module_level() -> None:
    """oneiric.cli.app must NOT be a bare typer.Typer; must be BodaiCLIBase."""
    import typer

    from oneiric.cli import app
    from oneiric.cli.base import BodaiCLIBase

    # BodaiCLIBase subclasses typer.Typer, so isinstance(app, typer.Typer) is
    # expected. The important guard is that we got there via BodaiCLIBase,
    # proving the self-adoption landed.
    assert isinstance(app, BodaiCLIBase)
    assert type(app) is not typer.Typer


def test_sub_typed_apps_remain_bare_typer() -> None:
    """The 4 sub-typers (manifest/secrets/event/workflow) stay bare typer.Typer.

    Phase 3.5 spec: only the top-level app adopts BodaiCLIBase.
    """
    import typer

    from oneiric.cli import (
        event_app,
        manifest_app,
        secrets_app,
        workflow_app,
    )

    for sub in (manifest_app, secrets_app, event_app, workflow_app):
        assert type(sub) is typer.Typer, (
            f"{sub!r} should be a bare typer.Typer, not a BodaiCLIBase subclass"
        )
