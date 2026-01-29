from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
            base_url="http://test.netdata:19999",
            headers={},
            timeout=10.0
        )

        await adapter.cleanup()


@pytest.mark.asyncio
async def test_netdata_adapter_initializes_with_api_key() -> None:
    fake_async_client = AsyncMock()

    with patch("oneiric.adapters.monitoring.netdata.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = fake_async_client
        settings = NetdataMonitoringSettings(
            base_url="http://test.netdata:19999",
            api_key="test-api-key"
        )
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()

        mock_httpx.AsyncClient.assert_called_once_with(
            base_url="http://test.netdata:19999",
            headers={"X-API-Key": "test-api-key"},
            timeout=10.0
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

        # Initialize the adapter first
        await adapter.init()

        # Reset the call count after init
        fake_async_client.get.reset_mock()

        # Test health check
        health_result = await adapter.health()
        assert health_result is True

        # Verify get was called once during health check
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

        # Initialize the adapter first
        await adapter.init()

        # Test health check failure
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
            metrics_refresh_interval=1.0  # Short interval for faster testing
        )
        adapter = NetdataMonitoringAdapter(settings)

        await adapter.init()

        # Verify that the metrics task was started
        assert adapter._metrics_task is not None

        # Perform cleanup
        await adapter.cleanup()

        # Verify that the metrics task was cancelled and client was closed
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

        # Test sending a custom metric
        result = await adapter.send_custom_metric(
            chart_name="oneiric.components",
            dimension="active",
            value=42.0,
            units="count"
        )

        assert result is True
        fake_async_client.post.assert_called_once_with("/api/v1/data", json={
            "chart": "oneiric.components",
            "dimensions": {
                "active": 42.0
            },
            "units": "count"
        })

        await adapter.cleanup()
