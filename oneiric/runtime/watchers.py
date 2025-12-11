"""Generic selection/config watchers with filesystem events."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency exercised in integration tests
    from watchfiles import awatch

    WATCHFILES_AVAILABLE = True
except Exception:  # pragma: no cover - import guard for serverless bundles
    WATCHFILES_AVAILABLE = False
    awatch = None  # type: ignore[assignment]

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
        watch_path: str | Path | None = None,
        serverless_mode: bool | None = None,
        use_watchfiles: bool | None = None,
        refresh_on_every_tick: bool = False,
    ) -> None:
        self.name = name
        self.bridge = bridge
        self.layer_selector = layer_selector
        self.settings_loader = settings_loader
        self.poll_interval = poll_interval
        env_serverless = os.getenv("ONEIRIC_SERVERLESS")
        self._serverless_mode = (
            serverless_mode if serverless_mode is not None else bool(env_serverless)
        )
        self._watch_path = self._resolve_watch_path(watch_path)
        wants_events = use_watchfiles if use_watchfiles is not None else True
        if self._serverless_mode:
            wants_events = False
        self._strategy = (
            "events"
            if WATCHFILES_AVAILABLE and wants_events and self._watch_path
            else "poll"
        )
        self._logger = get_logger(f"{name}.watcher")
        self._refresh_on_every_tick = refresh_on_every_tick
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        layer = layer_selector(settings_loader())
        self._last: dict[str, str | None] = layer.selections.copy()  # type: ignore[assignment]
        self._logger.info(
            "watcher-init",
            strategy=self._strategy,
            watch_path=str(self._watch_path) if self._watch_path else None,
            poll_interval=self.poll_interval,
        )

    async def start(self) -> None:
        if self._task:
            raise RuntimeError("Watcher already running")
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"{self.name}.config.watcher"
        )

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def __aenter__(self) -> SelectionWatcher:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        await self.stop()
        return None

    async def run_once(self) -> None:
        await self._tick()

    async def _run(self) -> None:
        if self._strategy == "events":
            await self._run_event_loop()
        else:
            await self._run_poll_loop()

    async def _run_poll_loop(self) -> None:
        while not self._stop_event.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval
                )
            except TimeoutError:
                continue

    async def _run_event_loop(self) -> None:
        if not WATCHFILES_AVAILABLE or not self._watch_path:
            await self._run_poll_loop()
            return
        await self._tick()
        async for _changes in awatch(self._watch_path, stop_event=self._stop_event):
            if self._stop_event.is_set():
                break
            await self._tick()

    async def _tick(self) -> None:
        settings = self.settings_loader()
        layer = self.layer_selector(settings)
        selections = layer.selections.copy()
        added_or_changed = {
            key: provider
            for key, provider in selections.items()
            if self._last.get(key) != provider
        }
        removed = {key for key in self._last.keys() if key not in selections}
        if not added_or_changed and not removed:
            if self._refresh_on_every_tick:
                self.bridge.update_settings(layer)
                self._last = selections.copy()  # type: ignore[assignment]
            return

        self.bridge.update_settings(layer)
        self._last = selections.copy()  # type: ignore[assignment]

        for key, provider in added_or_changed.items():
            await self._trigger_swap(key, provider)
        for key in removed:
            await self._trigger_swap(key, None)

    async def _trigger_swap(self, key: str, provider: str | None) -> None:
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

    def _resolve_watch_path(self, explicit: str | Path | None) -> Path | None:
        candidate = explicit or os.getenv("ONEIRIC_CONFIG")
        if not candidate:
            return None
        path = Path(candidate)
        if path.exists():
            return path
        parent = path.parent
        if parent.exists():
            return parent
        return None
