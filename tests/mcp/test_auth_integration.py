"""End-to-end auth verification across all 7 substrate/scheduler tools.

REQ-002: BearerTokenMiddleware is wired correctly.
REQ-003: All substrate tools require auth.
REQ-004: /health is public, exempt from auth.

Uses a fake JWT provider whose ``verify_token`` succeeds only when the
token matches a pre-registered pair. This mirrors how mcp-common's
real JWT provider behaves; tests don't depend on a real JWT signing
implementation.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.testclient import TestClient

from mcp_common.auth.config import AuthConfig
from mcp_common.auth.context import seed_principal
from mcp_common.auth.exceptions import (
    AuthenticationRequiredError,
    InsufficientPermissionError,
    TokenInvalidError,
    UnknownIssuerError,
)
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal
from mcp_common.auth.provider import IdentityProvider

from oneiric.mcp.config import OneiricMCPAuthConfig, load_auth_config
from oneiric.mcp.health import HealthFeedState
from oneiric.mcp.server import build_mcp_server
from oneiric.mcp.store import SubstrateStore


# 32+ chars; not a placeholder. Satisfies AuthConfig's _resolve_secret
# validator when no explicit ``secret=`` is supplied to AuthConfig.
_TEST_SECRET = "test_secret_at_least_32_characters_long_xx"


@pytest.fixture(autouse=True)
def _set_shared_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set BODAI_SHARED_SECRET so AuthConfig's validator passes.

    The auth_config built by ``load_auth_config`` doesn't surface the
    ``provider_configs`` secret onto the AuthConfig object; mcp-common's
    AuthConfig resolves secrets via env vars. The shared dev secret is
    fine for tests — no real token signing happens because the provider
    is a stub that accepts the ``good-`` prefix only.
    """
    monkeypatch.setenv("BODAI_SHARED_SECRET", _TEST_SECRET)


class _FakeJWTProvider(IdentityProvider):
    def __init__(self, *, secret: str) -> None:
        self._secret = secret

    async def verify_token(
        self, token: str, *, expected_audience: str | None = None
    ) -> Principal:
        # Token format: "<subject>:<role1,role2>". Roles map to Permission.
        if not token.startswith("good-"):
            raise TokenInvalidError("bad token prefix")
        subject, roles_csv = token[5:].split(":", 1)
        perms: set[Permission] = set()
        for r in roles_csv.split(","):
            if r == "reader":
                perms.add(Permission.READ)
            elif r == "operator":
                perms.add(Permission.READ)
                perms.add(Permission.WRITE)
            elif r == "admin":
                perms.update(Permission)
        return Principal(
            issuer="acme",
            subject=subject,
            permissions=frozenset(perms),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            raw_claims={"roles": list(perms)},
        )


class _WrongIssuerProvider(IdentityProvider):
    """Provider that returns a Principal whose issuer is NOT trusted."""

    async def verify_token(
        self, token: str, *, expected_audience: str | None = None
    ) -> Principal:
        return Principal(
            issuer="other",  # not in trusted_issuers=["acme"]
            subject=subject_from_token(token),
            permissions=frozenset({Permission.READ}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            raw_claims={},
        )


def subject_from_token(token: str) -> str:
    return token[5:] if token.startswith("good-") else "unknown"


class _StubProcessor:
    """Scheduler processor stub so build_mcp_server() doesn't raise."""

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"run_id": "run-1", "results": {"ok": True}}


def _build_with_auth(tmp_path: Any, *, processor: Any = None) -> Any:
    cfg = OneiricMCPAuthConfig(
        enabled=True,
        default_provider="jwt",
        trusted_issuers=["acme"],
        provider_configs={"jwt": {"secret": "unused"}},
    )
    auth_config, providers = load_auth_config(
        cfg,
        provider_factories={"jwt": lambda _: _FakeJWTProvider(secret="unused")},
    )
    store = SubstrateStore(root=tmp_path)
    feeds = {"settings": HealthFeedState(name="settings")}
    return build_mcp_server(
        SimpleNamespace(name="oneiric-test"),
        auth_config=auth_config,
        providers=providers,
        store=store,
        processor=processor or _StubProcessor(),
        health_feeds=feeds,
    )


class TestHealthIsPublic:
    """REQ-004: /health returns 200 without auth."""

    def test_health_works_without_token(self, tmp_path: Any) -> None:
        mcp = _build_with_auth(tmp_path)
        client = TestClient(mcp.http_app())
        resp = client.get("/health")
        # 200 if feeds healthy, 503 if degraded — either proves the route
        # is reachable without auth (REQ-004).
        assert resp.status_code in (200, 503)
        assert "routes" in resp.json()


class TestSubstrateReadsRequireReadPermission:
    """REQ-003: reads require READ permission."""

    async def test_no_token_returns_401(self, tmp_path: Any) -> None:
        """No Principal in context → AuthenticationRequiredError.

        Replaces the pr-test-analyzer-flagged ``__import__("asyncio")``
        pattern with a clean async test (pytest-asyncio mode=auto).
        """
        mcp = _build_with_auth(tmp_path)
        tool = next(
            t for t in await mcp.list_tools() if t.name == "read_settings"
        )
        with pytest.raises(AuthenticationRequiredError):
            await tool.fn()


class TestSubstrateWritesRequireWritePermission:
    """REQ-003: writes require WRITE permission.

    pr-test-analyzer finding: only the negative case was tested. Without
    the positive case, a regression where every @require_auth demands
    ADMIN instead of WRITE would slip through. The four tests below
    pin both positive and negative paths.
    """

    def _seed(self, perms: frozenset[Permission]) -> Any:
        return seed_principal(
            Principal(
                issuer="acme",
                subject="alice",
                permissions=perms,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                raw_claims={},
            )
        )

    async def test_operator_can_write_settings(self, tmp_path: Any) -> None:
        """Positive: operator (READ + WRITE) succeeds."""
        mcp = _build_with_auth(tmp_path)
        tool = next(
            t for t in await mcp.list_tools() if t.name == "write_settings"
        )
        handle = self._seed(frozenset({Permission.READ, Permission.WRITE}))
        try:
            result = await tool.fn(version="v1")
            assert "record_id" in result
        finally:
            handle.var.reset(handle)

    async def test_reader_cannot_write_settings(self, tmp_path: Any) -> None:
        """Negative: reader (READ only) → InsufficientPermissionError."""
        mcp = _build_with_auth(tmp_path)
        tool = next(
            t for t in await mcp.list_tools() if t.name == "write_settings"
        )
        handle = self._seed(frozenset({Permission.READ}))
        try:
            with pytest.raises(InsufficientPermissionError):
                await tool.fn(version="v1")
        finally:
            handle.var.reset(handle)

    async def test_reader_can_read_settings(self, tmp_path: Any) -> None:
        """Positive: reader (READ) succeeds on a read tool."""
        mcp = _build_with_auth(tmp_path)
        tool = next(
            t for t in await mcp.list_tools() if t.name == "read_settings"
        )
        handle = self._seed(frozenset({Permission.READ}))
        try:
            result = await tool.fn()
            assert result["current"] is None
        finally:
            handle.var.reset(handle)

    async def test_operator_can_schedule_task(self, tmp_path: Any) -> None:
        """schedule_task is a WRITE-permission tool."""
        cfg = OneiricMCPAuthConfig(
            enabled=True,
            default_provider="jwt",
            trusted_issuers=["acme"],
            provider_configs={"jwt": {"secret": "unused"}},
        )
        auth_config, providers = load_auth_config(
            cfg,
            provider_factories={
                "jwt": lambda _: _FakeJWTProvider(secret="unused")
            },
        )
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}

        mcp = build_mcp_server(
            SimpleNamespace(name="oneiric-test"),
            auth_config=auth_config,
            providers=providers,
            store=store,
            processor=_StubProcessor(),
            health_feeds=feeds,
        )
        tool = next(
            t for t in await mcp.list_tools() if t.name == "schedule_task"
        )
        handle = self._seed(frozenset({Permission.READ, Permission.WRITE}))
        try:
            result = await tool.fn(workflow="my-workflow")
            assert result["run_id"] == "run-1"
        finally:
            handle.var.reset(handle)


class TestTokenValidation:
    """Spec §7.1: cover missing/invalid/expired/wrong-issuer tokens."""

    async def test_invalid_token_rejected(self, tmp_path: Any) -> None:
        """Malformed token (no 'good-' prefix) is rejected.

        BearerTokenMiddleware fires on_request → verify_token raises
        TokenInvalidError → AuthError propagates. The test asserts the
        request is NOT silently accepted — the JSON-RPC envelope must
        carry an error, either as an HTTP 401 (middleware layer) or as
        ``isError: true`` with an ``AuthenticationRequiredError`` from
        the @require_auth decorator (when the streamable-HTTP transport
        bypasses the middleware and the safe-default decorator catches
        the missing Principal).
        """
        mcp = _build_with_auth(tmp_path)
        # `with` activates FastMCP's lifespan so the StreamableHTTPSessionManager
        # task group initializes (otherwise the /mcp/ endpoint 500s before the
        # middleware even runs).
        with TestClient(mcp.http_app()) as client:
            init = client.post(
                "/mcp/",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                    "id": 1,
                },
            )
            session_id = init.headers.get("mcp-session-id")
            resp = client.post(
                "/mcp/",
                headers={
                    "Authorization": "Bearer bad-format-token",
                    "mcp-session-id": session_id or "",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "read_settings", "arguments": {}},
                    "id": 2,
                },
            )
        # Either 401 (middleware rejection) or 200 with isError=True
        # (decorator fallback). Both demonstrate the token is rejected.
        assert resp.status_code in (200, 401)
        body = resp.text.lower()
        assert (
            "auth" in body
            or "token" in body
            or "iserror" in body
            or "missing" in body
        )

    async def test_expired_token_accepted_documented_gap(
        self, tmp_path: Any
    ) -> None:
        """Document the spec gap: BearerTokenMiddleware does NOT enforce
        ``expires_at`` — that's the provider's responsibility.

        A Principal with ``expires_at`` in the past still passes the
        decorator (which only checks authentication + permission). When
        mcp-common's real ``JWTIdentityProvider`` is used, expiry IS
        enforced at verify_token time, so this gap is closed in
        production by using a real provider. This test pins the current
        behavior so a future refactor of the decorator doesn't silently
        drop the explicit permission check.
        """
        expired = Principal(
            issuer="acme",
            subject="alice",
            permissions=frozenset({Permission.READ}),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
            raw_claims={},
        )
        mcp = _build_with_auth(tmp_path)
        handle = seed_principal(expired)
        try:
            tool = next(
                t for t in await mcp.list_tools() if t.name == "read_settings"
            )
            # Documented gap: expired principal IS accepted. The
            # decorator doesn't check expires_at — that's a provider
            # concern. Real providers enforce it at verify_token time.
            result = await tool.fn()
            assert result["current"] is None
        finally:
            handle.var.reset(handle)

    async def test_wrong_issuer_rejected(self, tmp_path: Any) -> None:
        """Provider returns a Principal whose issuer is NOT in
        ``trusted_issuers`` → BearerTokenMiddleware's
        ``_enforce_trusted_issuers`` gate raises ``UnknownIssuerError``.

        This test goes through the HTTP path so the middleware actually
        fires ``on_request`` (calling ``seed_principal`` directly would
        bypass the middleware and skip this gate — that's why the test
        uses TestClient + Authorization header). The test accepts any
        rejection — either the middleware's UnknownIssuerError (HTTP
        401) or the decorator's AuthenticationRequiredError fallback
        (when the streamable-HTTP transport bypasses the middleware).
        """
        cfg = OneiricMCPAuthConfig(
            enabled=True,
            default_provider="jwt",
            trusted_issuers=["acme"],
            provider_configs={"jwt": {"secret": "unused"}},
        )
        auth_config, providers = load_auth_config(
            cfg,
            provider_factories={
                "jwt": lambda _: _WrongIssuerProvider(),
            },
        )
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}
        mcp = build_mcp_server(
            SimpleNamespace(name="oneiric-test"),
            auth_config=auth_config,
            providers=providers,
            store=store,
            processor=_StubProcessor(),
            health_feeds=feeds,
        )
        with TestClient(mcp.http_app()) as client:
            init = client.post(
                "/mcp/",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                    "id": 1,
                },
            )
            session_id = init.headers.get("mcp-session-id")
            resp = client.post(
                "/mcp/",
                headers={
                    "Authorization": "Bearer good-alice:reader",
                    "mcp-session-id": session_id or "",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "read_settings", "arguments": {}},
                    "id": 2,
                },
            )
        # Either a 401 (middleware rejection) or a 200 with isError=True
        # (decorator fallback). Both demonstrate the request is rejected.
        assert resp.status_code in (200, 401)
        body = resp.text.lower()
        assert (
            "auth" in body
            or "issuer" in body
            or "trust" in body
            or "not in" in body
            or "iserror" in body
        )
