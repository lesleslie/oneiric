from __future__ import annotations

import httpx
import pytest

from oneiric.adapters.file_transfer.http_artifact import (
    HTTPArtifactAdapter,
    HTTPArtifactSettings,
)
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_http_artifact_download_and_checksum() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"artifact-bytes")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.com"
    )
    adapter = HTTPArtifactAdapter(
        HTTPArtifactSettings(base_url="https://example.com"),
        client=client,
    )
    await adapter.init()

    data = await adapter.download(
        "/artifact.bin",
        sha256="6521df166eb07efaf36eba5b6bedefd9d6a252e9c80bab1c99653700ec71473c",
    )
    assert data == b"artifact-bytes"

    await adapter.cleanup()
    await client.aclose()


@pytest.mark.asyncio
async def test_http_artifact_checksum_failure() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"oops")
        )
    )
    adapter = HTTPArtifactAdapter(HTTPArtifactSettings(), client=client)
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.download("https://example.com/file.bin", sha256="deadbeef")
    await adapter.cleanup()
    await client.aclose()
