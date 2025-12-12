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
