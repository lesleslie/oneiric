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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aws_health_with_healthcheck_secret_found() -> None:
    """health() fetches healthcheck_secret and returns True when found (lines 100-105)."""
    client = _FakeAWSSecretsClient({"probe-secret": "alive"})
    settings = AWSSecretManagerSettings(
        region="us-east-1", healthcheck_secret="probe-secret"
    )
    adapter = AWSSecretManagerAdapter(settings, client=client)
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_aws_health_with_missing_healthcheck_secret() -> None:
    """health() returns False when healthcheck_secret is not found."""
    client = _FakeAWSSecretsClient({})
    settings = AWSSecretManagerSettings(
        region="us-east-1", healthcheck_secret="probe-secret"
    )
    adapter = AWSSecretManagerAdapter(settings, client=client)
    await adapter.init()
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_aws_cleanup_with_client_cm() -> None:
    """cleanup() calls __aexit__ on client_cm when set (line 112)."""
    exited: list[bool] = []

    class FakeClientCM:
        async def __aenter__(self) -> _FakeAWSSecretsClient:
            return _FakeAWSSecretsClient({})

        async def __aexit__(self, *args: object) -> None:
            exited.append(True)

    adapter = AWSSecretManagerAdapter(AWSSecretManagerSettings(region="us-east-1"))
    adapter._client_cm = FakeClientCM()
    adapter._client = _FakeAWSSecretsClient({})
    await adapter.cleanup()
    assert exited == [True]


@pytest.mark.asyncio
async def test_aws_invalidate_cache() -> None:
    """invalidate_cache() clears the cache (lines 121-123)."""
    client = _FakeAWSSecretsClient({"KEY": "val"})
    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1"), client=client
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    assert adapter._cache  # something cached
    await adapter.invalidate_cache()
    assert adapter._cache == {}


@pytest.mark.asyncio
async def test_aws_get_secret_with_version_stage() -> None:
    """get_secret passes VersionStage to request when set (line 139)."""
    client = _FakeAWSSecretsClient({"KEY": "value"})
    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1", version_stage="AWSCURRENT"),
        client=client,
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    assert client.calls[-1].get("VersionStage") == "AWSCURRENT"


@pytest.mark.asyncio
async def test_aws_get_secret_not_found_reraises_when_not_allow_missing() -> None:
    """get_secret re-raises when allow_missing=False and exception occurs (line 145)."""
    client = _FakeAWSSecretsClient({})
    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1"), client=client
    )
    await adapter.init()
    with pytest.raises(_ResourceNotFoundError):
        await adapter.get_secret("MISSING", allow_missing=False)


@pytest.mark.asyncio
async def test_aws_extract_secret_binary() -> None:
    """_extract_secret returns decoded bytes for SecretBinary (lines 158-161)."""
    client = _FakeAWSSecretsClient({})
    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1"), client=client
    )
    result = adapter._extract_secret({"SecretBinary": b"binary-value"})
    assert result == "binary-value"


def test_aws_extract_secret_invalid_raises() -> None:
    """_extract_secret raises LifecycleError for empty response (line 162)."""
    adapter = AWSSecretManagerAdapter(AWSSecretManagerSettings(region="us-east-1"))
    with pytest.raises(LifecycleError, match="aws-secret-invalid-response"):
        adapter._extract_secret({})


def test_aws_is_not_found_via_message_string() -> None:
    """_is_not_found returns True when exc.args[0] contains ResourceNotFound (lines 168-170)."""
    exc = Exception("ResourceNotFound: the secret does not exist")
    adapter = AWSSecretManagerAdapter(AWSSecretManagerSettings(region="us-east-1"))
    assert adapter._is_not_found(exc) is True


def test_aws_is_not_found_returns_false_for_other_exceptions() -> None:
    """_is_not_found returns False when args[0] is non-string (line 171)."""
    adapter = AWSSecretManagerAdapter(AWSSecretManagerSettings(region="us-east-1"))
    assert (
        adapter._is_not_found(Exception(404)) is False
    )  # int arg → not a string → line 171


@pytest.mark.asyncio
async def test_aws_health_no_healthcheck_secret_returns_true() -> None:
    """health() returns True immediately when healthcheck_secret is not set (line 102)."""
    client = _FakeAWSSecretsClient({})
    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1"),
        client=client,
    )
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_aws_init_with_client_factory() -> None:
    """init() uses client_factory when provided (lines 74-75)."""
    client = _FakeAWSSecretsClient({"K": "v"})

    async def factory() -> _FakeAWSSecretsClient:
        return client

    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1"),
        client_factory=factory,
    )
    await adapter.init()
    assert adapter._client is client


@pytest.mark.asyncio
async def test_aws_get_cached_returns_none_on_expiry(monkeypatch) -> None:
    """_get_cached returns None and evicts entry when TTL has expired (lines 181-182)."""
    import time

    client = _FakeAWSSecretsClient({"KEY": "v"})
    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1", cache_ttl_seconds=1),
        client=client,
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    key = adapter._cache_key("KEY", None)
    adapter._cache[key] = ("v", time.monotonic() - 1)  # already expired
    result = await adapter._get_cached("KEY", None)
    assert result is None
    assert key not in adapter._cache


@pytest.mark.asyncio
async def test_aws_set_cached_skips_when_ttl_zero() -> None:
    """_set_cached returns early when cache_ttl_seconds == 0 (line 189)."""
    client = _FakeAWSSecretsClient({"KEY": "v"})
    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(region="us-east-1", cache_ttl_seconds=0),
        client=client,
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    assert adapter._cache == {}  # nothing was cached


@pytest.mark.asyncio
async def test_aws_init_via_aioboto3(monkeypatch) -> None:
    """init() creates client via aioboto3.Session when no factory/client (lines 73-97)."""
    import sys

    client = _FakeAWSSecretsClient({"K": "v"})
    created_kwargs: list[dict] = []

    class FakeClientCM:
        async def __aenter__(self) -> _FakeAWSSecretsClient:
            return client

        async def __aexit__(self, *args: object) -> None:
            pass

    class FakeSession:
        def __init__(self, **kwargs: object) -> None:
            created_kwargs.append(dict(kwargs))

        def client(self, **kwargs: object) -> FakeClientCM:
            return FakeClientCM()

    class FakeAioboto3:
        Session = FakeSession

    monkeypatch.setitem(sys.modules, "aioboto3", FakeAioboto3)  # type: ignore[arg-type]

    adapter = AWSSecretManagerAdapter(
        AWSSecretManagerSettings(
            region="eu-west-1",
            profile_name="dev",
        )
    )
    await adapter.init()
    assert adapter._client is client
    assert created_kwargs[0].get("region_name") == "eu-west-1"
    assert created_kwargs[0].get("profile_name") == "dev"
