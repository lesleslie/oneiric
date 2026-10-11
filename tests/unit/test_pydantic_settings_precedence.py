"""Phase 0 safety-net tests for oneiric.core.config.load_settings() precedence.

These tests pin the CURRENT (pre-pydantic-settings-migration) hand-rolled
loader's behavior so that the Phase 1 pydantic-settings migration can use
them as acceptance criteria. Each test exercises a single precedence rule
using ``tmp_path`` for ephemeral YAML layers and ``monkeypatch`` for env-var
isolation — no real ``settings/`` directory and no global ``os.environ``
pollution.

NOTE on round-trip mechanics: ``OneiricSettings()`` instantiated DIRECTLY
does NOT apply env vars to nested sections — only ``load_settings()`` does
(because the nested section models like ``AppConfig`` / ``LoggingConfig``
are plain ``BaseModel`` s, not ``BaseSettings``). Every env-var round-trip
test below therefore goes through ``load_settings()``, never through
``OneiricSettings()``.

Layer numbering convention (from the loader's applied-order; numbering goes
from L3 = lowest YAML layer under test up to L5 = highest YAML layer under
test; env vars are applied AFTER L5; explicit path env + path arg are the
final two overrides):

- L3 = project-local YAML (``<project_root>/settings/local.yaml``)
- L4 = XDG config YAML (``<XDG_CONFIG_HOME>/<project_name>/config.yaml``)
- L5 = XDG local YAML (``<XDG_CONFIG_HOME>/<project_name>/local.yaml``)
- env = ONEIRIC_* environment variables (override all YAML layers)
- PROJECT_CONFIG = ``{PROJECT_NAME}_CONFIG`` env var pointing at a YAML file
- path = explicit ``path=`` argument to ``load_settings()``

Each test prints the env-var forms that would also target the field on
assertion failure so a developer can debug with one screenshot.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from oneiric.core.config import OneiricSettings, load_settings

EXPECTED_PRIMARY_ENV: dict[str, tuple[str, ...]] = {
    "logging.level": ("ONEIRIC_LOGGING__LEVEL", "ONEIRIC_LOG_LEVEL"),
    "runtime_paths.domain_activity_path": (
        "ONEIRIC_RUNTIME_PATHS__DOMAIN_ACTIVITY_PATH",
        "ONEIRIC_ACTIVITY_STORE",
    ),
}


def _strip_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every ONEIRIC_* env var plus XDG_CONFIG_HOME so tests start clean."""
    for key in [k for k in os.environ if k.startswith("ONEIRIC_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


def _xdg_root(tmp_path: Path) -> Path:
    """Return the XDG config root for ``project_name='oneiric'``."""
    return tmp_path / "xdg" / "oneiric"


def _write_xdg_local(
    xdg_local: Path, *, app_name: str | None = None, level: str | None = None
) -> None:
    """Write ``<xdg>/local.yaml`` with selective keys."""
    xdg_local.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if app_name is not None:
        payload.setdefault("app", {})["name"] = app_name
    if level is not None:
        payload.setdefault("logging", {})["level"] = level
    _dump_yaml(xdg_local, payload)


def _write_xdg_config(xdg_config: Path, *, app_name: str) -> None:
    xdg_config.parent.mkdir(parents=True, exist_ok=True)
    _dump_yaml(xdg_config, {"app": {"name": app_name}})


def _write_project_local(
    project_root: Path, *, app_name: str | None = None, level: str | None = None
) -> None:
    settings_dir = project_root / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if app_name is not None:
        payload.setdefault("app", {})["name"] = app_name
    if level is not None:
        payload.setdefault("logging", {})["level"] = level
    _dump_yaml(settings_dir / "local.yaml", payload)


def _dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    """Tiny YAML dumper so this file has no third-party imports."""
    path.write_text(_render_yaml(payload))


def _render_yaml(payload: dict[str, Any], indent: int = 0) -> str:
    """Render a 1-deep dict into YAML (sufficient for these tests)."""
    lines: list[str] = []
    pad = "  " * indent
    for key, value in payload.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_render_yaml(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{pad}{key}:")
            for item in value:
                lines.append(f"{pad}  - {item!r}")
        else:
            lines.append(f"{pad}{key}: {_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _hint_collision(field_path: str) -> str:
    """Build a debug hint showing the env-var forms for the failing field."""
    primary = EXPECTED_PRIMARY_ENV.get(field_path)
    if primary:
        return (
            f"Field {field_path!r} is reachable via: "
            + ", ".join(primary)
            + " (see _ALIAS_OVERRIDES + AliasChoices for collisions)"
        )
    section, _, field = field_path.rpartition(".")
    env_var = f"ONEIRIC_{section.upper()}__{field.upper()}"
    return f"Field {field_path!r} is reachable via env var {env_var!r}"


# ---------------------------------------------------------------------------
# 1. env overrides XDG-local
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_env_overrides_yaml_layer_5_xdg_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env var (``ONEIRIC_APP__ENVIRONMENT``) must override XDG-local value."""
    _strip_oneiric_env(monkeypatch)
    xdg_root = _xdg_root(tmp_path)
    _write_xdg_local(xdg_root / "local.yaml", level=None)
    _dump_yaml(xdg_root / "local.yaml", {"app": {"environment": "from_xdg_local"}})

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("ONEIRIC_APP__ENVIRONMENT", "from_env")

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.app.environment == "from_env", (
            "env (ONEIRIC_APP__ENVIRONMENT) failed to override XDG-local value. "
            + _hint_collision("app.environment")
        )
    finally:
        # Echo on failure for the developer.
        if s.app.environment != "from_env":
            print(_hint_collision("app.environment"))


# ---------------------------------------------------------------------------
# 2. env overrides project-local
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_env_overrides_yaml_layer_3_project_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env var must override project-local YAML value."""
    _strip_oneiric_env(monkeypatch)
    _write_project_local(tmp_path, app_name=None, level=None)
    _dump_yaml(
        tmp_path / "settings" / "local.yaml",
        {"app": {"environment": "from_project_local"}},
    )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))  # empty XDG
    monkeypatch.setenv("ONEIRIC_APP__ENVIRONMENT", "from_env")

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.app.environment == "from_env", (
            "env (ONEIRIC_APP__ENVIRONMENT) failed to override project-local YAML. "
            + _hint_collision("app.environment")
        )
    finally:
        if s.app.environment != "from_env":
            print(_hint_collision("app.environment"))


# ---------------------------------------------------------------------------
# 3. XDG-local > XDG-config (yaml layer 5 overrides layer 4)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_yaml_layer_5_xdg_local_overrides_layer_4_xdg_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """XDG-local.yaml must win over XDG-config.yaml for the same key."""
    _strip_oneiric_env(monkeypatch)
    xdg_root = _xdg_root(tmp_path)
    _write_xdg_config(xdg_root / "config.yaml", app_name="from_xdg_config")
    _write_xdg_local(xdg_root / "local.yaml", app_name="from_xdg_local")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.app.name == "from_xdg_local", (
            "XDG-local.yaml should override XDG-config.yaml per the "
            "loader's applied layer ordering. "
            + _hint_collision("app.name")
        )
    finally:
        if s.app.name != "from_xdg_local":
            print(_hint_collision("app.name"))


# ---------------------------------------------------------------------------
# 4. XDG-config > project-local (yaml layer 4 overrides layer 3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_yaml_layer_4_xdg_config_overrides_layer_3_project_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """XDG-config.yaml must win over project-local.yaml for the same key."""
    _strip_oneiric_env(monkeypatch)
    _write_project_local(tmp_path, app_name="from_project_local")
    xdg_root = _xdg_root(tmp_path)
    _write_xdg_config(xdg_root / "config.yaml", app_name="from_xdg_config")
    # intentionally do NOT write XDG-local

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.app.name == "from_xdg_config", (
            "XDG-config.yaml should win over project-local.yaml. "
            + _hint_collision("app.name")
        )
    finally:
        if s.app.name != "from_xdg_config":
            print(_hint_collision("app.name"))


# ---------------------------------------------------------------------------
# 5. defaults (init kwargs) when no source supplies a value
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_init_kwargs_default_when_no_source_supplies_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no YAML and no env vars, field defaults must populate."""
    _strip_oneiric_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.app.name == "oneiric", (
            "default value `oneiric` for app.name not used when no YAML or "
            "env var supplies a value"
        )
        assert s.app.environment == "dev", (
            "default value `dev` for app.environment not used when no YAML "
            "or env var supplies a value"
        )
        assert s.remote.enabled is False, (
            "default value `False` for remote.enabled not used when no "
            "YAML or env var supplies a value"
        )
    finally:
        if s.app.name != "oneiric":
            print(_hint_collision("app.name"))


# ---------------------------------------------------------------------------
# 6. alias ONEIRIC_ACTIVITY_STORE -> runtime_paths.domain_activity_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_alias_overrides_activity_store_routes_to_domain_activity_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting the ONEIRIC_ACTIVITY_STORE alias must populate
    ``runtime_paths.domain_activity_path`` (via _ALIAS_OVERRIDES + AliasChoices)."""
    _strip_oneiric_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("ONEIRIC_ACTIVITY_STORE", "/tmp/custom-activity.sqlite")

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.runtime_paths.domain_activity_path == "/tmp/custom-activity.sqlite", (
            "ONEIRIC_ACTIVITY_STORE alias did not route to "
            "runtime_paths.domain_activity_path. "
            + _hint_collision("runtime_paths.domain_activity_path")
        )
    finally:
        if s.runtime_paths.domain_activity_path != "/tmp/custom-activity.sqlite":
            print(_hint_collision("runtime_paths.domain_activity_path"))


# ---------------------------------------------------------------------------
# 7. alias ONEIRIC_LOG_LEVEL -> logging.level
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_alias_overrides_log_level_routes_to_logging_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting the ONEIRIC_LOG_LEVEL alias must populate ``logging.level``
    (via _ALIAS_OVERRIDES + AliasChoices)."""
    _strip_oneiric_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("ONEIRIC_LOG_LEVEL", "WARNING")

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.logging.level == "WARNING", (
            "ONEIRIC_LOG_LEVEL alias did not route to logging.level. "
            + _hint_collision("logging.level")
        )
    finally:
        if s.logging.level != "WARNING":
            print(_hint_collision("logging.level"))


# ---------------------------------------------------------------------------
# 8. explicit path argument wins over all YAML layers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_explicit_path_argument_overrides_yaml_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``path=`` arg must override every YAML layer (incl. xdg-local)."""
    _strip_oneiric_env(monkeypatch)
    xdg_root = _xdg_root(tmp_path)
    _write_xdg_local(xdg_root / "local.yaml", app_name="from_xdg_local")
    _write_project_local(tmp_path, app_name="from_project_local")

    explicit_yaml = tmp_path / "explicit.yaml"
    _dump_yaml(explicit_yaml, {"app": {"name": "from_explicit_path"}})

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    s = load_settings(
        path=explicit_yaml,
        project_root=tmp_path,
        project_name="oneiric",
    )
    try:
        assert s.app.name == "from_explicit_path", (
            "Explicit path= argument did not win over XDG-local + project-local. "
            + _hint_collision("app.name")
        )
    finally:
        if s.app.name != "from_explicit_path":
            print(_hint_collision("app.name"))


# ---------------------------------------------------------------------------
# 9. PROJECT_CONFIG env var wins over all YAML layers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_PROJECT_CONFIG_env_overrides_yaml_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONEIRIC_CONFIG env var must win over every YAML layer (incl. xdg-local)."""
    _strip_oneiric_env(monkeypatch)
    xdg_root = _xdg_root(tmp_path)
    _write_xdg_local(xdg_root / "local.yaml", app_name="from_xdg_local")
    _write_project_local(tmp_path, app_name="from_project_local")

    explicit_yaml = tmp_path / "from_env_config.yaml"
    _dump_yaml(explicit_yaml, {"app": {"name": "from_PROJECT_CONFIG"}})

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("ONEIRIC_CONFIG", str(explicit_yaml))

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.app.name == "from_PROJECT_CONFIG", (
            "ONEIRIC_CONFIG env var did not win over XDG-local + project-local. "
            + _hint_collision("app.name")
        )
    finally:
        if s.app.name != "from_PROJECT_CONFIG":
            print(_hint_collision("app.name"))


# ---------------------------------------------------------------------------
# 10. missing YAML files in every layer must not raise
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_yaml_source_with_missing_file_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointing load_settings at a fully-empty project_root + empty XDG must
    resolve to all defaults without raising FileNotFoundError."""
    _strip_oneiric_env(monkeypatch)
    # create empty project_root and empty XDG dirs; nothing else
    (tmp_path / "settings").mkdir(exist_ok=True)
    empty_xdg = tmp_path / "xdg" / "oneiric"
    empty_xdg.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    s = load_settings(project_root=tmp_path, project_name="oneiric")
    try:
        assert s.app.name == "oneiric", (
            "Defaults not preserved when no YAML sources exist. "
            + _hint_collision("app.name")
        )
        assert s.remote.enabled is False
    finally:
        if s.app.name != "oneiric":
            print(_hint_collision("app.name"))


# Reference import kept for type-check visibility; helpers below are public
# so the audit test file can import them without duplication.
__all__ = [
    "EXPECTED_PRIMARY_ENV",
    "_strip_oneiric_env",
]
