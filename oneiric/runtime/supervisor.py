"""Lightweight service supervisor that enforces pause/drain semantics."""

from __future__ import annotations

import asyncio
import threading

from oneiric.core.logging import get_logger

from .activity import DomainActivity, DomainActivityStore

logger = get_logger("runtime.supervisor")


class ServiceSupervisor:
    """Polls the activity store and exposes pause/drain decisions."""

    def __init__(
        self,
        activity_store: DomainActivityStore,
        *,
        poll_interval: float = 2.0,
    ) -> None:
        self._activity_store = activity_store
        self._poll_interval = max(poll_interval, 0.1)
        self._state: dict[str, dict[str, DomainActivity]] = {}
        self._lock = threading.RLock()
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
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
        with self._lock:
            self._state = snapshot

    def snapshot(self) -> dict[str, dict[str, DomainActivity]]:
        """Return an in-memory snapshot of the current state."""

        with self._lock:
            return {domain: state.copy() for domain, state in self._state.items()}

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
