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

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from mcp_common.auth.context import seed_principal
from mcp_common.auth.exceptions import (
    InsufficientPermissionError,
    TokenInvalidError,
)
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal
from mcp_common.auth.provider import IdentityProvider
from starlette.testclient import TestClient

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

    def test_no_authorization_header_returns_auth_error(
        self, tmp_path: Any
    ) -> None:
        """REQ-003 transport-boundary proof: an unauthenticated tools/call
        over HTTP MUST be rejected before the tool function executes.

        With mcp-common's ``include={'authorization'}`` fix in place,
        ``BearerTokenMiddleware`` actually fires on HTTP. When no
        Authorization header is present, the middleware passes through
        (per its design — anonymous requests are the decorator's
        responsibility). The ``@require_auth`` decorator then raises
        ``AuthenticationRequiredError``, which FastMCP's streamable-HTTP
        transport wraps as ``ToolError`` and surfaces as a JSON-RPC
        ``isError: true`` envelope.

        Important: FastMCP streamable-HTTP always returns HTTP 200 (the
        JSON-RPC error lives in the response body). The middleware-layer
        rejection signal is therefore the body content — the decorator's
        safe-default ``Authentication required for <tool>`` message — NOT
        an HTTP 401 status code. A future FastMCP change that surfaces
        AuthError as a real 401 would surface as a status-code test
        failure, which is the regression signal we want.
        """
        mcp = _build_with_auth(tmp_path)
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
            session_id = init.headers.get("mcp-session-id", "")
            resp = client.post(
                "/mcp/",
                headers={
                    "mcp-session-id": session_id,
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
        # FastMCP streamable-HTTP returns 200; the rejection is in the body.
        assert resp.status_code == 200
        body = resp.text
        # Decorator's safe-default message proves @require_auth fired.
        # NOT a middleware AuthError (those carry their own specific
        # message; see test_invalid_token_rejected below).
        assert "Authentication required for read_settings" in body
        assert '"isError":true' in body


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
        """Malformed token (no 'good-' prefix) is rejected by
        ``BearerTokenMiddleware``, NOT by the per-tool decorator.

        This is the REQ-002 / REQ-003 transport-boundary proof: with
        mcp-common's ``include={'authorization'}`` fix in place, the
        middleware actually fires on HTTP requests. ``verify_token``
        raises ``TokenInvalidError`` and the middleware re-raises; FastMCP
        wraps it as a ``ToolError`` that surfaces in the JSON-RPC body
        with ``isError: true``.

        Crucially, the body MUST contain the middleware's specific error
        message (``"bad token prefix"`` — the ``str(exc)`` from
        ``TokenInvalidError``), NOT the decorator's safe-default message
        (``"Authentication required for <tool>"``). If we ever see the
        decorator message in this test, the middleware has been
        bypassed (e.g. a future FastMCP change that strips
        ``on_request``) and REQ-003 enforcement has silently degraded
        to the decorator fallback — which means the transport boundary
        is no longer guarded.

        Note: FastMCP streamable-HTTP returns HTTP 200 even when the
        middleware rejects; the rejection lives in the JSON-RPC body.
        A future FastMCP change that surfaces AuthError as a real 401
        would surface here as a status-code assertion failure.
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
        # FastMCP streamable-HTTP returns 200; the rejection is in the body.
        assert resp.status_code == 200
        body = resp.text
        # Middleware-layer signal: the TokenInvalidError message, NOT
        # the decorator's "Authentication required for ..." fallback.
        assert "bad token prefix" in body, (
            f"expected TokenInvalidError message in body, got: {body!r}"
        )
        assert "Authentication required for read_settings" not in body, (
            f"middleware should have fired, but decorator fallback ran: {body!r}"
        )
        assert '"isError":true' in body

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
        ``trusted_issuers`` → ``BearerTokenMiddleware``'s
        ``_enforce_trusted_issuers`` gate raises ``UnknownIssuerError``.

        This test goes through the HTTP path so the middleware actually
        fires ``on_request`` (calling ``seed_principal`` directly would
        bypass the middleware and skip this gate — that's why the test
        uses TestClient + Authorization header).

        The body MUST carry the ``UnknownIssuerError`` message —
        ``"Issuer 'other' not in auth_config.trusted_issuers: ['acme']"``
        — NOT the decorator's ``Authentication required for <tool>``
        fallback. If we see the decorator message, the
        ``_enforce_trusted_issuers`` gate has been bypassed (e.g. a
        refactor that drops it) and any signature-valid token from an
        untrusted issuer would slip through.

        Note: FastMCP streamable-HTTP returns HTTP 200 even when the
        middleware rejects; the rejection lives in the JSON-RPC body.
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
        assert resp.status_code == 200
        body = resp.text
        # Middleware-layer signal: UnknownIssuerError carries this exact
        # message format. NOT the decorator's "Authentication required" string.
        assert "Issuer 'other' not in auth_config.trusted_issuers" in body, (
            f"expected UnknownIssuerError message in body, got: {body!r}"
        )
        assert "Authentication required for read_settings" not in body, (
            f"middleware should have fired, but decorator fallback ran: {body!r}"
        )
        assert '"isError":true' in body

    def test_tools_list_without_auth_rejected_by_middleware(
        self, tmp_path: Any
    ) -> None:
        """REQ-003 transport-boundary proof for ``tools/list``.

        An unauthenticated ``tools/list`` request carrying a bad bearer
        token MUST be rejected by ``BearerTokenMiddleware`` at the
        transport boundary. FastMCP's streamable-HTTP transport surfaces
        the resulting ``AuthError`` as a JSON-RPC ``error`` envelope
        (note: ``error``, not ``isError: true`` — tools/list is a
        session-level method, not a tool invocation).

        If the middleware stops firing for tools/list, an unauthenticated
        caller would receive the full tool inventory — exposing the
        tool surface to anonymous probes. This test would surface that
        regression as either (a) the body contains the full ``tools``
        array, or (b) the JSON-RPC ``error`` envelope is absent.

        Known gap surfaced by this test: ``tools/list`` WITHOUT an
        Authorization header is NOT rejected — ``BearerTokenMiddleware``
        passes through (per design; anonymous is the decorator's
        concern) and tools/list has no ``@require_auth`` decorator
        (listing is not a tool call). That gap is documented in
        Task 16 / T17 follow-up.
        """
        mcp = _build_with_auth(tmp_path)
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
            session_id = init.headers.get("mcp-session-id", "")
            resp = client.post(
                "/mcp/",
                headers={
                    "Authorization": "Bearer bad-format-token",
                    "mcp-session-id": session_id,
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/list",
                    "id": 2,
                },
            )
        # FastMCP streamable-HTTP returns 200; rejection is in the body.
        assert resp.status_code == 200
        body = resp.text
        # TokenInvalidError message — same as test_invalid_token_rejected.
        assert "bad token prefix" in body, (
            f"expected TokenInvalidError message in body, got: {body!r}"
        )
        # The tool inventory MUST NOT be present (the middleware
        # rejected before tools/list could execute).
        assert '"tools"' not in body, (
            f"middleware should have rejected before tools/list executed; "
            f"tool inventory leaked: {body[:500]!r}"
        )
        # FastMCP surfaces middleware errors on session-level methods
        # as a JSON-RPC ``error`` envelope (not ``isError: true``).
        assert '"error"' in body

    def test_tools_list_with_valid_token_succeeds(self, tmp_path: Any) -> None:
        """Positive proof: a valid bearer token authorizes ``tools/list``.

        After the mcp-common ``include={'authorization'}`` fix, a valid
        ``good-<sub>:<role>`` token is verified by the JWT provider,
        seeded into the request context, and the middleware passes
        through to ``tools/list``. The response body MUST carry the
        full tool inventory (``"tools"`` array). This is the inverse
        of ``test_tools_list_without_auth_rejected_by_middleware`` and
        pins the success path that the middleware is wired correctly.
        """
        mcp = _build_with_auth(tmp_path)
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
            session_id = init.headers.get("mcp-session-id", "")
            resp = client.post(
                "/mcp/",
                headers={
                    "Authorization": "Bearer good-alice:reader",
                    "mcp-session-id": session_id,
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/list",
                    "id": 2,
                },
            )
        assert resp.status_code == 200
        body = resp.text
        # Positive proof: tool inventory is present and not an error.
        assert '"tools"' in body, (
            f"expected tool inventory in body, got: {body[:500]!r}"
        )
        assert '"isError":true' not in body
        assert '"error"' not in body
        # Sanity: all 7 substrate/scheduler tools are exposed.
        # (read_settings + write_settings + read_context + write_context +
        #  read_progress + write_progress + schedule_task = 7.)
        for tool_name in (
            "read_settings",
            "write_settings",
            "read_context",
            "write_context",
            "read_progress",
            "write_progress",
            "schedule_task",
        ):
            assert f'"name":"{tool_name}"' in body, (
                f"tool {tool_name!r} missing from inventory: {body[:500]!r}"
            )
