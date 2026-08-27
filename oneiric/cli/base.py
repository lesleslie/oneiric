"""BodaiCLIBase — shared Typer base for all Bodai Core 7 component CLIs.

Each Core 7 repo subclasses ``BodaiCLIBase(component_name="...")`` to get:

- ``version`` / ``doctor`` / ``health`` global commands
- ``--json`` global flag
- ``--version`` / ``-V`` Typer options (single-callback wiring per round-1 F-α fix)
- ``ExitCode`` enum (``SUCCESS=0``, ``ERROR=1``, ``USAGE_ERROR=2``,
  ``UNAVAILABLE=3``, ``PERMISSION_DENIED=4``, ``TIMEOUT=124``)

Subclasses override ``_doctor_checks()`` and ``_health_probe()`` to return
their repo-specific checks. Both raise ``NotImplementedError`` by default;
per-repo CI tests must assert the hooks return real data, not ``{}``.

The ``_pre_callback(ctx)`` subclass hook (default no-op) lets akosha/oneiric
preserve their preserved callbacks without re-declaring ``@app.callback``.

Round-1 cascade-fix notes:

- Unified callback via ``@self.callback(invoke_without_command=True)`` wires
  ``--json`` (sets ``ctx.obj["json_output"]``) and ``--version``/``-V``
  Typer options. No ``_intercept_version_flag()`` sys.argv mutation.
- ``_detect_version()`` catches ``PackageNotFoundError`` only (round-2 F-β
  fix); other exceptions propagate so we don't hide real errors.
- ``doctor``/``health`` split: ``NotImplementedError`` → ``ExitCode.UNAVAILABLE``
  vs ``Exception`` → ``ExitCode.ERROR`` (round-2 F-γ fix), with
  ``logger.exception`` per project CLAUDE.md.
- ``_resolve_json_output(ctx)`` helper (round-2 F-δ fix) replaces the
  duplicated ``(ctx.obj or {}).get("json_output", False)`` pattern.
"""
from __future__ import annotations

import json
import logging
import warnings
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as metadata_version
from typing import Any

import typer

logger = logging.getLogger(__name__)


class ExitCode:
    """Standardized exit codes across all Bodai CLIs."""

    SUCCESS = 0
    ERROR = 1
    USAGE_ERROR = 2
    UNAVAILABLE = 3
    PERMISSION_DENIED = 4
    TIMEOUT = 124


class BodaiCLIBase(typer.Typer):
    """Base Typer app for all Bodai component CLIs."""

    def __init__(
        self,
        component_name: str,
        *,
        help: str | None = None,
        no_args_is_help: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(help=help, no_args_is_help=no_args_is_help, **kwargs)
        self.component_name = component_name
        self.component_version = self._detect_version()
        self._register_global_callback()
        self._register_global_commands()

    # ------------------------------------------------------------------
    # Version detection
    # ------------------------------------------------------------------
    def _detect_version(self) -> str:
        """Return the installed version of ``self.component_name``.

        Catches ``PackageNotFoundError`` (the only expected failure mode when
        a component is run from a source tree without being installed). All
        other exceptions propagate so we don't hide real errors.
        """
        try:
            return metadata_version(self.component_name)
        except PackageNotFoundError:
            return "(not installed)"

    # ------------------------------------------------------------------
    # Subclass extension hook
    # ------------------------------------------------------------------
    def _pre_callback(self, ctx: typer.Context) -> None:
        """Hook for subclasses to extend the unified callback.

        Default no-op. ``akosha`` and ``oneiric`` use this to preserve their
        own callback side-effects (config init, logging setup) without
        re-declaring ``@app.callback``.
        """

    # ------------------------------------------------------------------
    # Unified callback registration (round-1 F-α fix)
    # ------------------------------------------------------------------
    def _register_global_callback(self) -> None:
        """Register one unified callback wiring ``--json`` and ``--version``.

        A single callback (with ``invoke_without_command=True``) replaces the
        original split: ``_intercept_version_flag()`` sys.argv mutation +
        per-command ``ctx.obj`` reads. The Typer ``--version``/``-V`` options
        emit a ``DeprecationWarning`` (one release) and print the version.
        """

        @self.callback(invoke_without_command=True)
        def _root_callback(
            ctx: typer.Context,
            json_output: bool = typer.Option(
                False,
                "--json",
                help="Emit machine-readable JSON instead of human-readable text.",
            ),
            version_flag: bool = typer.Option(
                False,
                "--version",
                "-V",
                help="[DEPRECATED] Use '<component> version' instead.",
                is_flag=True,
            ),
        ) -> None:
            ctx.ensure_object(dict)
            ctx.obj["json_output"] = json_output

            if version_flag:
                warnings.warn(
                    f"--version is deprecated; use '{self.component_name} version'. "
                    "The flag will be removed in the next minor.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                typer.echo(f"{self.component_name}: {self.component_version}")
                raise typer.Exit(code=ExitCode.SUCCESS)

            self._pre_callback(ctx)

    # ------------------------------------------------------------------
    # JSON helper (round-2 F-δ fix)
    # ------------------------------------------------------------------
    def _resolve_json_output(self, ctx: typer.Context) -> bool:
        """Return the resolved ``--json`` flag from ``ctx.obj``."""
        if ctx.obj is None:
            return False
        return bool(ctx.obj.get("json_output", False))

    # ------------------------------------------------------------------
    # Global commands
    # ------------------------------------------------------------------
    def _register_global_commands(self) -> None:
        @self.command()
        def version() -> None:
            """Print this component's version."""
            typer.echo(f"{self.component_name}: {self.component_version}")
            raise typer.Exit(code=ExitCode.SUCCESS)

        @self.command()
        def doctor(ctx: typer.Context) -> None:
            """Run diagnostic checks against this component's runtime."""
            json_output = self._resolve_json_output(ctx)
            try:
                checks = self._doctor_checks()
            except NotImplementedError:
                typer.echo(
                    f"{self.component_name}: doctor checks not yet implemented"
                )
                raise typer.Exit(code=ExitCode.UNAVAILABLE) from None
            except Exception as exc:  # pragma: no cover - subclass hook
                logger.exception("doctor-failed", component=self.component_name)
                typer.echo(f"{self.component_name}: doctor failed: {exc}")
                raise typer.Exit(code=ExitCode.ERROR) from None

            if json_output:
                typer.echo(json.dumps({"checks": checks}, indent=2, default=str))
                return
            for name, info in checks.items():
                status = info.get("status", "unknown") if isinstance(info, dict) else "unknown"
                detail = info.get("detail", "") if isinstance(info, dict) else str(info)
                typer.echo(f"{name}: {status} - {detail}")

        @self.command()
        def health(ctx: typer.Context) -> None:
            """Probe this component's runtime health."""
            json_output = self._resolve_json_output(ctx)
            try:
                snapshot = self._health_probe()
            except NotImplementedError:
                typer.echo(
                    f"{self.component_name}: health checks not yet implemented"
                )
                raise typer.Exit(code=ExitCode.UNAVAILABLE) from None
            except Exception as exc:  # pragma: no cover - subclass hook
                logger.exception("health-failed", component=self.component_name)
                typer.echo(f"{self.component_name}: health failed: {exc}")
                raise typer.Exit(code=ExitCode.ERROR) from None

            if json_output:
                typer.echo(json.dumps(snapshot, indent=2, default=str))
                return
            typer.echo(str(snapshot))

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------
    def _doctor_checks(self) -> dict[str, Any]:
        """Override in subclass. Return dict of check_name -> {status, detail}."""
        raise NotImplementedError

    def _health_probe(self) -> dict[str, Any]:
        """Override in subclass. Return dict matching oneiric health schema."""
        raise NotImplementedError