from __future__ import annotations

import asyncio
import ipaddress
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

# ---------------------------------------------------------------------------
# Transport policy helpers
# ---------------------------------------------------------------------------
#
# An ``http://`` OTLP endpoint resolves to a *plaintext* channel, so metric
# names, labels and resource attributes would leave the host in the clear.
# The helpers below decide whether a given endpoint would actually be
# plaintext, so the settings guard never disagrees with the transport the
# exporter really opens.

# AWS / GCP / Azure metadata endpoints. An observability exporter has no
# business talking to a cloud metadata service.
_METADATA_HOSTS: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "169.254.169.253",
        "100.100.100.200",
        "metadata.google.internal",
        "metadata.azure.com",
    }
)


def _strip_brackets(host: str) -> str:
    """Strip IPv6 brackets from a host value (``[::1]`` -> ``::1``)."""
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _is_loopback(host: str) -> bool:
    """Return True for loopback hosts (127.0.0.1, ::1, localhost).

    Mirrors ``oneiric.adapters.llm.bifrost._is_loopback``. The duplication is
    deliberate: adapters do not import across each other, so each module
    keeps its own copy. Keep the two in sync.
    """
    normalized = _strip_brackets(host)
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _endpoint_host(endpoint: str) -> str:
    """The host component of an OTLP endpoint, lowercased and unbracketed.

    ``urlparse`` is the parser the gRPC exporter uses, so a normal
    ``scheme://host:port`` endpoint resolves identically here. Endpoint forms
    without ``//`` (``host:port``) leave ``netloc`` empty — and ``urlparse``
    reads a leading ``localhost:`` as a *scheme* — so those fall back to
    splitting the raw string.
    """
    raw = endpoint.strip()
    parsed = urlparse(raw)
    if parsed.netloc:
        return _strip_brackets((parsed.hostname or "").lower())

    candidate = raw
    for scheme in ("grpcs", "grpc", "https", "http"):
        if candidate.lower().startswith(f"{scheme}:"):
            candidate = candidate[len(scheme) + 1 :]
            break
    if candidate.startswith("["):
        end = candidate.find("]")
        if end != -1:
            return candidate[1:end].lower()
    head, sep, tail = candidate.rpartition(":")
    if sep and head and tail.isdigit():
        candidate = head
    return candidate.split("/", 1)[0].lower()


def _resolved_insecure(endpoint: str, insecure: bool | None) -> bool:
    """Whether the exporter would open a plaintext channel for this endpoint.

    Mirrors the gRPC exporter's own resolution
    (``opentelemetry/exporter/otlp/proto/grpc/exporter.py``) exactly:

        parsed_url = urlparse(self._endpoint)
        if parsed_url.scheme == "https":
            insecure = False
        insecure_exporter = environ.get("OTEL_EXPORTER_OTLP_INSECURE")
        if insecure is None:
            if insecure_exporter is not None:
                insecure = insecure_exporter.lower() == "true"
            else:
                insecure = parsed_url.scheme == "http"

    The environment variable is read at validation time here and again at
    export time, so a change between the two is not seen by this guard.
    """
    parsed_url = urlparse(endpoint)
    if parsed_url.scheme == "https":
        return False
    if insecure is not None:
        return bool(insecure)
    insecure_exporter = os.environ.get("OTEL_EXPORTER_OTLP_INSECURE")
    if insecure_exporter is not None:
        return insecure_exporter.lower() == "true"
    return parsed_url.scheme == "http"


class OTLPObservabilitySettings(BaseModel):
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
    insecure: bool | None = Field(
        default=None,
        description=(
            "Use a plaintext channel. None (the default) lets the exporter "
            "decide from the endpoint scheme: http:// is plaintext, https:// "
            "is TLS. Set true to force plaintext or false to force TLS; an "
            "https:// endpoint stays TLS regardless."
        ),
    )
    service_name: str = Field(default="oneiric")
    environment: str = Field(default="development")
    release: str | None = None
    export_interval_seconds: float = Field(default=10.0, gt=0)
    export_timeout_seconds: float = Field(default=5.0, gt=0)
    enable_traces: bool = True
    enable_metrics: bool = True
    allow_insecure: bool = Field(
        default=False,
        description=(
            "Opt in to a plaintext channel to a non-loopback collector. An "
            "http:// endpoint resolves to plaintext, so a remote collector "
            "needs this explicit opt-in; loopback collectors (the default "
            "endpoint) do not."
        ),
    )

    @model_validator(mode="after")
    def _guard_plaintext_transport(self) -> Self:
        """Fail closed on plaintext telemetry egress to a remote collector.

        The transport is resolved exactly as the exporter resolves it (see
        ``_resolved_insecure``), so this guard never rejects a config the
        exporter would have handled over TLS, and never waves through one it
        would have sent in the clear.

        Three ways out, in order of preference:
          1. use an ``https://`` endpoint,
          2. set ``insecure=False`` to force TLS,
          3. set ``allow_insecure=True`` to opt in to a plaintext
             non-loopback collector.

        ``insecure=True`` on its own is **not** a way out: it selects the
        transport, it does not grant the policy exception.
        """
        host = _endpoint_host(self.endpoint)
        if host in _METADATA_HOSTS:
            raise ValueError(
                f"OTLPObservabilitySettings.endpoint: host '{host}' is a "
                f"cloud metadata endpoint. An observability exporter must "
                f"not target AWS / GCP / Azure metadata services."
            )
        if not _resolved_insecure(self.endpoint, self.insecure):
            return self
        if _is_loopback(host):
            return self
        if self.allow_insecure:
            return self
        raise ValueError(
            f"OTLPObservabilitySettings.endpoint: endpoint '{self.endpoint}' "
            f"resolves to a plaintext channel to non-loopback host "
            f"'{host}'. Telemetry would leave the host unencrypted. Use an "
            f"'https://' endpoint, set insecure=False to force TLS, or set "
            f"allow_insecure=True to opt in to a plaintext non-loopback "
            f"collector."
        )


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
    metadata = AdapterMetadata(
        category="monitoring",
        provider="otel-otlp",
        factory="oneiric.adapters.monitoring.otlp: OTLPObservabilityAdapter",
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

    def _exporter_kwargs(self) -> dict[str, Any]:
        """Transport-specific keyword arguments for the OTLP exporters.

        Only the gRPC exporters accept ``insecure``; the HTTP/protobuf
        exporters have no such parameter (their TLS behaviour follows the
        endpoint scheme and the ``certificate_file`` family of options), so
        passing one raises ``TypeError``.
        """
        kwargs: dict[str, Any] = {
            "endpoint": self._settings.endpoint,
            "headers": self._settings.headers or None,
            "timeout": self._settings.export_timeout_seconds,
        }
        if self._settings.protocol == "grpc":
            kwargs["insecure"] = self._settings.insecure
        return kwargs

    def _create_span_exporter(self, components: _OTLPComponents) -> Any:
        exporter_cls = (
            components.grpc_span_exporter_cls
            if self._settings.protocol == "grpc"
            else components.http_span_exporter_cls
        )
        return exporter_cls(**self._exporter_kwargs())

    def _create_metric_exporter(self, components: _OTLPComponents) -> Any:
        exporter_cls = (
            components.grpc_metric_exporter_cls
            if self._settings.protocol == "grpc"
            else components.http_metric_exporter_cls
        )
        return exporter_cls(**self._exporter_kwargs())

    def _import_components(self) -> _OTLPComponents:
        try:  # pragma: no cover - depends on optional OTLP install
            from opentelemetry import metrics as metrics_api
            from opentelemetry import trace as trace_api
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # ty: ignore[unresolved-import]
                OTLPMetricExporter as GrpcMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # ty: ignore[unresolved-import]
                OTLPSpanExporter as GrpcSpanExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # ty: ignore[unresolved-import]
                OTLPMetricExporter as HttpMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # ty: ignore[unresolved-import]
                OTLPSpanExporter as HttpSpanExporter,
            )
            from opentelemetry.sdk.metrics import (  # ty: ignore[unresolved-import]
                MeterProvider,  # ty: ignore[unresolved-import]
            )
            from opentelemetry.sdk.metrics.export import (  # ty: ignore[unresolved-import]
                PeriodicExportingMetricReader,  # ty: ignore[unresolved-import]
            )
            from opentelemetry.sdk.resources import (  # ty: ignore[unresolved-import]
                Resource,  # ty: ignore[unresolved-import]
            )
            from opentelemetry.sdk.trace import (  # ty: ignore[unresolved-import]
                TracerProvider,  # ty: ignore[unresolved-import]
            )
            from opentelemetry.sdk.trace.export import (  # ty: ignore[unresolved-import]
                BatchSpanProcessor,  # ty: ignore[unresolved-import]
            )
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
