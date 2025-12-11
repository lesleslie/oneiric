"""Tests for the runtime ServiceSupervisor."""

from __future__ import annotations

import asyncio

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


def test_supervisor_snapshot(tmp_path):
    """snapshot() returns in-memory state."""

    store = DomainActivityStore(tmp_path / "activity.sqlite")
    store.set("service", "api", DomainActivity(paused=True, note="maint"))
    supervisor = ServiceSupervisor(store)

    snapshot = supervisor.snapshot()
    assert "service" in snapshot
    assert "api" in snapshot["service"]
    assert snapshot["service"]["api"].note == "maint"
