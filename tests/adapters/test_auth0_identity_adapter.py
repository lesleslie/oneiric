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
