"""OTLP monitoring adapter for OpenTelemetry traces + metrics."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class OTLPObservabilitySettings(BaseModel):
    """Settings for configuring OTLP exporters."""

    endpoint: str = Field(
        default="http://127.0.0.1:4317", description="OTLP collector endpoint."
    )
    protocol: str = Field(
        default="grpc",
        pattern="^(grpc|http/protobuf)$",
        description="Protocol used by the OTLP exporter.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict, description="Additional request headers."
    )
    insecure: bool = Field(
        default=False, description="Skip TLS verification when true."
    )
    service_name: str = Field(default="oneiric")
    environment: str = Field(default="development")
    release: str | None = None
    export_interval_seconds: float = Field(default=10.0, gt=0)
    export_timeout_seconds: float = Field(default=5.0, gt=0)
    enable_traces: bool = True
    enable_metrics: bool = True


@dataclass
class _OTLPComponents:
    metrics_api: Any
    trace_api: Any
    Resource: Any
    TracerProvider: Any
    BatchSpanProcessor: Any
    MeterProvider: Any
    MetricReader: Any
    grpc_span_exporter_cls: Any
    grpc_metric_exporter_cls: Any
    http_span_exporter_cls: Any
    http_metric_exporter_cls: Any


class OTLPObservabilityAdapter:
    """Adapter that wires OpenTelemetry SDK exporters for OTLP endpoints."""

    metadata = AdapterMetadata(
        category="monitoring",
        provider="otel-otlp",
        factory="oneiric.adapters.monitoring.otlp:OTLPObservabilityAdapter",
        capabilities=["metrics", "tracing"],
        stack_level=29,
        priority=205,
        source=CandidateSource.LOCAL_PKG,
        owner="Observability",
        requires_secrets=False,
        settings_model=OTLPObservabilitySettings,
    )

    def __init__(self, settings: OTLPObservabilitySettings | None = None) -> None:
        self._settings = settings or OTLPObservabilitySettings()
        self._logger = get_logger("adapter.monitoring.otlp").bind(
            domain="adapter",
            key="monitoring",
            provider="otel-otlp",
        )
        self._configured = False
        self._shutdown_callbacks: list[Callable[[], Any]] = []

    async def init(self) -> None:
        components = self._import_components()
        resource_attrs: dict[str, Any] = {
            "service.name": self._settings.service_name,
            "deployment.environment": self._settings.environment,
        }
        if self._settings.release:
            resource_attrs["service.version"] = self._settings.release
        resource = components.Resource(attributes=resource_attrs)
        if self._settings.enable_traces:
            exporter = self._create_span_exporter(components)
            tracer_provider = components.TracerProvider(resource=resource)
            span_processor = components.BatchSpanProcessor(exporter)
            tracer_provider.add_span_processor(span_processor)
            components.trace_api.set_tracer_provider(tracer_provider)
            if hasattr(tracer_provider, "shutdown"):
                self._shutdown_callbacks.append(tracer_provider.shutdown)
        if self._settings.enable_metrics:
            metric_exporter = self._create_metric_exporter(components)
            interval_ms = int(self._settings.export_interval_seconds * 1000)
            timeout_ms = int(self._settings.export_timeout_seconds * 1000)
            reader = components.MetricReader(
                metric_exporter,
                export_interval_millis=interval_ms,
                export_timeout_millis=timeout_ms,
            )
            meter_provider = components.MeterProvider(
                resource=resource, metric_readers=[reader]
            )
            components.metrics_api.set_meter_provider(meter_provider)
            if hasattr(meter_provider, "shutdown"):
                self._shutdown_callbacks.append(meter_provider.shutdown)
        if not (self._settings.enable_traces or self._settings.enable_metrics):
            raise LifecycleError("otlp-adapter-disabled")
        self._configured = True
        self._logger.info(
            "adapter-init",
            adapter="otel-otlp",
            endpoint=self._settings.endpoint,
            protocol=self._settings.protocol,
        )

    async def health(self) -> bool:
        return self._configured

    async def cleanup(self) -> None:
        callbacks = self._shutdown_callbacks.copy()
        self._shutdown_callbacks.clear()
        for callback in callbacks:
            if callable(callback):
                await asyncio.to_thread(callback)
        self._configured = False
        self._logger.info("adapter-cleanup-complete", adapter="otel-otlp")

    def _create_span_exporter(self, components: _OTLPComponents) -> Any:
        exporter_cls = (
            components.grpc_span_exporter_cls
            if self._settings.protocol == "grpc"
            else components.http_span_exporter_cls
        )
        return exporter_cls(
            endpoint=self._settings.endpoint,
            headers=self._settings.headers or None,
            insecure=self._settings.insecure,
            timeout=self._settings.export_timeout_seconds,
        )

    def _create_metric_exporter(self, components: _OTLPComponents) -> Any:
        exporter_cls = (
            components.grpc_metric_exporter_cls
            if self._settings.protocol == "grpc"
            else components.http_metric_exporter_cls
        )
        return exporter_cls(
            endpoint=self._settings.endpoint,
            headers=self._settings.headers or None,
            insecure=self._settings.insecure,
            timeout=self._settings.export_timeout_seconds,
        )

    def _import_components(self) -> _OTLPComponents:
        try:  # pragma: no cover - depends on optional OTLP install
            from opentelemetry import metrics as metrics_api
            from opentelemetry import trace as trace_api
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter as GrpcMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcSpanExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter as HttpMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter as HttpSpanExporter,
            )
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise LifecycleError("opentelemetry-sdk-missing") from exc

        return _OTLPComponents(
            metrics_api=metrics_api,
            trace_api=trace_api,
            Resource=Resource,
            TracerProvider=TracerProvider,
            BatchSpanProcessor=BatchSpanProcessor,
            MeterProvider=MeterProvider,
            MetricReader=PeriodicExportingMetricReader,
            grpc_span_exporter_cls=GrpcSpanExporter,
            grpc_metric_exporter_cls=GrpcMetricExporter,
            http_span_exporter_cls=HttpSpanExporter,
            http_metric_exporter_cls=HttpMetricExporter,
        )
