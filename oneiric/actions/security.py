"""Security, signature, and token helper actions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class SecuritySignatureSettings(BaseModel):
    """Settings controlling signature generation."""

    algorithm: Literal["sha256", "sha512", "blake2b"] = Field(
        default="sha256",
        description="Digest algorithm used when hashing the payload.",
    )
    encoding: Literal["hex", "base64"] = Field(
        default="hex",
        description="Encoding applied to the digest output.",
    )
    secret: str | None = Field(
        default=None,
        description="Default secret used when payload omits 'secret'.",
    )
    header_name: str = Field(
        default="X-Oneiric-Signature",
        description="Default header name that downstream services expect.",
    )
    include_timestamp: bool = Field(
        default=True,
        description="Include an ISO timestamp alongside the signature result.",
    )


class SecuritySignatureAction:
    """Action kit that generates deterministic HMAC signatures."""

    metadata = ActionMetadata(
        key="security.signature",
        provider="builtin-security-signature",
        factory="oneiric.actions.security:SecuritySignatureAction",
        description="Security helper generating HMAC signatures for outbound requests",
        domains=["service", "task", "workflow"],
        capabilities=["signature", "hmac", "validation"],
        stack_level=40,
        priority=400,
        source=CandidateSource.LOCAL_PKG,
        owner="Security",
        requires_secrets=True,
        side_effect_free=True,
        settings_model=SecuritySignatureSettings,
    )

    _ALGORITHMS = {
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
        "blake2b": hashlib.blake2b,
    }

    def __init__(self, settings: SecuritySignatureSettings | None = None) -> None:
        self._settings = settings or SecuritySignatureSettings()
        self._logger = get_logger("action.security.signature")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        secret = payload.get("secret") or self._settings.secret
        if not secret:
            raise LifecycleError("security-signature-secret-required")
        algorithm = (payload.get("algorithm") or self._settings.algorithm).lower()
        if algorithm not in self._ALGORITHMS:
            raise LifecycleError("security-signature-algorithm-invalid")
        encoding = (payload.get("encoding") or self._settings.encoding).lower()
        if encoding not in {"hex", "base64"}:
            raise LifecycleError("security-signature-encoding-invalid")
        include_timestamp = payload.get("include_timestamp")
        if include_timestamp is None:
            include_timestamp = self._settings.include_timestamp
        message = self._normalize_message(payload)
        digest = hmac.new(secret.encode("utf-8"), message, self._ALGORITHMS[algorithm])
        if encoding == "hex":
            signature = digest.hexdigest()
        else:
            signature = base64.b64encode(digest.digest()).decode("ascii")
        result = {
            "status": "signed",
            "algorithm": algorithm,
            "encoding": encoding,
            "signature": signature,
            "header": payload.get("header") or self._settings.header_name,
        }
        if include_timestamp:
            result["timestamp"] = datetime.now(UTC).isoformat()
        self._logger.info(
            "security-action-signed", algorithm=algorithm, encoding=encoding
        )
        return result

    def _normalize_message(self, payload: dict) -> bytes:
        if "message" in payload and payload["message"] is not None:
            return self._to_bytes(payload["message"])
        if "body" in payload and payload["body"] is not None:
            return self._to_bytes(payload["body"])
        if "data" in payload and payload["data"] is not None:
            return self._to_bytes(payload["data"])
        raise LifecycleError("security-signature-message-required")

    def _to_bytes(self, value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        except TypeError as exc:  # pragma: no cover - serialization edge
            raise LifecycleError("security-signature-message-invalid") from exc


class SecuritySecureSettings(BaseModel):
    """Settings controlling secure token/password helpers."""

    token_length: int = Field(
        default=32, description="Default length for generated tokens."
    )
    password_iterations: int = Field(
        default=100_000,
        description="PBKDF2 iterations applied when hashing passwords.",
    )
    include_symbols: bool = Field(
        default=True,
        description="Include symbols when generating passwords.",
    )


class SecuritySecureAction:
    """Action kit that generates tokens and secures passwords."""

    metadata = ActionMetadata(
        key="security.secure",
        provider="builtin-security-secure",
        factory="oneiric.actions.security:SecuritySecureAction",
        description="Generates secure tokens/password hashes and verifies credentials",
        domains=["service", "task", "workflow"],
        capabilities=["secure", "token", "password"],
        stack_level=40,
        priority=390,
        source=CandidateSource.LOCAL_PKG,
        owner="Security",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=SecuritySecureSettings,
    )

    def __init__(self, settings: SecuritySecureSettings | None = None) -> None:
        self._settings = settings or SecuritySecureSettings()
        self._logger = get_logger("action.security.secure")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        mode = (payload.get("mode") or "token").lower()
        if mode == "token":
            length = int(payload.get("length") or self._settings.token_length)
            token = secrets.token_urlsafe(length)
            self._logger.info("security-action-token", length=length)
            return {"status": "token", "token": token, "length": length}
        if mode == "password-hash":
            return self._hash_password(payload)
        if mode == "password-verify":
            return self._verify_password(payload)
        if mode == "compare":
            return self._compare(payload)
        raise LifecycleError("security-secure-mode-invalid")

    def _hash_password(self, payload: dict) -> dict:
        password = payload.get("password")
        if not isinstance(password, str) or not password:
            raise LifecycleError("security-secure-password-required")
        iterations = int(
            payload.get("iterations") or self._settings.password_iterations
        )
        salt = payload.get("salt")
        if not salt:
            salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        self._logger.info("security-action-password-hash", iterations=iterations)
        return {
            "status": "password-hash",
            "hash": digest,
            "salt": salt,
            "iterations": iterations,
        }

    def _verify_password(self, payload: dict) -> dict:
        password = payload.get("password")
        password_hash = payload.get("hash")
        salt = payload.get("salt")
        iterations = int(
            payload.get("iterations") or self._settings.password_iterations
        )
        if not all(
            isinstance(value, str) and value
            for value in (password, password_hash, salt)
        ):
            raise LifecycleError("security-secure-verification-input-invalid")
        computed = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        valid = hmac.compare_digest(computed, password_hash)
        self._logger.info("security-action-password-verify", valid=valid)
        return {
            "status": "password-verify",
            "valid": valid,
        }

    def _compare(self, payload: dict) -> dict:
        first = payload.get("a")
        second = payload.get("b")
        if not isinstance(first, str) or not isinstance(second, str):
            raise LifecycleError("security-secure-compare-invalid")
        equal = hmac.compare_digest(first, second)
        self._logger.info("security-action-compare", equal=equal)
        return {
            "status": "compare",
            "equal": equal,
        }
