from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from oneiric.adapters.dhara_pusher import DharaAdapterPusher, push_adapters_on_startup


def _make_metadata(
    *,
    category: str = "cache",
    provider: str = "memory",
    factory: Any = "oneiric.adapters.cache.memory:MemoryCacheAdapter",
    version: str | None = "1.0.0",
    capabilities: list[str] | None = None,
    description: str = "In-memory cache",
    owner: str = "Platform",
    requires_secrets: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        category=category,
        provider=provider,
        factory=factory,
        version=version,
        capabilities=capabilities or ["get", "set"],
        description=description,
        owner=owner,
        requires_secrets=requires_secrets,
    )


class _FakeResponse:
    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock()
            )

    def json(self) -> dict[str, Any]:
        return self._body


def _make_pusher(
    response: dict[str, Any] | None = None, raise_http: bool = False
) -> tuple[DharaAdapterPusher, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    pusher = DharaAdapterPusher()

    def fake_post(url: str, json: dict[str, Any]) -> _FakeResponse:
        calls.append({"url": url, "json": json})
        if raise_http:
            import httpx

            raise httpx.ConnectError("connection refused")
        return _FakeResponse(response or {"success": True})

    pusher.client.post = fake_post  # type: ignore[method-assign]
    return pusher, calls


# ---------------------------------------------------------------------------
# DharaAdapterPusher tests
# ---------------------------------------------------------------------------


def test_pusher_init_defaults() -> None:
    """__init__() sets dhara_url and timeout and creates httpx.Client."""
    pusher = DharaAdapterPusher()
    assert pusher.dhara_url == "http://127.0.0.1:8683"
    assert pusher.timeout == 30.0
    pusher.close()


def test_pusher_init_strips_trailing_slash() -> None:
    """__init__() strips trailing slash from dhara_url."""
    pusher = DharaAdapterPusher(dhara_url="http://localhost:8683/")
    assert pusher.dhara_url == "http://localhost:8683"
    pusher.close()


def test_make_adapter_id() -> None:
    """_make_adapter_id() returns 'adapter:category:provider'."""
    pusher, _ = _make_pusher()
    meta = _make_metadata(category="vector", provider="qdrant")
    assert pusher._make_adapter_id(meta) == "adapter:vector:qdrant"


def test_push_single_adapter_success() -> None:
    """_push_single_adapter() returns {'success': True} on 200 response."""
    pusher, calls = _make_pusher({"success": True})
    meta = _make_metadata()
    result = pusher._push_single_adapter(meta)
    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0]["json"]["provider"] == "memory"


def test_push_single_adapter_callable_factory() -> None:
    """_push_single_adapter() handles callable factory (lines 139-142)."""
    pusher, calls = _make_pusher({"success": True})

    def my_factory() -> None:
        pass

    meta = _make_metadata(factory=my_factory)
    pusher._push_single_adapter(meta)
    assert "my_factory" in calls[0]["json"]["factory_path"]


def test_push_single_adapter_http_error() -> None:
    """_push_single_adapter() returns {'success': False} on HTTPError (lines 175-179)."""
    pusher, _ = _make_pusher(raise_http=True)
    meta = _make_metadata()
    result = pusher._push_single_adapter(meta)
    assert result["success"] is False
    assert "HTTP error" in result["error"] or "error" in result


def test_push_single_adapter_http_status_error() -> None:
    """_push_single_adapter() returns {'success': False} on 500 response."""
    pusher, _ = _make_pusher({"detail": "server error"}, raise_http=False)
    pusher.client.post = lambda url, json: _FakeResponse(
        {"detail": "server error"}, status=500
    )  # type: ignore[method-assign]
    meta = _make_metadata()
    result = pusher._push_single_adapter(meta)
    assert result["success"] is False


def test_push_single_adapter_general_exception() -> None:
    """_push_single_adapter() returns {'success': False} on unexpected error (lines 181-185)."""
    pusher, _ = _make_pusher()

    def bad_post(url: str, json: dict[str, Any]) -> None:
        raise ValueError("unexpected")

    pusher.client.post = bad_post  # type: ignore[method-assign]
    meta = _make_metadata()
    result = pusher._push_single_adapter(meta)
    assert result["success"] is False
    assert "unexpected" in result["error"]


def test_push_builtin_adapters_all_success() -> None:
    """push_builtin_adapters() counts successes correctly (lines 56-123)."""
    pusher, _ = _make_pusher({"success": True})
    adapters = [_make_metadata(provider=f"p{i}") for i in range(3)]
    results = pusher.push_builtin_adapters(adapters)
    assert results["total"] == 3
    assert results["success"] == 3
    assert results["errors"] == 0


def test_push_builtin_adapters_some_errors() -> None:
    """push_builtin_adapters() counts errors correctly (lines 91-103)."""
    pusher, _ = _make_pusher({"success": False, "error": "quota"})
    adapters = [_make_metadata()]
    results = pusher.push_builtin_adapters(adapters)
    assert results["errors"] == 1
    assert results["details"][0]["status"] == "error"
    assert results["details"][0]["error"] == "quota"


def test_push_builtin_adapters_exception_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """push_builtin_adapters() handles unexpected exception per adapter (lines 105-116)."""
    pusher, _ = _make_pusher()

    def explode(self: Any, metadata: Any) -> dict[str, Any]:
        raise RuntimeError("network down")

    monkeypatch.setattr(DharaAdapterPusher, "_push_single_adapter", explode)
    adapters = [_make_metadata()]
    results = pusher.push_builtin_adapters(adapters)
    assert results["errors"] == 1
    assert results["details"][0]["status"] == "exception"
    assert "network down" in results["details"][0]["error"]


def test_pusher_close() -> None:
    """close() closes the httpx client without raising."""
    pusher = DharaAdapterPusher()
    pusher.close()  # must not raise


def test_push_adapters_on_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """push_adapters_on_startup() calls builtin_adapter_metadata and push_builtin_adapters."""
    meta = _make_metadata()
    monkeypatch.setattr(
        "oneiric.adapters.dhara_pusher.DharaAdapterPusher._push_single_adapter",
        lambda self, m: {"success": True},
    )
    with patch(
        "oneiric.adapters.bootstrap.builtin_adapter_metadata", return_value=[meta]
    ):
        results = push_adapters_on_startup()
    assert results["success"] == 1


def test_main_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() returns 0 when all adapters push successfully."""
    from oneiric.adapters.dhara_pusher import main

    monkeypatch.setattr(
        "oneiric.adapters.dhara_pusher.push_adapters_on_startup",
        lambda **_: {"success": 2, "total": 2, "errors": 0, "details": []},
    )
    monkeypatch.setattr("sys.argv", ["dhara_pusher"])
    result = main()
    assert result == 0


def test_main_with_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() returns 1 and prints errors when pushes fail."""
    from oneiric.adapters.dhara_pusher import main

    details = [
        {"adapter_id": "adapter:cache:broken", "status": "error", "error": "timeout"},
    ]
    monkeypatch.setattr(
        "oneiric.adapters.dhara_pusher.push_adapters_on_startup",
        lambda **_: {"success": 0, "total": 1, "errors": 1, "details": details},
    )
    monkeypatch.setattr("sys.argv", ["dhara_pusher", "--druva-url", "http://test:8683"])
    result = main()
    assert result == 1
    captured = capsys.readouterr()
    assert "adapter:cache:broken" in captured.out
