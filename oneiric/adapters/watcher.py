"""Adapter config watcher wrapper."""

from __future__ import annotations

from oneiric.core.config import OneiricSettings, load_settings
from oneiric.runtime.watchers import SelectionWatcher

from .bridge import AdapterBridge


def adapter_layer(settings: OneiricSettings):
    return settings.adapters


class AdapterConfigWatcher(SelectionWatcher):
    def __init__(
        self,
        bridge: AdapterBridge,
        *,
        settings_loader=load_settings,
        poll_interval: float = 5.0,
    ) -> None:
        super().__init__(
            "adapter",
            bridge,
            layer_selector=adapter_layer,
            settings_loader=settings_loader,
            poll_interval=poll_interval,
        )
