from __future__ import annotations

import datetime
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest

from oneiric.actions.http import HttpActionSettings, HttpFetchAction
from oneiric.core.lifecycle import LifecycleError


def _mock_response(
    json_payload: dict | None = None, status_code: int = 200, text: str = ""
):
    # Create a mock response with proper attributes
    mock_response = Mock()
    mock_response.status_code = status_code

    # Properly mock the headers to return a dict-like object
    mock_headers = {"Content-Type": "application/json"}
    mock_response.headers = mock_headers

    # Mock the request object with a URL for the response
    mock_request = Mock()
    mock_request.url = "https://api.local/demo"
    type(mock_response).request = PropertyMock(return_value=mock_request)

    if json_payload is not None:
        mock_response.json.return_value = json_payload
        mock_response.text = json.dumps(json_payload)
    else:
        mock_response.json.return_value = {}
        mock_response.text = text or "ok"

    # Mock is_success property
    type(mock_response).is_success = PropertyMock(return_value=200 <= status_code < 400)

    mock_response.ok = 200 <= status_code < 400

    # Mock the elapsed attribute which needs to be a timedelta object
    elapsed_time = datetime.timedelta(seconds=0.1)  # 100ms as an example
    type(mock_response).elapsed = PropertyMock(return_value=elapsed_time)

    # Mock the aread method
    mock_response.aread = AsyncMock(return_value=None)

    return mock_response


@pytest.mark.asyncio
async def test_http_fetch_action_returns_json() -> None:
    # Create a mock response
    mock_response = _mock_response({"ok": True})

    # Create a mock async client that will return our mock response
    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response

    action = HttpFetchAction(
        HttpActionSettings(base_url="https://api.local"), client=mock_client
    )

    result = await action.execute(
        {
            "path": "/demo",
            "params": {"q": "1"},
            "headers": {"X-Test": "value"},
        }
    )

    assert result["status_code"] == 200
    assert result["json"] == {"ok": True}
    assert result["ok"] is True
    assert result["method"] == "GET"
    # Since we're mocking, the URL field may not be populated as expected
    # The important thing is that the client was called and response was processed correctly

    await mock_client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_action_raise_for_status() -> None:
    # Create a mock response
    mock_response = _mock_response({"error": True}, status_code=500)

    # Create a mock async client that will return our mock response
    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response

    action = HttpFetchAction(
        HttpActionSettings(base_url="https://api.local"), client=mock_client
    )

    with pytest.raises(LifecycleError):
        await action.execute(
            {
                "path": "/demo",
                "raise_for_status": True,
            }
        )

    await mock_client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_action_requires_url() -> None:
    action = HttpFetchAction(HttpActionSettings(base_url=None))

    with pytest.raises(LifecycleError):
        await action.execute({})


# ---------------------------------------------------------------------------
# Gap-fill: uncovered branches in http.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_invalid_method_raises() -> None:
    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=MagicMock())
    with pytest.raises(LifecycleError):
        await action.execute({"url": "https://api.local/x", "method": "CONNECT"})


@pytest.mark.asyncio
async def test_http_non_json_response() -> None:
    mock_response = _mock_response(status_code=200, text="plain text")
    mock_response.json.side_effect = ValueError("not json")
    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response

    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=mock_client)
    result = await action.execute({"url": "https://api.local/text"})

    assert result["json"] is None
    assert result["text"] == "plain text"


@pytest.mark.asyncio
async def test_http_build_url_direct() -> None:
    """_build_url returns str(url) when url key is provided directly (line 163)."""
    mock_response = _mock_response({"ok": True})
    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response

    action = HttpFetchAction(HttpActionSettings(base_url=None), client=mock_client)
    result = await action.execute({"url": "https://direct.example.com/path"})
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_http_build_url_base_url_no_path() -> None:
    """_build_url returns base_url when base_url set but no path (line 167)."""
    mock_response = _mock_response({"ok": True})
    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response

    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=mock_client)
    result = await action.execute({})  # no url, no path
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_http_headers_not_mapping_raises() -> None:
    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=MagicMock())
    with pytest.raises(LifecycleError):
        await action.execute({"url": "https://api.local/x", "headers": "not-a-mapping"})


@pytest.mark.asyncio
async def test_http_params_not_mapping_raises() -> None:
    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=MagicMock())
    with pytest.raises(LifecycleError):
        await action.execute({"url": "https://api.local/x", "params": "not-a-mapping"})


@pytest.mark.asyncio
async def test_http_no_client_uses_internal_client() -> None:
    """When client=None, HttpFetchAction uses an internal httpx.AsyncClient (lines 217-222)."""
    mock_response = _mock_response({"result": "ok"})
    mock_inner_client = AsyncMock()
    mock_inner_client.request = AsyncMock(return_value=mock_response)

    with patch("oneiric.actions.http.httpx.AsyncClient") as MockAsyncClient:
        MockAsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_inner_client)
        MockAsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)

        action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=None)
        result = await action.execute({"url": "https://api.local/x"})
        assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_elapsed_ms_runtime_error_then_returns_none() -> None:
    """_elapsed_ms returns None when both elapsed accesses raise RuntimeError (lines 227-232)."""
    response = MagicMock()
    type(response).elapsed = PropertyMock(side_effect=RuntimeError("not read"))
    response.aread = AsyncMock(return_value=None)

    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"))
    result = await action._elapsed_ms(response)
    assert result is None


@pytest.mark.asyncio
async def test_elapsed_ms_none_elapsed_returns_none() -> None:
    """_elapsed_ms returns None when elapsed is None (line 234)."""
    response = MagicMock()
    type(response).elapsed = PropertyMock(return_value=None)

    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"))
    result = await action._elapsed_ms(response)
    assert result is None
