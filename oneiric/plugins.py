from __future__ import annotations

from collections import abc
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from importlib import metadata

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
    groups: list[str] = field(default_factory=list)
    registered: int = 0
    entries: list[PluginEntryRecord] = field(default_factory=list)
    errors: list[PluginErrorRecord] = field(default_factory=list)

    @classmethod
    def empty(cls) -> PluginRegistrationReport:
        return cls()

    def as_dict(self) -> dict:
        return {
            "groups": self.groups.copy(),
            "registered": self.registered,
            "entries": [entry.__dict__ for entry in self.entries],
            "errors": [error.__dict__ for error in self.errors],
        }


@dataclass
class _FactoryLoadResult:
    group: str
    entry_point: str
    factory: Callable[[], object] | None = None
    error: str | None = None


def iter_entry_points(group: str) -> Sequence[metadata.EntryPoint]:
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return tuple(entry_points.select(group=group))

    if hasattr(entry_points, "get"):
        return tuple(entry_points.get(group, []))  # type: ignore[attr-defined]
    return ()


def load_callables(group: str) -> list[Callable[[], object]]:
    return [
        result.factory
        for result in _load_entry_point_factories(group)
        if result.factory
    ]


def discover_metadata(group: str) -> Iterable[object]:
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


def register_entrypoint_plugins(
    resolver: Resolver,
    config: PluginsConfig,
    *,
    skip_if_loaded: bool = True,
) -> PluginRegistrationReport:
    if not config:
        return PluginRegistrationReport.empty()

    if skip_if_loaded and getattr(resolver, "_oneiric_plugins_loaded", False):
        cached = getattr(resolver, "_oneiric_plugin_report", None)
        if isinstance(cached, PluginRegistrationReport):
            return cached
        return PluginRegistrationReport.empty()

    groups = _build_plugin_groups(config)
    if not groups:
        return PluginRegistrationReport.empty()

    report = _process_plugin_groups(resolver, groups)
    resolver._oneiric_plugins_loaded = True  # type: ignore[attr-defined]
    resolver._oneiric_plugin_report = report  # type: ignore[attr-defined]

    if report.registered:
        logger.info(
            "plugins-registered",
            groups=report.groups.copy(),
            registered=report.registered,
        )
    return report


def _build_plugin_groups(config: PluginsConfig) -> list[str]:
    groups: list[str] = []
    if config.auto_load:
        groups.extend(DEFAULT_ENTRY_POINT_GROUPS)
    groups.extend(config.entry_points)
    return groups


def _process_plugin_groups(
    resolver: Resolver, groups: list[str]
) -> PluginRegistrationReport:
    seen = set()
    report = PluginRegistrationReport()

    for group in groups:
        if group in seen:
            continue
        seen.add(group)
        report.groups.append(group)
        _process_plugin_group(resolver, group, report)

    return report


def _process_plugin_group(
    resolver: Resolver, group: str, report: PluginRegistrationReport
) -> None:
    for result in _load_entry_point_factories(group):
        if not result.factory:
            _record_factory_error(group, result, report)
            continue

        payload, had_error = _invoke_factory(group, result, report)
        if had_error:
            continue

        _register_payload_candidates(resolver, group, result, payload, report)


def _record_factory_error(
    group: str, result: _FactoryLoadResult, report: PluginRegistrationReport
) -> None:
    report.errors.append(
        PluginErrorRecord(
            group=group,
            entry_point=result.entry_point,
            reason=result.error or "not-callable",
        )
    )


def _invoke_factory(
    group: str, result: _FactoryLoadResult, report: PluginRegistrationReport
) -> tuple[object | None, bool]:
    if result.factory is None:
        return (None, True)

    try:
        payload = result.factory()
        return (payload, False)
    except Exception as exc:  # pragma: no cover - diagnostic only
        logger.warning(
            "plugin-metadata-failed",
            group=group,
            entry_point=result.entry_point,
            error=str(exc),
        )
        report.errors.append(
            PluginErrorRecord(
                group=group, entry_point=result.entry_point, reason=str(exc)
            )
        )
        return (None, True)


def _register_payload_candidates(
    resolver: Resolver,
    group: str,
    result: _FactoryLoadResult,
    payload: object,
    report: PluginRegistrationReport,
) -> None:
    normalized = _normalize_candidates(payload)
    if not normalized:
        report.errors.append(
            PluginErrorRecord(
                group=group,
                entry_point=result.entry_point,
                reason=f"unsupported payload {type(payload).__name__}",
            )
        )
        return

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


def _normalize_candidates(payload: object) -> list[Candidate]:
    candidates: list[Candidate] = []
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


def _load_entry_point_factories(group: str) -> list[_FactoryLoadResult]:
    results: list[_FactoryLoadResult] = []
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
