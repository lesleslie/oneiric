"""Per-project OneiricSettings subclass factory.

``build_oneiric_settings(project_name, project_root=...)`` returns a
memoized ``_Project(OneiricSettings)`` subclass with ``env_prefix`` set to
``f"{project_name.upper()}_"``. Each project (oneiric, mahavishnu,
akosha, crackerjack, session-buddy, mcp-common) calls this factory to
get its own subclass; the subclass is built once per ``(project_name,
project_root)`` tuple and reused for every subsequent
``load_settings(project_name=..., project_root=...)`` call.

The factory pattern lets pydantic-settings' ``BaseSettings`` machinery
handle the per-project env-var prefix without leaking global state.
``load_settings()`` instantiates the factory output, applies the explicit
``path=`` override via post-construction ``model_validate(merged_dict)``,
and returns the validated instance.

The ``project_root`` parameter lets test code anchor the YAML layers
under an ephemeral directory (``tmp_path``) without touching the
package's installed ``settings/`` tree. Memoization keys on the tuple
so the same (name, root) pair returns the same class object; different
roots produce distinct subclasses.

The project_root is exposed to the subclass body as the
``_oneiric_project_root`` class attribute (pathlib.Path) so the
``settings_customise_sources`` classmethod can compute the YAML layer
paths without relying on ``Path(__file__)`` resolution (which always
returns the package install location, never the caller's anchor).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic_settings import SettingsConfigDict

from .config import OneiricSettings

_PROJECT_SETTINGS: dict[tuple[str, str], type[OneiricSettings]] = {}


def build_oneiric_settings(
    project_name: str,
    project_root: Path | str | None = None,
) -> type[OneiricSettings]:
    """Return the memoized per-project ``OneiricSettings`` subclass.

    Args:
        project_name: Project identifier (e.g., "oneiric", "mahavishnu").
            Used to compute the env_prefix (``f"{project_name.upper()}_"``).
        project_root: Where YAML layers resolve under. When ``None``,
            defaults to the package install location
            (``Path(__file__).resolve().parent.parent.parent`` of the
            ``oneiric.core.config`` module). Pass explicitly when
            anchoring at a checkout or ``tmp_path``.

    Returns:
        A subclass of ``OneiricSettings`` with env_prefix bound to the
        project. Instantiable directly (``_Project()``) or via
        ``load_settings()``.
    """
    package_root = Path(__file__).resolve().parent.parent.parent
    root_path = Path(project_root).resolve() if project_root else package_root
    cache_key = (project_name, str(root_path))
    cached = _PROJECT_SETTINGS.get(cache_key)
    if cached is not None:
        return cached

    class _Project(OneiricSettings):
        # ``ClassVar`` keeps Pydantic from treating these as model fields
        # (and from emitting ``ModelPrivateAttr`` descriptors when the
        # name starts with an underscore). The leading ``oneiric_`` prefix
        # avoids accidental collisions with pydantic-settings' own
        # attributes.
        oneiric_project_root: ClassVar[Path] = root_path
        oneiric_project_name: ClassVar[str] = project_name

        model_config = SettingsConfigDict(
            env_prefix=f"{project_name.upper()}_",
            env_nested_delimiter="__",
            extra="allow",
            populate_by_name=True,
            arbitrary_types_allowed=True,
        )

    _Project.__name__ = f"OneiricSettings[{project_name}]"
    _Project.__qualname__ = f"OneiricSettings[{project_name}]"
    _PROJECT_SETTINGS[cache_key] = _Project
    return _Project


def clear_project_settings_cache() -> None:
    """Reset the memoization cache. Test-only escape hatch."""
    _PROJECT_SETTINGS.clear()


__all__ = ["build_oneiric_settings", "clear_project_settings_cache"]