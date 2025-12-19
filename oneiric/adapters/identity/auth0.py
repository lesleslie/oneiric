"""Auth0-backed identity adapter."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from typing import Any

import httpx
import jwt
from pydantic import BaseModel, Field

from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class Auth0IdentitySettings(BaseModel):
    """Settings for the Auth0 identity adapter."""

    domain: str = Field(description="Auth0 tenant domain, e.g., example.us.auth0.com")
    audience: str = Field(description="Expected audience claim for issued tokens.")
    algorithms: Sequence[str] = Field(default=("RS256",), min_length=1)
    jwks_url: str | None = Field(
        default=None,
        description="Override JWKS URL; defaults to https://<domain>/.well-known/jwks.json",
    )
    http_timeout: float = Field(default=5.0, gt=0)
    cache_ttl_seconds: int = Field(default=300, ge=30)


class Auth0IdentityAdapter(HTTPXClientMixin):
    """Validates Auth0-issued JWTs using cached JWKS data."""

    metadata = AdapterMetadata(
        category="identity",
        provider="auth0",
        factory="oneiric.adapters.identity.auth0:Auth0IdentityAdapter",
        capabilities=["jwt", "jwks", "userinfo"],
        stack_level=40,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="Security",
        requires_secrets=True,
        settings_model=Auth0IdentitySettings,
    )

    def __init__(
        self,
        settings: Auth0IdentitySettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=http_client)
        self._settings = settings
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at: float | None = None
        self._jwks_lock = asyncio.Lock()
        self._logger = get_logger("adapter.identity.auth0").bind(
            domain="adapter",
            key="identity",
            provider="auth0",
        )

    async def init(self) -> None:
        if self._client is None:
            self._init_client(
                lambda: httpx.AsyncClient(timeout=self._settings.http_timeout)
            )
        self._logger.info("adapter-init", adapter="auth0-identity")

    async def health(self) -> bool:
        try:
            await self._fetch_jwks(force=True)
            return True
        except Exception as exc:  # pragma: no cover - network failure
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        await self._cleanup_client()
        self._jwks = None
        self._logger.info("adapter-cleanup-complete", adapter="auth0-identity")

    async def verify_token(self, token: str) -> dict[str, Any]:
        jwks = await self._fetch_jwks()
        header = jwt.get_unverified_header(token)
        if not (kid := header.get("kid")):
            raise LifecycleError("token-missing-kid")
        key_data = self._match_key(jwks, kid)
        if not key_data:
            raise LifecycleError("token-key-not-found")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        issuer = f"https://{self._settings.domain}/"
        return jwt.decode(
            token,
            key=public_key,
            audience=self._settings.audience,
            algorithms=list(self._settings.algorithms),
            issuer=issuer,
        )

    async def _fetch_jwks(self, *, force: bool = False) -> dict[str, Any]:
        async with self._jwks_lock:
            should_refresh = force
            if self._jwks and self._jwks_loaded_at:
                age = time.monotonic() - self._jwks_loaded_at
                if age > self._settings.cache_ttl_seconds:
                    should_refresh = True
                else:
                    should_refresh = False
            if not should_refresh and self._jwks:
                return self._jwks
            client = self._ensure_client("auth0-http-client-not-initialized")
            url = (
                self._settings.jwks_url
                or f"https://{self._settings.domain}/.well-known/jwks.json"
            )
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if "keys" not in data:
                raise LifecycleError("jwks-missing-keys")
            self._jwks = data
            self._jwks_loaded_at = time.monotonic()
            return data

    def _match_key(self, jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
        for entry in jwks.get("keys", []):
            if entry.get("kid") == kid:
                return entry
        return None
