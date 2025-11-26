"""Generic selection/config watchers."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from oneiric.core.config import LayerSettings, OneiricSettings, load_settings
from oneiric.core.logging import get_logger

LayerSelector = Callable[[OneiricSettings], LayerSettings]


class SelectionWatcher:
    """Polls configuration for domain selection changes and triggers swaps."""

    def __init__(
        self,
        name: str,
        bridge: Any,
        *,
        layer_selector: LayerSelector,
        settings_loader: Callable[[], OneiricSettings] = load_settings,
        poll_interval: float = 5.0,
    ) -> None:
        self.name = name
        self.bridge = bridge
        self.layer_selector = layer_selector
        self.settings_loader = settings_loader
        self.poll_interval = poll_interval
        self._logger = get_logger(f"{name}.watcher")
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()
        layer = layer_selector(settings_loader())
        self._last: Dict[str, Optional[str]] = dict(layer.selections)

    async def start(self) -> None:
        if self._task:
            raise RuntimeError("Watcher already running")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name=f"{self.name}.config.watcher")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def __aenter__(self) -> "SelectionWatcher":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> Optional[bool]:
        await self.stop()
        return None

    async def run_once(self) -> None:
        await self._tick()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        settings = self.settings_loader()
        layer = self.layer_selector(settings)
        selections = dict(layer.selections)
        added_or_changed = {
            key: provider
            for key, provider in selections.items()
            if self._last.get(key) != provider
        }
        removed = {key for key in self._last.keys() if key not in selections}
        if not added_or_changed and not removed:
            return

        self.bridge.update_settings(layer)
        self._last = selections

        for key, provider in added_or_changed.items():
            await self._trigger_swap(key, provider)
        for key in removed:
            await self._trigger_swap(key, None)

    async def _trigger_swap(self, key: str, provider: Optional[str]) -> None:
        domain = getattr(self.bridge, "domain", self.name)
        activity = None
        activity_getter = getattr(self.bridge, "activity_state", None)
        if callable(activity_getter):
            activity = activity_getter(key)
        if activity and activity.paused:
            self._logger.info(
                "selection-swap-skipped",
                domain=domain,
                key=key,
                reason="paused",
                provider=provider,
            )
            return
        if activity and activity.draining and provider is not None:
            self._logger.info(
                "selection-swap-delayed",
                domain=domain,
                key=key,
                reason="draining",
                provider=provider,
            )
            return
        try:
            await self.bridge.lifecycle.swap(domain, key, provider=provider)
            self._logger.info(
                "selection-swap-triggered",
                domain=domain,
                key=key,
                provider=provider or "auto",
            )
        except Exception as exc:  # pragma: no cover - log and continue
            self._logger.error(
                "selection-swap-failed",
                domain=domain,
                key=key,
                provider=provider,
                exc_info=exc,
            )
