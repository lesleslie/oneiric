from __future__ import annotations

import base64

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from oneiric.adapters.identity.auth0 import Auth0IdentityAdapter, Auth0IdentitySettings


def _build_jwk(public_pem: bytes, kid: str) -> dict[str, str]:
    public_key = serialization.load_pem_public_key(public_pem)
    numbers = public_key.public_numbers()
    n = base64.urlsafe_b64encode(
        numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    ).rstrip(b"=")
    e = base64.urlsafe_b64encode(
        numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    ).rstrip(b"=")
    return {
        "kty": "RSA",
        "alg": "RS256",
        "kid": kid,
        "use": "sig",
        "n": n.decode("ascii"),
        "e": e.decode("ascii"),
    }


class _DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:  # pragma: no cover - simple stub
        return None


class _DummyHTTPClient:
    def __init__(self, response: _DummyResponse) -> None:
        self._response = response
        self.calls = 0
        self.closed = False

    async def get(self, url: str) -> _DummyResponse:
        self.calls += 1
        return self._response

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_auth0_adapter_verifies_token_with_cached_jwks() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = _build_jwk(public_pem, "demo-key")
    client = _DummyHTTPClient(_DummyResponse({"keys": [jwk]}))
    settings = Auth0IdentitySettings(
        domain="tenant.us.auth0.com", audience="api://default"
    )
    adapter = Auth0IdentityAdapter(settings, http_client=client)
    await adapter.init()
    token = jwt.encode(
        {
            "sub": "user-1",
            "aud": "api://default",
            "iss": "https://tenant.us.auth0.com/",
        },
        key=private_key,
        algorithm="RS256",
        headers={"kid": "demo-key"},
    )
    claims = await adapter.verify_token(token)
    assert claims["sub"] == "user-1"
    await adapter.verify_token(token)
    assert client.calls == 1  # cached JWKS
    await adapter.cleanup()
    assert client.closed is False  # client is external; adapter should not close it


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_creates_client_when_none() -> None:
    """init() calls _init_client when http_client not provided (line 65)."""
    settings = Auth0IdentitySettings(domain="t.auth0.com", audience="aud")
    adapter = Auth0IdentityAdapter(settings)
    await adapter.init()
    assert adapter._client is not None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_health_returns_true_on_valid_jwks() -> None:
    """health() fetches JWKS with force=True and returns True (lines 71-73)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = _build_jwk(public_pem, "health-key")
    client = _DummyHTTPClient(_DummyResponse({"keys": [jwk]}))
    settings = Auth0IdentitySettings(domain="t.auth0.com", audience="aud")
    adapter = Auth0IdentityAdapter(settings, http_client=client)
    await adapter.init()
    result = await adapter.health()
    assert result is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_verify_token_raises_on_missing_kid() -> None:
    """verify_token raises LifecycleError when JWT has no kid header (line 87)."""
    from oneiric.core.lifecycle import LifecycleError

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = _build_jwk(public_pem, "some-key")
    client = _DummyHTTPClient(_DummyResponse({"keys": [jwk]}))
    settings = Auth0IdentitySettings(domain="t.auth0.com", audience="aud")
    adapter = Auth0IdentityAdapter(settings, http_client=client)
    await adapter.init()
    token = jwt.encode(
        {"sub": "u", "aud": "aud", "iss": "https://t.auth0.com/"},
        key=private_key,
        algorithm="RS256",
        # no kid header
    )
    with pytest.raises(LifecycleError, match="token-missing-kid"):
        await adapter.verify_token(token)
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_verify_token_raises_when_key_not_found() -> None:
    """verify_token raises LifecycleError when kid doesn't match any JWKS key (line 90)."""
    from oneiric.core.lifecycle import LifecycleError

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = _build_jwk(public_pem, "real-key")
    client = _DummyHTTPClient(_DummyResponse({"keys": [jwk]}))
    settings = Auth0IdentitySettings(domain="t.auth0.com", audience="aud")
    adapter = Auth0IdentityAdapter(settings, http_client=client)
    await adapter.init()
    token = jwt.encode(
        {"sub": "u", "aud": "aud", "iss": "https://t.auth0.com/"},
        key=private_key,
        algorithm="RS256",
        headers={"kid": "wrong-key"},  # kid not in JWKS
    )
    with pytest.raises(LifecycleError, match="token-key-not-found"):
        await adapter.verify_token(token)
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_fetch_jwks_refreshes_on_stale_cache() -> None:
    """_fetch_jwks sets should_refresh=True when cache TTL exceeded (line 107)."""
    import time

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = _build_jwk(public_pem, "ttl-key")
    client = _DummyHTTPClient(_DummyResponse({"keys": [jwk]}))
    settings = Auth0IdentitySettings(
        domain="t.auth0.com", audience="aud", cache_ttl_seconds=30
    )
    adapter = Auth0IdentityAdapter(settings, http_client=client)
    await adapter.init()
    await adapter._fetch_jwks()
    assert client.calls == 1
    # Simulate cache expiry by backdating the loaded timestamp
    adapter._jwks_loaded_at = time.monotonic() - 60
    await adapter._fetch_jwks()
    assert client.calls == 2  # re-fetched due to stale cache
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_fetch_jwks_raises_on_missing_keys_field() -> None:
    """_fetch_jwks raises LifecycleError when response has no 'keys' field (line 121)."""
    from oneiric.core.lifecycle import LifecycleError

    client = _DummyHTTPClient(_DummyResponse({"not_keys": []}))
    settings = Auth0IdentitySettings(domain="t.auth0.com", audience="aud")
    adapter = Auth0IdentityAdapter(settings, http_client=client)
    await adapter.init()
    with pytest.raises(LifecycleError, match="jwks-missing-keys"):
        await adapter._fetch_jwks()
    await adapter.cleanup()


def test_match_key_returns_none_when_no_match() -> None:
    """_match_key returns None when no entry matches the kid (line 130)."""
    settings = Auth0IdentitySettings(domain="t.auth0.com", audience="aud")
    adapter = Auth0IdentityAdapter(settings)
    jwks = {"keys": [{"kid": "key-a", "kty": "RSA"}, {"kid": "key-b", "kty": "RSA"}]}
    result = adapter._match_key(jwks, "key-c")
    assert result is None
