from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

import pytest

from oneiric.adapters.monitoring.otlp import (
    OTLPObservabilityAdapter,
    OTLPObservabilitySettings,
    _OTLPComponents,
)
from oneiric.core.lifecycle import LifecycleError


class _FakeTraceAPI:
    def __init__(self) -> None:
        self.provider = None

    def set_tracer_provider(self, provider: Any) -> None:
        self.provider = provider


class _FakeMetricsAPI:
    def __init__(self) -> None:
        self.provider = None

    def set_meter_provider(self, provider: Any) -> None:
        self.provider = provider


class _FakeTracerProvider:
    instances: list["_FakeTracerProvider"] = []

    def __init__(self, resource: Any) -> None:
        self.resource = resource
        self.processors: list[Any] = []
        self.shutdown_called = False
        _FakeTracerProvider.instances.append(self)

    def add_span_processor(self, processor: Any) -> None:
        self.processors.append(processor)

    def shutdown(self) -> None:
        self.shutdown_called = True


class _FakeMeterProvider:
    instances: list["_FakeMeterProvider"] = []

    def __init__(self, resource: Any, metric_readers: list[Any]) -> None:
        self.resource = resource
        self.metric_readers = metric_readers
        self.shutdown_called = False
        _FakeMeterProvider.instances.append(self)

    def shutdown(self) -> None:
        self.shutdown_called = True


class _FakeBatchProcessor:
    def __init__(self, exporter: Any) -> None:
        self.exporter = exporter


class _FakeMetricReader:
    def __init__(self, exporter: Any, *, export_interval_millis: int, export_timeout_millis: int) -> None:
        self.exporter = exporter
        self.export_interval_millis = export_interval_millis
        self.export_timeout_millis = export_timeout_millis


class _FakeSpanExporter:
    instances: list["_FakeSpanExporter"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeSpanExporter.instances.append(self)


class _FakeMetricExporter:
    instances: list["_FakeMetricExporter"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeMetricExporter.instances.append(self)


@dataclass
class _FakeResource:
    attributes: Dict[str, Any]


def _fake_components() -> _OTLPComponents:
    _FakeTracerProvider.instances = []
    _FakeMeterProvider.instances = []
    _FakeSpanExporter.instances = []
    _FakeMetricExporter.instances = []
    return _OTLPComponents(
        metrics_api=_FakeMetricsAPI(),
        trace_api=_FakeTraceAPI(),
        Resource=lambda attributes: _FakeResource(attributes=attributes),
        TracerProvider=_FakeTracerProvider,
        BatchSpanProcessor=_FakeBatchProcessor,
        MeterProvider=_FakeMeterProvider,
        MetricReader=_FakeMetricReader,
        grpc_span_exporter_cls=_FakeSpanExporter,
        grpc_metric_exporter_cls=_FakeMetricExporter,
        http_span_exporter_cls=_FakeSpanExporter,
        http_metric_exporter_cls=_FakeMetricExporter,
    )


@pytest.mark.asyncio
async def test_otlp_adapter_configures_traces_and_metrics(monkeypatch) -> None:
    components = _fake_components()
    adapter = OTLPObservabilityAdapter(
        OTLPObservabilitySettings(endpoint="http://collector:4317", protocol="grpc")
    )
    monkeypatch.setattr(
        OTLPObservabilityAdapter,
        "_import_components",
        lambda self: components,
    )
    await adapter.init()
    assert await adapter.health() is True
    assert components.trace_api.provider is _FakeTracerProvider.instances[-1]
    assert components.metrics_api.provider is _FakeMeterProvider.instances[-1]
    span_exporter = _FakeSpanExporter.instances[-1]
    assert span_exporter.kwargs["endpoint"] == "http://collector:4317"
    await adapter.cleanup()
    assert _FakeTracerProvider.instances[-1].shutdown_called is True
    assert _FakeMeterProvider.instances[-1].shutdown_called is True


@pytest.mark.asyncio
async def test_otlp_adapter_uses_http_exporters(monkeypatch) -> None:
    components = _fake_components()
    adapter = OTLPObservabilityAdapter(
        OTLPObservabilitySettings(endpoint="http://collector:4318", protocol="http/protobuf")
    )
    monkeypatch.setattr(
        OTLPObservabilityAdapter,
        "_import_components",
        lambda self: components,
    )
    await adapter.init()
    metric_exporter = _FakeMetricExporter.instances[-1]
    assert metric_exporter.kwargs["endpoint"] == "http://collector:4318"


@pytest.mark.asyncio
async def test_otlp_adapter_requires_enabled_pipeline(monkeypatch) -> None:
    components = _fake_components()
    adapter = OTLPObservabilityAdapter(
        OTLPObservabilitySettings(enable_metrics=False, enable_traces=False)
    )
    monkeypatch.setattr(
        OTLPObservabilityAdapter,
        "_import_components",
        lambda self: components,
    )
    with pytest.raises(LifecycleError):
        await adapter.init()
