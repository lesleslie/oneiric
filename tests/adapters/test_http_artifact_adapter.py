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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_artifact_init_creates_client() -> None:
    """init() creates httpx.AsyncClient when none provided (lines 54-61)."""
    adapter = HTTPArtifactAdapter(
        HTTPArtifactSettings(base_url="https://example.com", timeout=10.0, verify_tls=False)
    )
    await adapter.init()
    assert adapter._client is not None
    assert adapter._owns_client is True
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_http_artifact_cleanup_owned_client() -> None:
    """cleanup() closes client when _owns_client=True (line 66)."""
    adapter = HTTPArtifactAdapter(HTTPArtifactSettings())
    await adapter.init()
    assert adapter._owns_client is True
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_http_artifact_health_with_base_url() -> None:
    """health() GETs base_url and returns True on sub-500 status (lines 73-75)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport, base_url="https://example.com")
    adapter = HTTPArtifactAdapter(
        HTTPArtifactSettings(base_url="https://example.com"),
        client=client,
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_http_artifact_health_no_base_url() -> None:
    """health() returns True immediately when base_url is None (line 72)."""
    adapter = HTTPArtifactAdapter(
        HTTPArtifactSettings(),
        client=httpx.AsyncClient(),
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_http_artifact_download_http_error_raises() -> None:
    """download() wraps HTTPError in LifecycleError (lines 87-89)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    client = httpx.AsyncClient(transport=transport)
    adapter = HTTPArtifactAdapter(HTTPArtifactSettings(), client=client)
    await adapter.init()
    with pytest.raises(LifecycleError, match="http-artifact-download-failed"):
        await adapter.download("https://example.com/fail.bin")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_http_artifact_download_to_file(tmp_path) -> None:
    """download_to_file() writes data to disk (lines 100-103)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"file-data"))
    client = httpx.AsyncClient(transport=transport)
    adapter = HTTPArtifactAdapter(HTTPArtifactSettings(), client=client)
    await adapter.init()
    dest = tmp_path / "artifact.bin"
    await adapter.download_to_file("https://example.com/artifact.bin", dest)
    assert dest.read_bytes() == b"file-data"
    await adapter.cleanup()


def test_http_artifact_ensure_client_raises_when_not_initialized() -> None:
    """_ensure_client raises LifecycleError when client is not set (line 107)."""
    adapter = HTTPArtifactAdapter(HTTPArtifactSettings())
    with pytest.raises(LifecycleError, match="http-artifact-client-not-initialized"):
        adapter._ensure_client()
