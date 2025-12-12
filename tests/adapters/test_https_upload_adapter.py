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
