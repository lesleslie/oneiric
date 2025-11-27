"""Entry-point discovery helpers for Oneiric plugins."""

from __future__ import annotations

from collections import abc
from dataclasses import dataclass, field
from importlib import metadata
from typing import Callable, Iterable, List, Optional, Sequence

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.config import PluginsConfig
from oneiric.core.logging import get_logger
from oneiric.core.resolution import Candidate, Resolver

logger = get_logger("plugins")

DEFAULT_ENTRY_POINT_GROUPS = (
    "oneiric.adapters",
    "oneiric.services",
    "oneiric.tasks",
    "oneiric.events",
    "oneiric.workflows",
)


@dataclass
class PluginEntryRecord:
    group: str
    entry_point: str
    payload_type: str
    registered_candidates: int


@dataclass
class PluginErrorRecord:
    group: str
    entry_point: str
    reason: str


@dataclass
class PluginRegistrationReport:
    """Diagnostics describing plugin bootstrap activity."""

    groups: List[str] = field(default_factory=list)
    registered: int = 0
    entries: List[PluginEntryRecord] = field(default_factory=list)
    errors: List[PluginErrorRecord] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "PluginRegistrationReport":
        return cls()

    def as_dict(self) -> dict:
        return {
            "groups": list(self.groups),
            "registered": self.registered,
            "entries": [entry.__dict__ for entry in self.entries],
            "errors": [error.__dict__ for error in self.errors],
        }


@dataclass
class _FactoryLoadResult:
    group: str
    entry_point: str
    factory: Optional[Callable[[], object]] = None
    error: Optional[str] = None


def iter_entry_points(group: str) -> Sequence[metadata.EntryPoint]:
    """Return entry points for the supplied group (PyPI metadata helper)."""

    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return tuple(entry_points.select(group=group))
    return tuple(entry_points.get(group, []))


def load_callables(group: str) -> List[Callable[[], object]]:
    """Load callable factories exposed via an entry-point group.

    Any entry point that fails to load is logged and skipped so plugin discovery
    remains best-effort.
    """

    callables: List[Callable[[], object]] = []
    for result in _load_entry_point_factories(group):
        if result.factory:
            callables.append(result.factory)
    return callables


def discover_metadata(group: str) -> Iterable[object]:
    """Convenience wrapper that calls each plugin factory and yields metadata."""

    for factory in load_callables(group):
        try:
            yield factory()
        except Exception as exc:  # pragma: no cover - logging guard
            logger.warning(
                "plugin-metadata-failed",
                group=group,
                factory=getattr(factory, "__name__", repr(factory)),
                error=str(exc),
            )


def register_entrypoint_plugins(resolver: Resolver, config: PluginsConfig) -> PluginRegistrationReport:
    """Load entry-point plugins and register returned candidates."""

    if not config:
        return PluginRegistrationReport.empty()

    groups: List[str] = []
    if config.auto_load:
        groups.extend(DEFAULT_ENTRY_POINT_GROUPS)
    groups.extend(config.entry_points)
    if not groups:
        return PluginRegistrationReport.empty()

    seen = set()
    report = PluginRegistrationReport()
    for group in groups:
        if group in seen:
            continue
        seen.add(group)
        report.groups.append(group)
        for result in _load_entry_point_factories(group):
            if not result.factory:
                report.errors.append(
                    PluginErrorRecord(
                        group=group,
                        entry_point=result.entry_point,
                        reason=result.error or "not-callable",
                    )
                )
                continue
            try:
                payload = result.factory()
            except Exception as exc:  # pragma: no cover - diagnostic only
                logger.warning(
                    "plugin-metadata-failed",
                    group=group,
                    entry_point=result.entry_point,
                    error=str(exc),
                )
                report.errors.append(
                    PluginErrorRecord(group=group, entry_point=result.entry_point, reason=str(exc))
                )
                continue
            normalized = _normalize_candidates(payload)
            if not normalized:
                report.errors.append(
                    PluginErrorRecord(
                        group=group,
                        entry_point=result.entry_point,
                        reason=f"unsupported payload {type(payload).__name__}",
                    )
                )
                continue
            for candidate in normalized:
                resolver.register(candidate)
            report.entries.append(
                PluginEntryRecord(
                    group=group,
                    entry_point=result.entry_point,
                    payload_type=type(payload).__name__,
                    registered_candidates=len(normalized),
                )
            )
            report.registered += len(normalized)
    if report.registered:
        logger.info("plugins-registered", groups=list(report.groups), registered=report.registered)
    return report


def _normalize_candidates(payload: object) -> List[Candidate]:
    candidates: List[Candidate] = []
    if payload is None:
        return candidates
    if isinstance(payload, Candidate):
        return [payload]
    if isinstance(payload, AdapterMetadata):
        return [payload.to_candidate()]
    if isinstance(payload, abc.Iterable) and not isinstance(payload, (str, bytes)):
        for item in payload:
            candidates.extend(_normalize_candidates(item))
        return candidates
    logger.warning(
        "plugin-unsupported-payload",
        type=type(payload).__name__,
    )
    return candidates


def _load_entry_point_factories(group: str) -> List[_FactoryLoadResult]:
    results: List[_FactoryLoadResult] = []
    for entry_point in iter_entry_points(group):
        result = _FactoryLoadResult(group=group, entry_point=entry_point.name)
        try:
            loaded = entry_point.load()
        except Exception as exc:  # pragma: no cover - logging guard
            logger.warning(
                "plugin-load-failed",
                group=group,
                entry_point=entry_point.name,
                error=str(exc),
            )
            result.error = str(exc)
            results.append(result)
            continue
        if callable(loaded):
            result.factory = loaded
        else:
            result.error = f"not-callable:{type(loaded).__name__}"
            logger.warning(
                "plugin-not-callable",
                group=group,
                entry_point=entry_point.name,
                type=type(loaded).__name__,
            )
        results.append(result)
    return results
