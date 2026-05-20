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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcdns_init_with_client_creates_zone() -> None:
    """init() calls client.zone() when _zone is None and _client is provided (lines 60-63)."""
    zone = _FakeZone(records=[])

    class _FakeClient:
        def zone(self, managed_zone: str) -> _FakeZone:
            return zone

    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="my-zone"), client=_FakeClient())
    await adapter.init()
    assert adapter._zone is zone


@pytest.mark.asyncio
async def test_gcdns_init_with_sys_modules_google_cloud(monkeypatch) -> None:
    """_create_client() imports google.cloud.dns when client is None (lines 171-190)."""
    import sys
    import types

    zone = _FakeZone(records=[])

    class FakeDNSClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def zone(self, managed_zone: str) -> _FakeZone:
            return zone

    fake_dns = types.ModuleType("google.cloud.dns")
    fake_dns.Client = FakeDNSClient  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_cloud = types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.dns", fake_dns)

    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="my-zone", project_id="proj"))
    await adapter.init()
    assert adapter._zone is zone


@pytest.mark.asyncio
async def test_gcdns_list_records_filters_by_name() -> None:
    """list_records() skips records whose name doesn't match (line 89)."""
    zone = _FakeZone(records=[
        _FakeRecord("alpha.example.com.", "A", 300, ["1.1.1.1"]),
        _FakeRecord("beta.example.com.", "A", 300, ["2.2.2.2"]),
    ])
    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"), zone=zone)
    await adapter.init()
    records = await adapter.list_records(name="alpha.example.com.")
    assert len(records) == 1
    assert records[0]["name"] == "alpha.example.com."


@pytest.mark.asyncio
async def test_gcdns_list_records_filters_by_type() -> None:
    """list_records() skips records whose type doesn't match (line 87)."""
    zone = _FakeZone(records=[
        _FakeRecord("a.example.com.", "A", 300, ["1.1.1.1"]),
        _FakeRecord("txt.example.com.", "TXT", 300, ['"hello"']),
    ])
    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"), zone=zone)
    await adapter.init()
    records = await adapter.list_records(record_type="TXT")
    assert len(records) == 1
    assert records[0]["type"] == "TXT"


@pytest.mark.asyncio
async def test_gcdns_create_change_exception_raises_lifecycle_error() -> None:
    """_create_change raises LifecycleError when change.create fails (lines 213-215)."""
    from oneiric.core.lifecycle import LifecycleError

    class FailChange(_FakeChange):
        def create(self) -> None:
            raise OSError("API quota exceeded")

    class FailZone(_FakeZone):
        def changes(self) -> FailChange:
            return FailChange()

    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"), zone=FailZone(records=[]))
    await adapter.init()
    with pytest.raises(LifecycleError, match="gcdns-change-failed"):
        await adapter.create_record(name="demo.", content="1.1.1.1")


def test_gcdns_ensure_zone_raises_when_not_initialized() -> None:
    """_ensure_zone raises LifecycleError when zone is None (line 194)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"))
    with pytest.raises(LifecycleError, match="gcdns-zone-not-initialized"):
        adapter._ensure_zone()


@pytest.mark.asyncio
async def test_gcdns_health_returns_true_on_success() -> None:
    """health() returns True when zone.exists() returns truthy (line 74)."""
    zone = _FakeZone(records=[])
    # raise_on_exists defaults to False → zone.exists() returns True
    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"), zone=zone)
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_gcdns_delete_record_with_explicit_content() -> None:
    """delete_record() with content builds specific record_set and deletes it (lines 154-160)."""
    zone = _FakeZone(records=[_FakeRecord("del.example.com.", "A", 300, ["9.9.9.9"])])
    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="zone"), zone=zone)
    await adapter.init()
    result = await adapter.delete_record(
        name="del.example.com.", content="9.9.9.9", ttl=300
    )
    assert result is True
    assert zone.last_change is not None
    assert len(zone.last_change.deleted) == 1
    assert zone.last_change.deleted[0].name == "del.example.com."


@pytest.mark.asyncio
async def test_gcdns_create_client_with_credentials_file(monkeypatch, tmp_path) -> None:
    """_create_client() loads service account credentials when credentials_file is set (lines 180-186)."""
    import sys
    import types
    from pathlib import Path

    zone = _FakeZone(records=[])
    creds_file = tmp_path / "sa.json"
    creds_file.write_text("{}")

    class FakeCredentials:
        @staticmethod
        def from_service_account_file(path: str) -> "FakeCredentials":
            return FakeCredentials()

    fake_sa = types.ModuleType("google.oauth2.service_account")
    fake_sa.Credentials = FakeCredentials  # type: ignore[attr-defined]
    fake_oauth2 = types.ModuleType("google.oauth2")

    class FakeDNSClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def zone(self, managed_zone: str) -> _FakeZone:
            return zone

    fake_dns = types.ModuleType("google.cloud.dns")
    fake_dns.Client = FakeDNSClient  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_cloud = types.ModuleType("google.cloud")

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.dns", fake_dns)
    monkeypatch.setitem(sys.modules, "google.oauth2", fake_oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_sa)  # type: ignore[arg-type]

    adapter = GCDNSAdapter(
        GCDNSSettings(
            managed_zone="my-zone",
            project_id="proj",
            credentials_file=creds_file,
        )
    )
    await adapter.init()
    assert adapter._zone is zone
