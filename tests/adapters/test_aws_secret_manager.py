from __future__ import annotations

import pytest

from oneiric.adapters.secrets.aws import (
    AWSSecretManagerAdapter,
    AWSSecretManagerSettings,
)
from oneiric.core.lifecycle import LifecycleError


class _FakeAWSSecretsClient:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets
        self.calls: list[dict[str, str]] = []

    async def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["SecretId"]
        if name not in self._secrets:
            raise _ResourceNotFoundError()
        return {"SecretString": self._secrets[name]}

    async def close(self) -> None:  # pragma: no cover - cleanup stub
        return None


class _ResourceNotFoundError(Exception):
    def __init__(self) -> None:
        self.response = {"Error": {"Code": "ResourceNotFoundException"}}


@pytest.mark.asyncio
async def test_aws_secret_manager_adapter_fetches_and_caches(monkeypatch) -> None:
    client = _FakeAWSSecretsClient({"DB_PASSWORD": "secret"})
    settings = AWSSecretManagerSettings(region="us-east-1")
    adapter = AWSSecretManagerAdapter(settings, client=client)
    await adapter.init()
    value = await adapter.get_secret("DB_PASSWORD")
    assert value == "secret"
    cached = await adapter.get_secret("DB_PASSWORD")
    assert cached == "secret"
    missing = await adapter.get_secret("MISSING", allow_missing=True)
    assert missing is None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_aws_secret_manager_adapter_requires_init(monkeypatch) -> None:
    adapter = AWSSecretManagerAdapter(AWSSecretManagerSettings(region="us-east-1"))
    with pytest.raises(LifecycleError):
        await adapter.get_secret("TEST")
