from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from oneiric.core.metadata import build_metadata, register_metadata, settings_model_path


class ExampleSettings(BaseModel):
    enabled: bool = True


@dataclass
class _CandidateLike:
    value: dict[str, Any]

    def to_candidate(self) -> dict[str, Any]:
        return self.value


def test_settings_model_path_handles_type_and_none() -> None:
    assert (
        settings_model_path(ExampleSettings)
        == f"{ExampleSettings.__module__}.ExampleSettings"
    )
    assert settings_model_path(None) is None


def test_build_metadata_filters_empty_values() -> None:
    metadata = build_metadata(
        {"a": 1, "b": None, "c": [], "d": {}, "e": False},
        {"f": "ok", "g": None, "h": []},
    )

    assert metadata == {"a": 1, "e": False, "f": "ok"}


def test_register_metadata_registers_candidates_and_logs() -> None:
    class ResolverMock:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]] = []

        def register_from_pkg(
            self, package_name, package_path, candidates, *, priority=None
        ):
            self.calls.append(
                (
                    package_name,
                    package_path,
                    list(candidates),
                    {"priority": priority},
                )
            )

    class LoggerMock:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def info(self, key, **kwargs):
            self.calls.append((key, kwargs))

    resolver = ResolverMock()
    logger = LoggerMock()
    items = [
        _CandidateLike({"name": "alpha"}),  # type: ignore[arg-type]
        _CandidateLike({"name": "beta"}),  # type: ignore[arg-type]
    ]

    register_metadata(
        resolver,  # type: ignore
        "pkg.name",
        "pkg/path",
        items,
        priority=7,
        logger=logger,
        log_key="metadata-registered",
    )

    assert resolver.calls == [
        ("pkg.name", "pkg/path", [{"name": "alpha"}, {"name": "beta"}], {"priority": 7})
    ]
    assert logger.calls == [
        ("metadata-registered", {"package": "pkg.name", "count": 2})
    ]
