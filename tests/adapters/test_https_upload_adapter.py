from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.file_transfer.http_upload import (
    HTTPSUploadAdapter,
    HTTPSUploadSettings,
)
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_https_upload_adapter_upload_injects_headers() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(201, headers={"Location": "https://example.com/uploaded"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    )
    adapter = HTTPSUploadAdapter(
        HTTPSUploadSettings(
            base_url="https://example.com",
            auth_token=SecretStr("secret-token"),
            default_headers={"X-Default": "1"},
        ),
        client=client,
    )

    await adapter.init()
    location = await adapter.upload(
        "/artifact.bin",
        b"payload",
        content_type="application/octet-stream",
        extra_headers={"X-Extra": "demo"},
    )

    assert location == "https://example.com/uploaded"
    assert captured["method"] == "PUT"
    assert captured["url"] == "https://example.com/artifact.bin"
    assert captured["body"] == b"payload"
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["x-default"] == "1"
    assert headers["x-extra"] == "demo"
    assert headers["content-type"] == "application/octet-stream"
    assert headers["authorization"] == "Bearer secret-token"

    await adapter.cleanup()
    await client.aclose()


@pytest.mark.asyncio
async def test_https_upload_adapter_upload_file_and_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    )
    adapter = HTTPSUploadAdapter(
        HTTPSUploadSettings(base_url="https://example.com"), client=client
    )
    await adapter.init()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"file-bytes")
        tmp_path = Path(tmp.name)

    with pytest.raises(LifecycleError):
        await adapter.upload_file("/artifact.bin", tmp_path)

    tmp_path.unlink()
    await adapter.cleanup()
    await client.aclose()


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_https_upload_init_creates_client() -> None:
    """init() creates httpx.AsyncClient when none provided (lines 72-82)."""
    adapter = HTTPSUploadAdapter(
        HTTPSUploadSettings(base_url="https://example.com", timeout=10.0, verify_tls=False)
    )
    await adapter.init()
    assert adapter._client is not None
    assert adapter._owns_client is True
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_https_upload_cleanup_owned_client() -> None:
    """cleanup() closes client when _owns_client=True (line 87)."""
    adapter = HTTPSUploadAdapter(HTTPSUploadSettings())
    await adapter.init()
    assert adapter._owns_client is True
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_https_upload_health_with_base_url() -> None:
    """health() GETs base_url and returns True on sub-500 status (lines 92-96)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport, base_url="https://example.com")
    adapter = HTTPSUploadAdapter(
        HTTPSUploadSettings(base_url="https://example.com"),
        client=client,
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_https_upload_health_no_base_url() -> None:
    """health() returns True immediately when base_url is None (line 92)."""
    adapter = HTTPSUploadAdapter(
        HTTPSUploadSettings(),
        client=httpx.AsyncClient(),
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


def test_https_upload_ensure_client_raises_when_not_initialized() -> None:
    """_ensure_client raises LifecycleError when client is not set (line 159)."""
    adapter = HTTPSUploadAdapter(HTTPSUploadSettings())
    with pytest.raises(LifecycleError, match="https-upload-client-not-initialized"):
        adapter._ensure_client()
