from __future__ import annotations

from dataclasses import dataclass

import pytest

from oneiric.adapters.dns.gcdns import GCDNSAdapter, GCDNSSettings


@dataclass
class _FakeRecord:
    name: str
    record_type: str
    ttl: int
    rrdatas: list[str]


class _FakeChange:
    def __init__(self) -> None:
        self.added: list[_FakeRecord] = []
        self.deleted: list[_FakeRecord] = []
        self.created = False
        self.id = "change-1"

    def add_record_set(self, record: _FakeRecord) -> None:
        self.added.append(record)

    def delete_record_set(self, record: _FakeRecord) -> None:
        self.deleted.append(record)

    def create(self) -> None:
        self.created = True


class _FakeZone:
    def __init__(self, records: list[_FakeRecord]) -> None:
        self._records = records
        self.last_change: _FakeChange | None = None
        self.raise_on_exists = False

    def exists(self) -> bool:
        if self.raise_on_exists:
            raise RuntimeError("boom")
        return True

    def list_resource_record_sets(self) -> list[_FakeRecord]:
        return list(self._records)

    def resource_record_set(
        self, name: str, record_type: str, ttl: int, rrdatas: list[str]
    ) -> _FakeRecord:
        return _FakeRecord(name=name, record_type=record_type, ttl=ttl, rrdatas=rrdatas)

    def changes(self) -> _FakeChange:
        self.last_change = _FakeChange()
        return self.last_change


@pytest.mark.asyncio
async def test_gcdns_records_create_update_delete() -> None:
    zone = _FakeZone(records=[_FakeRecord("demo.example.com.", "A", 300, ["1.1.1.1"])])
    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"), zone=zone)

    await adapter.init()

    records = await adapter.list_records(record_type="A")
    assert records[0]["name"] == "demo.example.com."

    change_id = await adapter.create_record(name="demo.example.com.", content="2.2.2.2")
    assert change_id == "change-1"
    assert zone.last_change is not None
    assert zone.last_change.added

    await adapter.update_record(name="demo.example.com.", content="3.3.3.3")
    assert zone.last_change is not None
    assert zone.last_change.deleted

    assert await adapter.delete_record(name="demo.example.com.") is True
    assert zone.last_change is not None
    assert zone.last_change.deleted

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcdns_health_handles_errors() -> None:
    zone = _FakeZone(records=[])
    zone.raise_on_exists = True
    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"), zone=zone)
    await adapter.init()
    assert await adapter.health() is False
    await adapter.cleanup()
