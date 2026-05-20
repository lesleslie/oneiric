"""Tests for entry-point discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass

from oneiric import plugins
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.config import PluginsConfig
from oneiric.core.resolution import Candidate, Resolver


@dataclass
class DummyEntryPoint:
    name: str
    value: object
    group: str = "oneiric.adapters"

    def load(self):
        return self.value


class DummyEntryPoints:
    def __init__(self, entries):
        self._entries = entries

    def select(self, *, group):
        return tuple(entry for entry in self._entries if entry.group == group)


def test_iter_entry_points_modern_api(monkeypatch):
    entries = [DummyEntryPoint("plugin", lambda: 1)]
    monkeypatch.setattr(
        plugins.metadata, "entry_points", lambda: DummyEntryPoints(entries)
    )

    result = plugins.iter_entry_points("oneiric.adapters")

    assert len(result) == 1
    assert result[0].name == "plugin"


def test_iter_entry_points_legacy_api(monkeypatch):
    entries = [DummyEntryPoint("legacy", lambda: 2)]
    monkeypatch.setattr(
        plugins.metadata, "entry_points", lambda: {"oneiric.adapters": entries}
    )

    result = plugins.iter_entry_points("oneiric.adapters")

    assert len(result) == 1
    assert result[0].name == "legacy"


def test_load_callables_filters_non_callable(monkeypatch):
    entries = [
        DummyEntryPoint("callable", lambda: 42),
        DummyEntryPoint("not-callable", 123),
    ]
    monkeypatch.setattr(plugins, "iter_entry_points", lambda group: entries)

    callables = plugins.load_callables("oneiric.adapters")

    assert len(callables) == 1
    assert callables[0]() == 42


def test_discover_metadata_invokes_factories(monkeypatch):
    entries = [DummyEntryPoint("meta", lambda: {"provider": "demo"})]
    monkeypatch.setattr(plugins, "load_callables", lambda group: [entries[0].load()])

    metadata = list(plugins.discover_metadata("oneiric.adapters"))

    assert metadata == [{"provider": "demo"}]


def test_register_entrypoint_plugins_registers_candidates(monkeypatch):
    resolver = Resolver()
    config = PluginsConfig(auto_load=False, entry_points=["custom.group"])
    candidate = Candidate(
        domain="adapter",
        key="cache",
        provider="plugin",
        factory=lambda: object(),
    )

    monkeypatch.setattr(
        plugins,
        "_load_entry_point_factories",
        lambda group: [
            plugins._FactoryLoadResult(
                group=group, entry_point="demo", factory=lambda: candidate
            )
        ],
    )

    report = plugins.register_entrypoint_plugins(resolver, config)

    assert report.registered == 1
    assert report.entries[0].entry_point == "demo"
    assert resolver.resolve("adapter", "cache").provider == "plugin"


def test_register_entrypoint_plugins_handles_adapter_metadata(monkeypatch):
    resolver = Resolver()
    config = PluginsConfig(auto_load=True)
    metadata = AdapterMetadata(
        category="demo", provider="plugin", factory=lambda: object()
    )

    monkeypatch.setattr(
        plugins,
        "_load_entry_point_factories",
        lambda group: (
            [
                plugins._FactoryLoadResult(
                    group=group, entry_point="adapter_meta", factory=lambda: metadata
                )
            ]
            if group == plugins.DEFAULT_ENTRY_POINT_GROUPS[0]
            else []
        ),
    )

    report = plugins.register_entrypoint_plugins(resolver, config)

    assert report.registered == 1
    assert resolver.resolve("adapter", "demo").provider == "plugin"


def test_register_entrypoint_plugins_records_errors(monkeypatch):
    resolver = Resolver()
    config = PluginsConfig(auto_load=False, entry_points=["broken.group"])

    monkeypatch.setattr(
        plugins,
        "_load_entry_point_factories",
        lambda group: [
            plugins._FactoryLoadResult(
                group=group, entry_point="broken", factory=lambda: None
            )
        ],
    )

    report = plugins.register_entrypoint_plugins(resolver, config)

    assert report.registered == 0
    assert report.errors


def test_demo_adapter_callable() -> None:
    from oneiric.demo import DemoAdapter

    adapter = DemoAdapter()
    result = adapter()
    assert result == {"type": "demo"}


# ---------------------------------------------------------------------------
# Gap-fill: uncovered branches in plugins.py
# ---------------------------------------------------------------------------

from unittest.mock import patch

from oneiric import plugins as _plugins
from oneiric.core.resolution import CandidateSource


def test_plugin_registration_report_empty_and_as_dict() -> None:
    report = _plugins.PluginRegistrationReport.empty()
    assert report.registered == 0
    d = report.as_dict()
    assert d["registered"] == 0
    assert isinstance(d["groups"], list)
    assert isinstance(d["entries"], list)
    assert isinstance(d["errors"], list)


def test_iter_entry_points_returns_empty_for_no_select_no_get(monkeypatch) -> None:
    class NoSelectNoGet:
        pass

    monkeypatch.setattr(_plugins.metadata, "entry_points", lambda: NoSelectNoGet())
    result = _plugins.iter_entry_points("some.group")
    assert result == ()


def test_register_entrypoint_plugins_falsy_config_returns_empty() -> None:
    resolver = Resolver()
    report = _plugins.register_entrypoint_plugins(resolver, None)  # type: ignore[arg-type]
    assert report.registered == 0


def test_register_entrypoint_plugins_returns_cached_report() -> None:
    resolver = Resolver()
    config = PluginsConfig(auto_load=False, entry_points=["some.group"])
    existing = _plugins.PluginRegistrationReport(registered=7)
    resolver._oneiric_plugins_loaded = True  # type: ignore[attr-defined]
    resolver._oneiric_plugin_report = existing  # type: ignore[attr-defined]

    report = _plugins.register_entrypoint_plugins(resolver, config, skip_if_loaded=True)
    assert report.registered == 7


def test_register_entrypoint_plugins_returns_empty_when_cached_is_not_report() -> None:
    resolver = Resolver()
    config = PluginsConfig(auto_load=False, entry_points=["some.group"])
    resolver._oneiric_plugins_loaded = True  # type: ignore[attr-defined]
    resolver._oneiric_plugin_report = "not-a-report"  # type: ignore[attr-defined]

    report = _plugins.register_entrypoint_plugins(resolver, config, skip_if_loaded=True)
    assert report.registered == 0


def test_register_entrypoint_plugins_empty_groups_returns_empty() -> None:
    resolver = Resolver()
    config = PluginsConfig(auto_load=False, entry_points=[])
    report = _plugins.register_entrypoint_plugins(resolver, config)
    assert report.registered == 0


def test_process_plugin_groups_deduplicates_groups(monkeypatch) -> None:
    resolver = Resolver()
    seen_groups: list[str] = []

    def fake_factories(group: str):
        seen_groups.append(group)
        return []

    with patch.object(_plugins, "_load_entry_point_factories", side_effect=fake_factories):
        _plugins._process_plugin_groups(resolver, ["g1", "g1", "g2"])

    assert seen_groups == ["g1", "g2"]


def test_process_plugin_group_records_error_for_missing_factory(monkeypatch) -> None:
    resolver = Resolver()
    report = _plugins.PluginRegistrationReport()
    result = _plugins._FactoryLoadResult(group="g", entry_point="ep", factory=None, error="load-error")

    with patch.object(_plugins, "_load_entry_point_factories", return_value=[result]):
        _plugins._process_plugin_group(resolver, "g", report)

    assert len(report.errors) == 1
    assert report.errors[0].reason == "load-error"


def test_process_plugin_group_continues_on_invoke_had_error(monkeypatch) -> None:
    resolver = Resolver()
    report = _plugins.PluginRegistrationReport()
    result = _plugins._FactoryLoadResult(group="g", entry_point="ep", factory=lambda: "x")

    with patch.object(_plugins, "_load_entry_point_factories", return_value=[result]):
        with patch.object(_plugins, "_invoke_factory", return_value=(None, True)):
            _plugins._process_plugin_group(resolver, "g", report)

    assert report.registered == 0


def test_invoke_factory_returns_had_error_when_factory_is_none() -> None:
    result = _plugins._FactoryLoadResult(group="g", entry_point="ep", factory=None)
    payload, had_error = _plugins._invoke_factory("g", result, _plugins.PluginRegistrationReport())
    assert had_error is True
    assert payload is None


def test_normalize_candidates_handles_iterable_of_candidates() -> None:
    c1 = Candidate(
        domain="adapter", key="c1", provider="p", factory=lambda: None,
        source=CandidateSource.MANUAL,
    )
    c2 = Candidate(
        domain="adapter", key="c2", provider="p", factory=lambda: None,
        source=CandidateSource.MANUAL,
    )
    result = _plugins._normalize_candidates([c1, c2])
    assert len(result) == 2


def test_normalize_candidates_warns_for_unsupported_type() -> None:
    result = _plugins._normalize_candidates(42)
    assert result == []
