"""Shared metadata helpers for resolver-managed domains."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from oneiric.core.resolution import Resolver

FactoryType = Callable[..., Any] | str


def settings_model_path(settings_model: str | type[BaseModel] | None) -> str | None:
    if isinstance(settings_model, str):
        return settings_model
    if settings_model:
        return f"{settings_model.__module__}.{settings_model.__name__}"
    return None


def build_metadata(
    base: dict[str, Any], extras: dict[str, Any] | None
) -> dict[str, Any]:
    metadata = base | (extras or {})
    return {
        key: value for key, value in metadata.items() if value not in (None, [], {})
    }


def register_metadata(
    resolver: Resolver,
    package_name: str,
    package_path: str,
    items: Sequence[Any],
    *,
    priority: int | None = None,
    logger: Any,
    log_key: str,
) -> None:
    candidates = [metadata.to_candidate() for metadata in items]
    resolver.register_from_pkg(
        package_name, package_path, candidates, priority=priority
    )
    logger.info(log_key, package=package_name, count=len(candidates))
