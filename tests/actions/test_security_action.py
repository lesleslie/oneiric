from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from oneiric.actions.security import (
    SecuritySecureAction,
    SecuritySecureSettings,
    SecuritySignatureAction,
    SecuritySignatureSettings,
)
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_security_signature_action_hex() -> None:
    action = SecuritySignatureAction(
        SecuritySignatureSettings(
            secret="demo", include_timestamp=False, algorithm="sha256", encoding="hex"
        )
    )

    result = await action.execute({"message": "hello world"})

    expected = hmac.new(b"demo", b"hello world", hashlib.sha256).hexdigest()
    assert result["signature"] == expected
    assert result["encoding"] == "hex"
    assert "timestamp" not in result


@pytest.mark.asyncio
async def test_security_signature_action_base64_payload_override() -> None:
    action = SecuritySignatureAction(SecuritySignatureSettings(include_timestamp=False))

    payload = {"user": "ops", "scope": ["deploy"]}
    result = await action.execute(
        {
            "data": payload,
            "secret": "override",
            "algorithm": "sha512",
            "encoding": "base64",
        }
    )

    digest = hmac.new(
        b"override",
        b'{"scope":["deploy"],"user":"ops"}',
        hashlib.sha512,
    ).digest()
    assert result["signature"] == base64.b64encode(digest).decode("ascii")
    assert result["header"] == "X-Oneiric-Signature"


@pytest.mark.asyncio
async def test_security_signature_requires_secret() -> None:
    action = SecuritySignatureAction(SecuritySignatureSettings(secret=None))

    with pytest.raises(LifecycleError):
        await action.execute({"message": "hello"})


@pytest.mark.asyncio
async def test_security_secure_action_generates_token() -> None:
    action = SecuritySecureAction(SecuritySecureSettings(token_length=8))

    result = await action.execute({"mode": "token"})

    assert result["status"] == "token"
    assert isinstance(result["token"], str)
    assert result["length"] == 8


@pytest.mark.asyncio
async def test_security_secure_action_hash_and_verify_password() -> None:
    action = SecuritySecureAction()

    hashed = await action.execute({"mode": "password-hash", "password": "secret"})
    assert hashed["status"] == "password-hash"

    verified = await action.execute(
        {
            "mode": "password-verify",
            "password": "secret",
            "hash": hashed["hash"],
            "salt": hashed["salt"],
            "iterations": hashed["iterations"],
        }
    )

    assert verified["valid"] is True
