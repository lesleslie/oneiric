"""Tests for the runtime ServiceSupervisor."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from oneiric.runtime.activity import DomainActivity, DomainActivityStore
from oneiric.runtime.supervisor import ServiceSupervisor


@pytest.mark.asyncio
async def test_supervisor_polling_and_decisions(tmp_path):
    """Supervisor refreshes activity state and enforces pause/drain flags."""

    store = DomainActivityStore(tmp_path / "activity.sqlite")
    supervisor = ServiceSupervisor(store, poll_interval=0.01)

    # Default state allows work.
    assert supervisor.should_accept_work("service", "api")

    store.set("service", "api", DomainActivity(paused=True))
    supervisor.refresh()

    assert not supervisor.should_accept_work("service", "api")
    state = supervisor.activity_state("service", "api")
    assert state.paused
    assert not state.draining

    await supervisor.start()
    # Flip to draining=False -> allowed, ensure poll loop catches it.
    store.set("service", "api", DomainActivity())
    await asyncio.sleep(0.05)

    assert supervisor.should_accept_work("service", "api")

    await supervisor.stop()


@pytest.mark.asyncio
async def test_supervisor_notifies_listeners(tmp_path):
    """Supervisor listeners receive pause/drain deltas."""

    store = DomainActivityStore(tmp_path / "activity.sqlite")
    supervisor = ServiceSupervisor(store, poll_interval=0.01)
    events: list[tuple[str, str, DomainActivity]] = []

    def listener(domain: str, key: str, state: DomainActivity) -> None:
        events.append((domain, key, state))

    supervisor.add_listener(listener, fire_immediately=True)
    await supervisor.start()

    store.set("service", "api", DomainActivity(paused=True))
    await asyncio.sleep(0.05)

    assert any(
        domain == "service" and key == "api" and state.paused
        for domain, key, state in events
    )

    store.set("service", "api", DomainActivity())
    await asyncio.sleep(0.05)
    assert any(
        domain == "service" and key == "api" and not state.paused and not state.draining
        for domain, key, state in events
    )

    await supervisor.stop()


@pytest.mark.asyncio
async def test_supervisor_listener_filters_and_fire_immediately(tmp_path):
    store = DomainActivityStore(tmp_path / "activity.sqlite")
    store.set("service", "api", DomainActivity(paused=True))
    store.set("task", "worker", DomainActivity(paused=True))
    supervisor = ServiceSupervisor(store)

    events: list[tuple[str, str, DomainActivity]] = []

    def listener(domain: str, key: str, state: DomainActivity) -> None:
        events.append((domain, key, state))

    remove = supervisor.add_listener(
        listener, domain="service", fire_immediately=True
    )

    assert events == [("service", "api", DomainActivity(paused=True))]
    remove()


@pytest.mark.asyncio
async def test_supervisor_async_listener_dispatch_and_error_logging(tmp_path):
    store = DomainActivityStore(tmp_path / "activity.sqlite")
    supervisor = ServiceSupervisor(store)
    seen: list[tuple[str, str, DomainActivity]] = []

    async def listener(domain: str, key: str, state: DomainActivity) -> None:
        seen.append((domain, key, state))

    supervisor.add_listener(listener)

    with patch("oneiric.runtime.supervisor.logger.warning") as mock_warning:
        def _boom(domain: str, key: str, state: DomainActivity) -> None:
            raise RuntimeError("boom")

        supervisor._dispatch_listener(
            _boom,
            "service",
            "api",
            DomainActivity(),
        )

    supervisor._dispatch_listener(listener, "service", "api", DomainActivity())
    await asyncio.sleep(0)

    assert any(domain == "service" for domain, _, _ in seen)
    mock_warning.assert_called_once()


@pytest.mark.asyncio
async def test_supervisor_start_and_stop_idempotent(tmp_path):
    store = DomainActivityStore(tmp_path / "activity.sqlite")
    supervisor = ServiceSupervisor(store, poll_interval=0.01)

    await supervisor.start()
    await supervisor.start()
    await supervisor.stop()
    await supervisor.stop()

    assert supervisor._task is None


def test_supervisor_snapshot(tmp_path):
    """snapshot() returns in-memory state."""

    store = DomainActivityStore(tmp_path / "activity.sqlite")
    store.set("service", "api", DomainActivity(paused=True, note="maint"))
    supervisor = ServiceSupervisor(store)

    snapshot = supervisor.snapshot()
    assert "service" in snapshot
    assert "api" in snapshot["service"]
    assert snapshot["service"]["api"].note == "maint"


def test_supervisor_default_activity_state(tmp_path):
    store = DomainActivityStore(tmp_path / "activity.sqlite")
    supervisor = ServiceSupervisor(store)

    state = supervisor.activity_state("service", "missing")

    assert state == DomainActivity()


def test_supervisor_notify_listeners_with_empty_deltas(tmp_path):
    store = DomainActivityStore(tmp_path / "activity.sqlite")
    supervisor = ServiceSupervisor(store)

    supervisor._notify_listeners([])
