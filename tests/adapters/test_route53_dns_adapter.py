from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from oneiric.adapters.dns.route53 import Route53DNSAdapter, Route53DNSSettings
from oneiric.core.lifecycle import LifecycleError


class _FakeRoute53Client:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, Any]] = []
        self.change_calls: list[dict[str, Any]] = []

    async def list_resource_record_sets(self, **kwargs: Any) -> dict[str, Any]:
        self.list_calls.append(kwargs)
        return {"ResourceRecordSets": [{"Name": "demo"}]}

    async def change_resource_record_sets(self, **kwargs: Any) -> dict[str, Any]:
        self.change_calls.append(kwargs)
        return {"ChangeInfo": {"Id": "change-123"}}


@pytest.mark.asyncio
async def test_route53_create_update_delete_records() -> None:
    client = _FakeRoute53Client()

    adapter = Route53DNSAdapter(
        Route53DNSSettings(
            hosted_zone_id="Z123",
            access_key_id=SecretStr("key"),
            secret_access_key=SecretStr("secret"),
        ),
        client=client,
    )
    await adapter.init()

    records = await adapter.list_records(record_type="A", name="demo.example.com")
    assert records == [{"Name": "demo"}]
    assert client.list_calls[0]["HostedZoneId"] == "Z123"

    change_id = await adapter.create_record(name="demo", content="1.1.1.1")
    assert change_id == "change-123"
    assert client.change_calls[-1]["ChangeBatch"]["Changes"][0]["Action"] == "CREATE"

    await adapter.update_record(name="demo", content="2.2.2.2")
    assert client.change_calls[-1]["ChangeBatch"]["Changes"][0]["Action"] == "UPSERT"

    assert await adapter.delete_record(name="demo", content="2.2.2.2") is True
    assert client.change_calls[-1]["ChangeBatch"]["Changes"][0]["Action"] == "DELETE"

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_route53_health_handles_errors() -> None:
    class FailingClient:
        async def list_resource_record_sets(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("boom")

    adapter = Route53DNSAdapter(
        Route53DNSSettings(hosted_zone_id="Z123"),
        client=FailingClient(),
    )
    await adapter.init()
    assert await adapter.health() is False
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_route53_change_failure_raises_lifecycle_error() -> None:
    class FailingClient(_FakeRoute53Client):
        async def change_resource_record_sets(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("bad")

    adapter = Route53DNSAdapter(
        Route53DNSSettings(hosted_zone_id="Z123"),
        client=FailingClient(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.create_record(name="demo", content="1.1.1.1")
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route53_init_factory_path() -> None:
    """init() uses client_factory when provided (lines 58-62)."""
    client = _FakeRoute53Client()

    async def factory() -> _FakeRoute53Client:
        return client

    adapter = Route53DNSAdapter(
        Route53DNSSettings(hosted_zone_id="Z123"),
        client_factory=factory,
    )
    await adapter.init()
    assert adapter._client is client
    assert adapter._owns_client is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_route53_init_aioboto3_path(monkeypatch) -> None:
    """init() creates client via aioboto3.Session when no factory/client (lines 64-92)."""
    import sys

    client = _FakeRoute53Client()
    created_kwargs: list[dict] = []

    class FakeClientCM:
        async def __aenter__(self) -> _FakeRoute53Client:
            return client

        async def __aexit__(self, *args: object) -> None:
            pass

    class FakeSession:
        def __init__(self, **kwargs: object) -> None:
            created_kwargs.append(dict(kwargs))

        def client(self, service_name: str) -> FakeClientCM:
            return FakeClientCM()

    class FakeAioboto3:
        Session = FakeSession

    monkeypatch.setitem(sys.modules, "aioboto3", FakeAioboto3)  # type: ignore[arg-type]

    adapter = Route53DNSAdapter(
        Route53DNSSettings(
            hosted_zone_id="Z123",
            region_name="eu-west-1",
            access_key_id=SecretStr("key"),
            secret_access_key=SecretStr("secret"),
        ),
    )
    await adapter.init()
    assert adapter._client is client
    assert adapter._owns_client is True
    assert created_kwargs[0].get("region_name") == "eu-west-1"


@pytest.mark.asyncio
async def test_route53_cleanup_with_client_cm() -> None:
    """cleanup() calls __aexit__ on client_cm when set (line 96)."""
    exited: list[bool] = []

    class FakeClientCM:
        async def __aenter__(self) -> _FakeRoute53Client:
            return _FakeRoute53Client()

        async def __aexit__(self, *args: object) -> None:
            exited.append(True)

    adapter = Route53DNSAdapter(Route53DNSSettings(hosted_zone_id="Z123"))
    adapter._client = _FakeRoute53Client()
    adapter._client_cm = FakeClientCM()
    adapter._owns_client = True
    await adapter.cleanup()
    assert exited == [True]


@pytest.mark.asyncio
async def test_route53_health_returns_true() -> None:
    """health() returns True when list_resource_record_sets has ResourceRecordSets (line 108)."""
    adapter = Route53DNSAdapter(
        Route53DNSSettings(hosted_zone_id="Z123"),
        client=_FakeRoute53Client(),
    )
    await adapter.init()
    assert await adapter.health() is True


def test_route53_ensure_client_raises_when_not_initialized() -> None:
    """_ensure_client raises LifecycleError when client is None (line 198)."""
    adapter = Route53DNSAdapter(Route53DNSSettings(hosted_zone_id="Z123"))
    with pytest.raises(LifecycleError, match="route53-dns-client-not-initialized"):
        adapter._ensure_client()
