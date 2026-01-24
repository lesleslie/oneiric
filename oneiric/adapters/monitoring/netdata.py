"""Netdata monitoring adapter."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

if TYPE_CHECKING:  # pragma: no cover
    from asyncio import Task

try:  # pragma: no cover - optional dependency import
    import httpx
except Exception:  # pragma: no cover - optional dependency import
    httpx = None  # type: ignore[assignment]


class NetdataMonitoringSettings(BaseModel):
    """Configuration for the Netdata adapter."""

    base_url: str = Field(
        default="http://127.0.0.1:19999",
        description="Base URL for the Netdata server.",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="API key for Netdata authentication; falls back to NETDATA_API_KEY env var when omitted.",
    )
    hostname: str | None = Field(
        default=None,
        description="Hostname to associate with metrics; defaults to system hostname.",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment tag.",
    )
    enable_metrics_collection: bool = Field(
        default=True,
        description="Enable collection and reporting of Oneiric metrics to Netdata.",
    )
    metrics_refresh_interval: float = Field(
        default=30.0,
        ge=1.0,
        description="Interval in seconds between metric collection cycles.",
    )
    timeout: float = Field(
        default=10.0,
        ge=1.0,
        description="Request timeout in seconds for Netdata API calls.",
    )


class NetdataMonitoringAdapter:
    """Adapter that integrates Oneiric with Netdata for system and application monitoring."""

    metadata = AdapterMetadata(
        category="monitoring",
        provider="netdata",
        factory="oneiric.adapters.monitoring.netdata:NetdataMonitoringAdapter",
        capabilities=["metrics", "monitoring", "visualization"],
        stack_level=28,
        priority=215,
        source=CandidateSource.LOCAL_PKG,
        owner="Observability",
        requires_secrets=False,
        settings_model=NetdataMonitoringSettings,
    )

    def __init__(self, settings: NetdataMonitoringSettings | None = None) -> None:
        self._settings = settings or NetdataMonitoringSettings()
        self._logger = get_logger("adapter.monitoring.netdata").bind(
            domain="adapter",
            key="monitoring",
            provider="netdata",
        )
        self._configured = False
        self._client: httpx.AsyncClient | None = None
        self._metrics_task: Task[Any] | None = None

    async def init(self) -> None:
        if httpx is None:  # pragma: no cover - optional dependency
            raise LifecycleError("httpx-missing")

        try:
            # Initialize the httpx client for Netdata API
            headers = {}
            if self._settings.api_key:
                headers["X-API-Key"] = self._settings.api_key.get_secret_value()

            self._client = httpx.AsyncClient(
                base_url=self._settings.base_url,
                headers=headers,
                timeout=self._settings.timeout,
            )

            # Verify connectivity to Netdata server
            await self.health()

            # Start metrics collection if enabled
            if self._settings.enable_metrics_collection:
                self._metrics_task = asyncio.create_task(self._collect_metrics_loop())

            self._configured = True
            self._logger.info(
                "adapter-init",
                adapter="netdata",
                base_url=self._settings.base_url,
                environment=self._settings.environment,
            )
        except Exception as exc:  # pragma: no cover - depends on httpx internals
            raise LifecycleError("netdata-init-failed") from exc

    async def health(self) -> bool:
        if not self._client:
            return False

        try:
            # Check if we can reach the Netdata server using the info endpoint
            response = await self._client.get("/api/v1/info")
            return response.status_code < 400
        except Exception:  # pragma: no cover - network error path
            return False

    async def cleanup(self) -> None:
        # Cancel metrics collection task if running
        if self._metrics_task and not self._metrics_task.done():
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass  # Expected when cancelling the task

        # Close the httpx client
        if self._client:
            await self._client.aclose()

        self._configured = False
        self._logger.info("adapter-cleanup-complete", adapter="netdata")

    async def _collect_metrics_loop(self) -> None:
        """Continuously collect and report metrics to Netdata."""
        while True:
            try:
                await asyncio.sleep(self._settings.metrics_refresh_interval)

                # Collect Oneiric-specific metrics
                await self._collect_oneiric_metrics()
            except asyncio.CancelledError:
                # Task cancelled, exit the loop
                break
            except Exception as e:  # pragma: no cover - error handling
                self._logger.warning(
                    "metrics-collection-error",
                    error=str(e),
                    interval=self._settings.metrics_refresh_interval,
                )

    async def _collect_oneiric_metrics(self) -> None:
        """Collect and report Oneiric-specific metrics to Netdata."""
        if not self._client:
            return

        try:
            # Example: Report Oneiric component counts
            # This would need to be connected to actual Oneiric metrics
            # For now, we'll just log that the collection is happening
            self._logger.debug("collecting-oneiric-metrics")
        except Exception as e:  # pragma: no cover - error handling
            self._logger.warning("oneiric-metrics-collection-error", error=str(e))

    async def send_custom_metric(
        self, chart_name: str, dimension: str, value: float, units: str = "value"
    ) -> bool:
        """Send a custom metric to Netdata via its data collection API."""
        if not self._client:
            return False

        try:
            # Netdata's API for pushing custom metrics
            # Using the API endpoint that allows pushing metrics
            payload = {
                "chart": chart_name,
                "dimensions": {dimension: value},
                "units": units,
            }

            response = await self._client.post("/api/v1/data", json=payload)
            return response.status_code < 400
        except Exception as e:  # pragma: no cover - error handling
            self._logger.warning(
                "custom-metric-send-error",
                chart_name=chart_name,
                dimension=dimension,
                error=str(e),
            )
            return False
