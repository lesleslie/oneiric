"""Lightweight service supervisor that enforces pause/drain semantics."""

from __future__ import annotations

import asyncio
import inspect
import itertools
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from oneiric.core.logging import get_logger

from .activity import DomainActivity
from .protocols import ActivityStoreProtocol

logger = get_logger("runtime.supervisor")


ListenerCallback = Callable[[str, str, DomainActivity], Awaitable[None] | None]


@dataclass
class _Listener:
    domain: str | None
    callback: ListenerCallback


class ServiceSupervisor:
    """Polls the activity store and exposes pause/drain decisions."""

    def __init__(
        self,
        activity_store: ActivityStoreProtocol,
        *,
        poll_interval: float = 2.0,
    ) -> None:
        self._activity_store = activity_store
        self._poll_interval = max(poll_interval, 0.1)
        self._state: dict[str, dict[str, DomainActivity]] = {}
        self._lock = threading.RLock()
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._listeners: dict[int, _Listener] = {}
        self._listener_seq = itertools.count(1)
        self.refresh()

    async def start(self) -> None:
        """Start the background polling loop."""

        if self._task:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._poll_loop(), name="service.supervisor")

    async def stop(self) -> None:
        """Stop the background polling loop."""

        if not self._task:
            return
        self._stopped.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:  # pragma: no cover - expected cancellation path
            pass
        finally:
            self._task = None

    def refresh(self) -> None:
        """Refresh cached activity state from the backing store."""

        snapshot = self._activity_store.snapshot()
        deltas = self._calculate_deltas(snapshot)
        with self._lock:
            self._state = snapshot
        if deltas:
            self._notify_listeners(deltas)

    def snapshot(self) -> dict[str, dict[str, DomainActivity]]:
        """Return an in-memory snapshot of the current state."""

        with self._lock:
            return {domain: state.copy() for domain, state in self._state.items()}

    def add_listener(
        self,
        callback: ListenerCallback,
        *,
        domain: str | None = None,
        fire_immediately: bool = False,
    ) -> Callable[[], None]:
        """Register a callback invoked when activity entries change.

        Returns a callable that removes the listener when invoked.
        """

        token = next(self._listener_seq)
        with self._lock:
            self._listeners[token] = _Listener(domain=domain, callback=callback)
            current_snapshot = None if not fire_immediately else self._state.copy()

        if current_snapshot:
            for current_domain, entries in current_snapshot.items():
                if domain and current_domain != domain:
                    continue
                for key, state in entries.items():
                    self._dispatch_listener(callback, current_domain, key, state)

        def _remove() -> None:
            with self._lock:
                self._listeners.pop(token, None)

        return _remove

    def should_accept_work(self, domain: str, key: str) -> bool:
        """Return True when the domain/key is neither paused nor draining."""

        state = self._state.get(domain, {}).get(key)
        if state is None:
            # Default to allowed when no entry exists.
            return True
        return not state.paused and not state.draining

    def activity_state(self, domain: str, key: str) -> DomainActivity:
        """Return the cached activity entry for domain/key."""

        state = self._state.get(domain, {}).get(key)
        if state is None:
            return DomainActivity()
        return state

    def _calculate_deltas(
        self, fresh: dict[str, dict[str, DomainActivity]]
    ) -> list[tuple[str, str, DomainActivity]]:
        deltas: list[tuple[str, str, DomainActivity]] = []
        with self._lock:
            previous = {
                domain: entries.copy() for domain, entries in self._state.items()
            }
        for domain, entries in fresh.items():
            old_entries = previous.get(domain, {})
            for key, state in entries.items():
                if old_entries.get(key) != state:
                    deltas.append((domain, key, state))
        for domain, entries in previous.items():
            new_entries = fresh.get(domain, {})
            for key in entries:
                if key not in new_entries:
                    deltas.append((domain, key, DomainActivity()))
        return deltas

    def _notify_listeners(self, deltas: list[tuple[str, str, DomainActivity]]) -> None:
        if not deltas:
            return
        with self._lock:
            listeners = list(self._listeners.values())
        if not listeners:
            return
        for domain, key, state in deltas:
            for listener in listeners:
                if listener.domain and listener.domain != domain:
                    continue
                self._dispatch_listener(listener.callback, domain, key, state)

    def _dispatch_listener(
        self,
        callback: ListenerCallback,
        domain: str,
        key: str,
        state: DomainActivity,
    ) -> None:
        try:
            result = callback(domain, key, state)
            if inspect.isawaitable(result):
                asyncio.create_task(result)
        except Exception as exc:  # pragma: no cover - defensive log
            logger.warning(
                "supervisor-listener-error",
                domain=domain,
                key=key,
                error=str(exc),
            )

    async def _poll_loop(self) -> None:
        """Background loop that refreshes state on an interval."""

        try:
            while not self._stopped.is_set():
                self.refresh()
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - logged for observability
            logger.error("supervisor-loop-error", error=str(exc))
            raise
