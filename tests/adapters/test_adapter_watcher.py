"""Tests for AdapterConfigWatcher and adapter_layer helper."""
from __future__ import annotations

from unittest.mock import MagicMock

from oneiric.adapters.watcher import AdapterConfigWatcher, adapter_layer


def test_adapter_layer_returns_adapters_from_settings() -> None:
    """adapter_layer returns settings.adapters (line 10)."""
    settings = MagicMock()
    settings.adapters = {"redis": True, "mongo": False}
    result = adapter_layer(settings)
    assert result == {"redis": True, "mongo": False}


def test_adapter_config_watcher_init() -> None:
    """AdapterConfigWatcher.__init__ calls super().__init__ with correct args (line 21)."""
    bridge = MagicMock()
    settings_loader = MagicMock()
    watcher = AdapterConfigWatcher(
        bridge,
        settings_loader=settings_loader,
        poll_interval=10.0,
    )
    assert watcher.name == "adapter"
    assert watcher.bridge is bridge
    assert watcher.poll_interval == 10.0
