"""Tests for EmbeddingService public behavior + trace-text helpers.

The hybrid chain itself is exercised in
``tests/adapters/observability/test_hybrid_embeddings.py``; this file
focuses on the legacy surface that ``otel_ingester`` and similar
callers depend on:

- ``_build_text_from_trace`` — still part of the public surface
- ``_generate_cache_key`` — still used by ``embed_trace``
- ``_generate_fallback_embedding`` — the deterministic mock fallback
- ``embed_trace`` — the high-level API callers use

Tests for the removed sentence-transformers internals (``_load_model``,
``_generate_embedding``, ``_embed_cached``) were deleted when the
sentence-transformers backend was replaced by the probe chain —
see ``docs/plans/2026-08-22-hybrid-embeddings-design.md``.
"""

from __future__ import annotations

import httpx2 as httpx
import numpy as np
import pytest

from oneiric.adapters.observability.embedding_settings import EmbeddingSettings
from oneiric.adapters.observability.embeddings import EmbeddingService

# ---------------------------------------------------------------------------
# Test helpers — patch httpx.AsyncClient with MockTransport.
#
# EmbeddingService creates its own httpx.AsyncClient inside every probe/encode
# method (it does not accept a client via __init__). To exercise the network
# paths without making real requests, monkeypatch httpx.AsyncClient so every
# instantiation gets a MockTransport-backed client.
# ---------------------------------------------------------------------------


def _make_async_client_factory(handler):
    """Build a factory that returns AsyncClient instances backed by MockTransport.

    EmbeddingService instantiates ``httpx.AsyncClient(timeout=...)`` directly
    inside each probe/encode method, so we cannot inject a transport via
    __init__. Instead, monkeypatch the module-level ``AsyncClient`` symbol
    with a factory that injects the transport.

    The factory captures the original ``httpx.AsyncClient`` class so its
    own internal ``httpx.AsyncClient(...)`` call does not recurse back
    into the factory (since ``httpx`` is imported once and the closure
    resolves the current attribute at call time).
    """
    original_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def _factory(timeout=None, **kwargs):
        return original_async_client(
            transport=transport,
            timeout=timeout,
            **kwargs,
        )

    return _factory


def _install_mock_client(monkeypatch, handler) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _make_async_client_factory(handler))


# ---------------------------------------------------------------------------
# Tests — _build_text_from_trace (kept from old suite)
# ---------------------------------------------------------------------------


def test_build_text_from_trace_full() -> None:
    svc = EmbeddingService()
    text = svc._build_text_from_trace(
        {
            "service": "auth",
            "operation": "login",
            "status": "OK",
            "duration_ms": 42,
            "attributes": {"user": "abc", "method": "POST"},
        }
    )
    assert "auth" in text
    assert "login" in text
    assert "42ms" in text
    assert "user=abc" in text


def test_build_text_from_trace_defaults() -> None:
    svc = EmbeddingService()
    text = svc._build_text_from_trace({})
    assert "unknown" in text


# ---------------------------------------------------------------------------
# Tests — _generate_cache_key (kept from old suite)
# ---------------------------------------------------------------------------


def test_generate_cache_key_consistent() -> None:
    svc = EmbeddingService()
    trace = {"a": 1, "b": 2}
    k1 = svc._generate_cache_key(trace)
    k2 = svc._generate_cache_key(trace)
    assert k1 == k2
    assert isinstance(k1, int)


# ---------------------------------------------------------------------------
# Tests — _generate_fallback_embedding (mock fallback)
#
# Note: the new mock uses numpy.random.standard_normal (Gaussian) seeded
# from the trace_id's SHA-256, so values are centered around 0 (not in
# [0,1] as the old byte-shuffling version was). The test asserts the
# new contract: L2-normalized, deterministic, variable per id.
# ---------------------------------------------------------------------------


def test_generate_fallback_embedding_shape() -> None:
    svc = EmbeddingService()
    emb = svc._generate_fallback_embedding("trace-abc")
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (384,)
    # L2-normalized
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-5


def test_generate_fallback_embedding_deterministic() -> None:
    svc = EmbeddingService()
    e1 = svc._generate_fallback_embedding("same-id")
    e2 = svc._generate_fallback_embedding("same-id")
    assert np.array_equal(e1, e2)


def test_generate_fallback_embedding_differs_by_id() -> None:
    svc = EmbeddingService()
    e1 = svc._generate_fallback_embedding("id-a")
    e2 = svc._generate_fallback_embedding("id-b")
    assert not np.array_equal(e1, e2)


# ---------------------------------------------------------------------------
# Tests — embed_trace public API
#
# These rely on the chain auto-falling back to mock (no real backend
# configured). They verify that ``embed_trace`` keeps the same
# outward contract (returns np.ndarray, handles missing trace_id).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_trace_returns_ndarray_when_no_backend_available() -> None:
    """Without ``await initialize()`` the chain is uninitialised.

    The test asserts that ``embed_trace`` still returns a valid ndarray
    (the mock fallback) so the legacy trace-ingestion call sites don't
    break when the chain hasn't been awaited yet.
    """
    svc = EmbeddingService()
    result = await svc.embed_trace({"trace_id": "fallback-trace"})
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)


@pytest.mark.asyncio
async def test_embed_trace_handles_missing_trace_id() -> None:
    svc = EmbeddingService()
    result = await svc.embed_trace({})  # no trace_id key
    assert result.shape == (384,)


# ---------------------------------------------------------------------------
# Tests — observability settings validator (kept from old suite)
# ---------------------------------------------------------------------------


def test_otel_storage_settings_rejects_non_postgresql_scheme() -> None:
    """validate_connection_string raises for non-postgresql:// scheme (line 51 of settings.py)."""
    import pytest

    from oneiric.adapters.observability.settings import OTelStorageSettings

    with pytest.raises(ValueError, match="postgresql://"):
        OTelStorageSettings(connection_string="mysql://user:pass@host/db")


# ---------------------------------------------------------------------------
# Tests — probe chain (lines 285-490 of embeddings.py)
#
# The probe chain is the EMBEDDING BACKEND DISCOVERY logic. If it silently
# fails, production loses embeddings without warning. Tests below exercise
# each probe leg's success/failure paths and the encode-via-X backends.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _probe_llama_cpp
# ---------------------------------------------------------------------------


async def test_probe_llama_cpp_disabled_returns_false() -> None:
    """When llama_cpp_enabled is False, the probe short-circuits without HTTP."""
    svc = EmbeddingService(settings=EmbeddingSettings(llama_cpp_enabled=False))
    assert await svc._probe_llama_cpp() is False
    assert svc._backend_dim is None


async def test_probe_llama_cpp_success_sets_backend_dim(monkeypatch) -> None:
    """GET /v1/models returns 200 + a probe-encode succeeds → backend_dim set."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, content=b'{"data": []}')
        # Probe-encode call
        if request.url.path.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                content=b'{"data": [{"embedding": [0.1, 0.2, 0.3]}]}',
            )
        return httpx.Response(404)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_llama_cpp() is True
    assert svc._backend_dim == 3


async def test_probe_llama_cpp_get_returns_non_200(monkeypatch) -> None:
    """A non-200 response from /v1/models aborts the probe (no second call)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_llama_cpp() is False
    assert svc._backend_dim is None


async def test_probe_llama_cpp_probe_encode_fails(monkeypatch) -> None:
    """GET /v1/models succeeds but probe-encode returns None → probe fails."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, content=b'{"data": []}')
        # Probe-encode fails
        return httpx.Response(500)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_llama_cpp() is False
    assert svc._backend_dim is None


async def test_probe_llama_cpp_transport_error(monkeypatch) -> None:
    """A transport-level error (httpx.HTTPError) is caught and returns False."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_llama_cpp() is False


# ---------------------------------------------------------------------------
# _probe_ollama
# ---------------------------------------------------------------------------


async def test_probe_ollama_disabled_returns_false() -> None:
    svc = EmbeddingService(settings=EmbeddingSettings(ollama_enabled=False))
    assert await svc._probe_ollama() is False


async def test_probe_ollama_success_uses_prompt_payload(monkeypatch) -> None:
    """GET /api/tags + probe-encode with ollama=True (prompt key) succeeds."""

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, content=b'{"models": []}')
        # Probe-encode for Ollama (ollama=True) — body must use 'prompt' not 'input'
        if request.url.path.endswith("/api/embeddings"):
            import json as _json

            body = _json.loads(request.content)
            assert body == {"model": "nomic-embed-text", "prompt": "probe"}
            return httpx.Response(200, content=b'{"embedding": [0.1, 0.2, 0.3, 0.4]}')
        return httpx.Response(404)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_ollama() is True
    assert svc._backend_dim == 4


async def test_probe_ollama_get_returns_non_200(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_ollama() is False


async def test_probe_ollama_probe_encode_missing_embedding_key(monkeypatch) -> None:
    """Probe-encode returns 200 but no 'embedding' key → probe fails."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, content=b"{}")
        return httpx.Response(200, content=b'{"other": "value"}')

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_ollama() is False


async def test_probe_ollama_transport_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    assert await svc._probe_ollama() is False


# ---------------------------------------------------------------------------
# _probe_minimax
# ---------------------------------------------------------------------------


async def test_probe_minimax_missing_api_key_returns_false() -> None:
    """MiniMax probe requires both api_key AND group_id; missing either → False."""
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_api_key=None, minimax_group_id=None)
    )
    assert await svc._probe_minimax() is False


async def test_probe_minimax_missing_group_id_returns_false() -> None:
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_api_key="key", minimax_group_id=None)
    )
    assert await svc._probe_minimax() is False


async def test_probe_minimax_disabled_returns_false() -> None:
    svc = EmbeddingService(
        settings=EmbeddingSettings(
            minimax_enabled=False, minimax_api_key="key", minimax_group_id="group"
        )
    )
    assert await svc._probe_minimax() is False


async def test_probe_minimax_success_sets_backend_dim(monkeypatch) -> None:
    """MiniMax returns base_resp.status_code=0 + non-empty vectors → success."""

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.method == "POST"
        assert request.url.params.get("GroupId") == "test-group"
        assert request.headers.get("Authorization") == "Bearer test-key"
        return httpx.Response(
            200,
            content=b'{"base_resp": {"status_code": 0}, "vectors": [[0.5, 0.6, 0.7, 0.8]]}',
        )

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(
            minimax_api_key="test-key", minimax_group_id="test-group"
        )
    )
    assert await svc._probe_minimax() is True
    assert svc._backend_dim == 4
    assert len(captured) == 1


async def test_probe_minimax_non_zero_status_code(monkeypatch) -> None:
    """API responds 200 but base_resp.status_code != 0 → probe fails."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"base_resp": {"status_code": 401, "msg": "auth failed"}, "vectors": []}',
        )

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_api_key="k", minimax_group_id="g")
    )
    assert await svc._probe_minimax() is False


async def test_probe_minimax_missing_vectors(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"base_resp": {"status_code": 0}}')

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_api_key="k", minimax_group_id="g")
    )
    assert await svc._probe_minimax() is False


async def test_probe_minimax_http_4xx(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b'{"error": "unauthorized"}')

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_api_key="k", minimax_group_id="g")
    )
    assert await svc._probe_minimax() is False


async def test_probe_minimax_transport_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_api_key="k", minimax_group_id="g")
    )
    assert await svc._probe_minimax() is False


# ---------------------------------------------------------------------------
# _probe_model2vec
# ---------------------------------------------------------------------------


async def test_probe_model2vec_disabled_returns_false() -> None:
    svc = EmbeddingService(settings=EmbeddingSettings(model2vec_enabled=False))
    assert await svc._probe_model2vec() is False


async def test_probe_model2vec_import_error_returns_false(monkeypatch) -> None:
    """If model2vec is not importable, probe returns False gracefully."""
    import sys

    # Hide the model2vec module so the ImportError branch fires
    monkeypatch.setitem(sys.modules, "model2vec", None)
    svc = EmbeddingService()
    assert await svc._probe_model2vec() is False


async def test_probe_model2vec_success_caches_model(monkeypatch) -> None:
    """When StaticModel loads and encodes, the model is cached on the service."""
    import sys
    import types

    fake_model = types.SimpleNamespace()
    fake_model.encode = lambda texts: np.zeros((len(texts), 16), dtype=np.float32)

    class FakeStaticModel:
        @classmethod
        def from_pretrained(cls, _name: str):
            return fake_model

    fake_module = types.ModuleType("model2vec")
    fake_module.StaticModel = FakeStaticModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "model2vec", fake_module)

    svc = EmbeddingService()
    assert await svc._probe_model2vec() is True
    assert svc._backend_dim == 16
    # Model is cached for subsequent encode calls
    assert getattr(svc, "_model2vec_model", None) is fake_model


async def test_probe_model2vec_load_failure_returns_false(monkeypatch) -> None:
    """If StaticModel.from_pretrained raises (e.g. bad model id), probe returns False."""
    import sys
    import types

    class FailingStaticModel:
        @classmethod
        def from_pretrained(cls, _name: str):
            raise RuntimeError("model download failed")

    fake_module = types.ModuleType("model2vec")
    fake_module.StaticModel = FailingStaticModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "model2vec", fake_module)

    svc = EmbeddingService()
    assert await svc._probe_model2vec() is False


# ---------------------------------------------------------------------------
# _probe_encode_via
# ---------------------------------------------------------------------------


async def test_probe_encode_via_non_200_returns_none(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    # Capture the original AsyncClient class BEFORE patching (otherwise the
    # closure would capture our factory and recurse).
    factory = _make_async_client_factory(handler)
    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    # _probe_encode_via takes an existing client; build one with MockTransport
    # directly via the factory so it gets the right transport without recursion.
    client = factory(timeout=5)
    result = await svc._probe_encode_via(
        client, "https://example.com/embed", "model", ["probe"]
    )
    assert result is None


async def test_probe_encode_via_openai_shape_returns_ndarray(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b'{"data": [{"embedding": [0.5, 0.6, 0.7]}]}'
        )

    factory = _make_async_client_factory(handler)
    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    client = factory(timeout=5)
    result = await svc._probe_encode_via(
        client, "https://example.com/embed", "model", ["probe"], ollama=False
    )
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    assert result.shape == (3,)


async def test_probe_encode_via_ollama_shape_returns_ndarray(monkeypatch) -> None:
    """For ollama=True, body is parsed as {'embedding': [...]} (not 'data')."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"embedding": [0.1, 0.2]}')

    factory = _make_async_client_factory(handler)
    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    client = factory(timeout=5)
    result = await svc._probe_encode_via(
        client, "https://example.com/embed", "model", ["probe"], ollama=True
    )
    assert isinstance(result, np.ndarray)
    assert result.shape == (2,)


async def test_probe_encode_via_invalid_json_returns_none(monkeypatch) -> None:
    """JSON decode error (ValueError) is swallowed → None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all {{")

    factory = _make_async_client_factory(handler)
    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    client = factory(timeout=5)
    result = await svc._probe_encode_via(
        client, "https://example.com/embed", "model", ["probe"]
    )
    assert result is None


async def test_probe_encode_via_missing_embedding_key_returns_none(monkeypatch) -> None:
    """OpenAI shape: data list present but no 'embedding' key inside → None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"data": [{}]}')

    factory = _make_async_client_factory(handler)
    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    client = factory(timeout=5)
    result = await svc._probe_encode_via(
        client, "https://example.com/embed", "model", ["probe"], ollama=False
    )
    assert result is None


# ---------------------------------------------------------------------------
# _encode_llama_cpp / _encode_ollama / _encode_minimax / _encode_model2vec
# ---------------------------------------------------------------------------


async def test_encode_llama_cpp_returns_parsed_embeddings(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        import json as _json

        body = _json.loads(request.content)
        assert body == {"model": "nomic-embed-text", "input": ["hello", "world"]}
        return httpx.Response(
            200,
            content=b'{"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}',
        )

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    results = await svc._encode_llama_cpp(["hello", "world"])
    assert len(results) == 2
    assert all(isinstance(r, np.ndarray) and r.dtype == np.float32 for r in results)
    assert results[0].shape == (2,)
    assert results[1].shape == (2,)
    assert len(captured) == 1


async def test_encode_ollama_one_request_per_text(monkeypatch) -> None:
    """Ollama encodes one text per POST (unlike OpenAI-compatible batch)."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        import json as _json

        body = _json.loads(request.content)
        assert "prompt" in body
        return httpx.Response(200, content=b'{"embedding": [0.1, 0.2, 0.3]}')

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService()
    results = await svc._encode_ollama(["a", "b", "c"])
    assert len(results) == 3
    # 3 separate POSTs (Ollama doesn't batch)
    assert len(captured) == 3
    assert all(r.shape == (3,) for r in results)


async def test_encode_minimax_sends_auth_and_group(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url.params.get("GroupId") == "gid"
        assert request.headers.get("Authorization") == "Bearer mkey"
        return httpx.Response(
            200,
            content=b'{"vectors": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}',
        )

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_api_key="mkey", minimax_group_id="gid")
    )
    results = await svc._encode_minimax(["t1", "t2"])
    assert len(results) == 2
    assert results[0].shape == (3,)
    assert results[1].shape == (3,)


async def test_encode_model2vec_uses_cached_model(monkeypatch) -> None:
    """If _model2vec_model is already set, _encode_model2vec does not reload."""
    import types

    fake_model = types.SimpleNamespace()
    fake_model.encode = lambda texts: np.array(
        [[0.1, 0.2] for _ in texts], dtype=np.float32
    )
    svc = EmbeddingService()
    svc._model2vec_model = fake_model  # pre-cached

    # Stub StaticModel.from_pretrained to detect reload attempts
    import sys

    reload_calls: list[str] = []

    class TrackingStaticModel:
        @classmethod
        def from_pretrained(cls, name: str) -> object:
            reload_calls.append(name)
            return fake_model

    monkeypatch.setitem(
        sys.modules, "model2vec", types.SimpleNamespace(StaticModel=TrackingStaticModel)
    )

    results = svc._encode_model2vec(["hello", "world"])
    assert len(results) == 2
    assert all(r.shape == (2,) for r in results)
    assert reload_calls == []  # no reload — used cached model


async def test_encode_model2vec_lazy_loads_when_not_cached(monkeypatch) -> None:
    """If no cached model, _encode_model2vec loads via StaticModel.from_pretrained."""
    import sys
    import types

    fake_model = types.SimpleNamespace()
    fake_model.encode = lambda texts: np.array(
        [[0.5, 0.6, 0.7] for _ in texts], dtype=np.float32
    )

    class FakeStaticModel:
        @classmethod
        def from_pretrained(cls, name: str) -> object:
            return fake_model

    monkeypatch.setitem(
        sys.modules, "model2vec", types.SimpleNamespace(StaticModel=FakeStaticModel)
    )

    svc = EmbeddingService()
    assert not hasattr(svc, "_model2vec_model") or svc._model2vec_model is None
    results = svc._encode_model2vec(["text"])
    assert len(results) == 1
    assert results[0].shape == (3,)
    # Model is now cached for next call
    assert getattr(svc, "_model2vec_model", None) is fake_model


# ---------------------------------------------------------------------------
# initialize() end-to-end probe chain (covers the orchestration logic at
# the top of embeddings.py that ties the probes together)
# ---------------------------------------------------------------------------


async def test_initialize_falls_back_to_mock_when_all_probes_fail(
    monkeypatch,
) -> None:
    """All four probes fail → backend='mock', is_available()=False."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing reachable")

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(
            llama_cpp_enabled=True,
            ollama_enabled=True,
            minimax_enabled=False,  # skip so we don't need api_key/group_id
            model2vec_enabled=False,
        )
    )
    await svc.initialize()
    assert svc.backend_name() == "mock"
    assert svc.is_available() is False


async def test_initialize_selects_llama_cpp_when_first_probe_succeeds(
    monkeypatch,
) -> None:
    """When llama_cpp responds, it's selected and ollama is never tried."""

    ollama_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal ollama_called
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, content=b'{"data": []}')
        if request.url.path.endswith("/v1/embeddings"):
            return httpx.Response(200, content=b'{"data": [{"embedding": [0.1, 0.2]}]}')
        if "ollama" in request.url.host or "/api/" in request.url.path:
            ollama_called = True
        return httpx.Response(404)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(
            ollama_enabled=False,  # avoid probe-encode race in test
            minimax_enabled=False,
            model2vec_enabled=False,
        )
    )
    await svc.initialize()
    assert svc.backend_name() == "llama_cpp"
    assert svc.is_available() is True
    assert svc.dimension() == 2
    assert ollama_called is False


async def test_initialize_skips_to_ollama_when_llama_cpp_fails(monkeypatch) -> None:
    """Chain order: llama_cpp fails → ollama probed next."""

    def handler(request: httpx.Request) -> httpx.Response:
        # llama.cpp GET fails
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(503)
        # Ollama succeeds
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, content=b"{}")
        if request.url.path.endswith("/api/embeddings"):
            return httpx.Response(200, content=b'{"embedding": [0.5, 0.5]}')
        return httpx.Response(404)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(minimax_enabled=False, model2vec_enabled=False)
    )
    await svc.initialize()
    assert svc.backend_name() == "ollama"
    assert svc.dimension() == 2


async def test_initialize_exception_in_probe_does_not_break_chain(monkeypatch) -> None:
    """An unhandled exception in one probe is logged and the chain continues."""
    # The probe methods already swallow httpx.HTTPError. We verify the
    # broader catch-all by injecting a probe that raises a non-HTTPError.
    call_count = {"i": 0}

    async def _flaky_probe(self) -> bool:
        call_count["i"] += 1
        if call_count["i"] == 1:
            raise RuntimeError("probe blew up")
        return False  # subsequent probes return False → fall through to mock

    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.EmbeddingService._probe_llama_cpp",
        _flaky_probe,
    )

    svc = EmbeddingService(
        settings=EmbeddingSettings(
            ollama_enabled=False,
            minimax_enabled=False,
            model2vec_enabled=False,
        )
    )
    # The exception is caught and logged (debug), chain continues to mock
    await svc.initialize()
    assert svc.backend_name() == "mock"
    assert call_count["i"] == 1


async def test_encode_before_initialize_raises_runtime_error() -> None:
    """encode() guards against uninitialized state."""
    svc = EmbeddingService()
    with pytest.raises(RuntimeError, match="initialize"):
        await svc.encode("text")


async def test_encode_batch_before_initialize_raises_runtime_error() -> None:
    """encode_batch() guards against uninitialized state."""
    svc = EmbeddingService()
    with pytest.raises(RuntimeError, match="initialize"):
        await svc.encode_batch(["a", "b"])


async def test_encode_after_initialize_routes_to_selected_backend(monkeypatch) -> None:
    """encode() dispatches to the probe-selected backend's encode method."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, content=b'{"data": []}')
        if request.url.path.endswith("/v1/embeddings"):
            # Return 2-dim embedding
            return httpx.Response(200, content=b'{"data": [{"embedding": [0.7, 0.8]}]}')
        return httpx.Response(404)

    _install_mock_client(monkeypatch, handler)
    svc = EmbeddingService(
        settings=EmbeddingSettings(
            ollama_enabled=False,
            minimax_enabled=False,
            model2vec_enabled=False,
        )
    )
    await svc.initialize()
    assert svc.backend_name() == "llama_cpp"

    result = await svc.encode("hello")
    assert isinstance(result, np.ndarray)
    assert result.shape == (2,)


async def test_embed_trace_falls_back_when_encode_raises(monkeypatch) -> None:
    """When the selected backend's encode raises, embed_trace returns the
    deterministic mock fallback instead of propagating."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Probe (GET /v1/models) succeeds
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, content=b'{"data": []}')
        # Probe-encode (POST /v1/embeddings) succeeds with a real embedding
        if request.url.path.endswith("/v1/embeddings"):
            return httpx.Response(200, content=b'{"data": [{"embedding": [0.1, 0.2]}]}')
        return httpx.Response(404)

    # But the subsequent encode() call will raise
    async def _broken_encode(self, text: str) -> np.ndarray:
        raise httpx.HTTPError("backend died mid-encode")

    _install_mock_client(monkeypatch, handler)
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.EmbeddingService._encode_llama_cpp",
        _broken_encode,
    )

    svc = EmbeddingService(
        settings=EmbeddingSettings(
            ollama_enabled=False,
            minimax_enabled=False,
            model2vec_enabled=False,
        )
    )
    await svc.initialize()
    assert svc.backend_name() == "llama_cpp"

    # embed_trace should catch the encode failure and return the mock fallback
    result = await svc.embed_trace({"trace_id": "abc", "service": "s"})
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)
