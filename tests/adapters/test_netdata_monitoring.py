from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from oneiric.adapters.monitoring.netdata import (
    NetdataMonitoringAdapter,
    NetdataMonitoringSettings,
)
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_netdata_adapter_initializes_with_defaults() -> None:
    fake_async_client = AsyncMock()
    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_async_client.get.return_value = fake_response

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(base_url="http://test.netdata:19999")
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()

        assert await adapter.health() is True
        mock_httpx.AsyncClient.assert_called_once_with(
            base_url="http://test.netdata:19999", headers={}, timeout=10.0
        )

        await adapter.cleanup()


@pytest.mark.asyncio
async def test_netdata_adapter_initializes_with_api_key() -> None:
    fake_async_client = AsyncMock()

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(
            base_url="http://test.netdata:19999", api_key="test-api-key"
        )
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()

        mock_httpx.AsyncClient.assert_called_once_with(
            base_url="http://test.netdata:19999",
            headers={"X-API-Key": "test-api-key"},
            timeout=10.0,
        )

        await adapter.cleanup()


@pytest.mark.asyncio
async def test_netdata_adapter_health_check() -> None:
    fake_async_client = AsyncMock()
    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_async_client.get.return_value = fake_response

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(base_url="http://test.netdata:19999")
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()
        fake_async_client.get.reset_mock()

        health_result = await adapter.health()
        assert health_result is True
        fake_async_client.get.assert_called_once_with("/api/v1/info")

        await adapter.cleanup()


@pytest.mark.asyncio
async def test_netdata_adapter_health_check_failure() -> None:
    fake_async_client = AsyncMock()
    fake_async_client.get.side_effect = Exception("Connection failed")

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(base_url="http://test.netdata:19999")
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()

        health_result = await adapter.health()
        assert health_result is False

        await adapter.cleanup()


@pytest.mark.asyncio
async def test_netdata_adapter_missing_dependency() -> None:
    with patch("oneiric.adapters.monitoring.netdata.httpx", None):
        adapter = NetdataMonitoringAdapter(NetdataMonitoringSettings())
        with pytest.raises(LifecycleError, match="httpx-missing"):
            await adapter.init()


@pytest.mark.asyncio
async def test_netdata_adapter_cleanup_stops_metrics_task() -> None:
    fake_async_client = AsyncMock()

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(
            base_url="http://test.netdata:19999",
            enable_metrics_collection=True,
            metrics_refresh_interval=1.0,
        )
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()
        assert adapter._metrics_task is not None

        await adapter.cleanup()

        fake_async_client.aclose.assert_called_once()
        assert adapter._configured is False


@pytest.mark.asyncio
async def test_netdata_adapter_send_custom_metric() -> None:
    fake_async_client = AsyncMock()
    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_async_client.post.return_value = fake_response

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(base_url="http://test.netdata:19999")
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()

        result = await adapter.send_custom_metric(
            chart_name="oneiric.components",
            dimension="active",
            value=42.0,
            units="count",
        )

        assert result is True
        fake_async_client.post.assert_called_once_with(
            "/api/v1/data",
            json={
                "chart": "oneiric.components",
                "dimensions": {"active": 42.0},
                "units": "count",
            },
        )

        await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — health() without client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_client() -> None:
    adapter = NetdataMonitoringAdapter()
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# Tests — send_custom_metric without client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_custom_metric_no_client() -> None:
    adapter = NetdataMonitoringAdapter()
    result = await adapter.send_custom_metric("chart", "dim", 1.0)
    assert result is False


# ---------------------------------------------------------------------------
# Tests — _collect_metrics_loop runs and cancels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_metrics_loop_cancels_cleanly() -> None:
    fake_async_client = AsyncMock()
    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_async_client.get.return_value = fake_response

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(
            base_url="http://test.netdata:19999",
            enable_metrics_collection=True,
            metrics_refresh_interval=3600.0,  # long interval — never fires
        )
        adapter = NetdataMonitoringAdapter(settings)
        await adapter.init()
        assert adapter._metrics_task is not None
        assert not adapter._metrics_task.done()
        await adapter.cleanup()
        assert adapter._configured is False


# ---------------------------------------------------------------------------
# Tests — _collect_oneiric_metrics with client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_oneiric_metrics_no_client() -> None:
    adapter = NetdataMonitoringAdapter()
    await adapter._collect_oneiric_metrics()  # should return early, not raise


@pytest.mark.asyncio
async def test_collect_oneiric_metrics_with_client() -> None:
    fake_client = AsyncMock()
    adapter = NetdataMonitoringAdapter()
    adapter._client = fake_client
    await adapter._collect_oneiric_metrics()  # logs debug, no exception


# ---------------------------------------------------------------------------
# Tests — cleanup without metrics task or client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_no_task_no_client() -> None:
    adapter = NetdataMonitoringAdapter()
    await adapter.cleanup()  # should not raise
    assert adapter._configured is False


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_metrics_loop_executes_and_cancels() -> None:
    """_collect_metrics_loop runs sleep + _collect_oneiric_metrics then exits on cancel (lines 135-141)."""
    fake_client = AsyncMock()
    settings = NetdataMonitoringSettings(
        base_url="http://test.netdata:19999",
        enable_metrics_collection=True,
        metrics_refresh_interval=1.0,
    )
    adapter = NetdataMonitoringAdapter(settings)
    adapter._client = fake_client
    # Bypass Pydantic's min constraint to get a near-zero sleep for fast test execution
    object.__setattr__(adapter._settings, "metrics_refresh_interval", 0.001)

    task = asyncio.create_task(adapter._collect_metrics_loop())
    await asyncio.sleep(0.05)  # let at least one iteration complete
    task.cancel()
    await task  # loop breaks on CancelledError — no exception propagates
