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
        lambda group: [
            plugins._FactoryLoadResult(
                group=group, entry_point="adapter_meta", factory=lambda: metadata
            )
        ]
        if group == plugins.DEFAULT_ENTRY_POINT_GROUPS[0]
        else [],
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
