from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

# Cloud metadata *hostnames*. An observability exporter has no business
# talking to a cloud metadata service.
_METADATA_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.azure.com",
    }
)

# Cloud metadata *networks*. Blocked by membership rather than by literal
# string, so the alternate spellings of an address (decimal, hexadecimal,
# IPv6, trailing dot) cannot slip past.
#
# Deliberately NOT blocking RFC1918 ranges: an internal OTLP collector on
# 10.x is a legitimate destination here, unlike an LLM gateway.
_METADATA_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.IPv4Network("169.254.0.0/16"),  # link-local, covers AWS / Azure IMDS
    ipaddress.IPv4Network("100.100.100.200/32"),  # GCP IMDS
    ipaddress.IPv6Network("fd00:ec2::254/128"),  # AWS IMDS IPv6
    ipaddress.IPv6Network("fe80::/10"),  # IPv6 link-local
)


def _strip_brackets(host: str) -> str:
    """Strip IPv6 brackets from a host value (``[::1]`` -> ``::1``)."""
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _normalized_hostname(host: str) -> str:
    """Lowercase a host and strip one trailing dot (the FQDN root label).

    ``metadata.google.internal.`` names the same host as
    ``metadata.google.internal``; a resolver treats them identically.
    """
    normalized = host.strip().lower()
    return normalized.removesuffix(".")


def _canonical_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The IP address a host string denotes, in canonical form.

    ``ipaddress.ip_address`` alone misses the alternate spellings a resolver
    accepts -- the decimal (``2852039166``) and hexadecimal (``0xa9fea9fe``)
    forms of an IPv4 address -- so ``socket.inet_aton`` is used as a
    fallback. ``inet_aton`` is IPv4-only, so it raises for IPv6 literals,
    which ``ip_address`` has already handled.
    """
    candidate = host.strip()
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(candidate)
    except OSError:
        # inet_aton raises OSError for anything that is not an IPv4 address
        # in one of its accepted spellings.
        return None
    return ipaddress.ip_address(packed)


def _is_metadata_host(host: str) -> bool:
    """True for cloud metadata service endpoints.

    Blocking is by network membership and canonicalised name, not by literal
    string, so ``169.254.169.254``, ``169.254.169.254.``, ``2852039166`` and
    ``0xa9fea9fe`` are all recognised as the same address.

    Deliberately out of scope: resolving the hostname and re-checking the
    resolved addresses before connecting. The endpoint is operator-set
    configuration, not attacker input -- anyone who can write it can aim it
    at a collector the guard already permits under ``allow_insecure`` -- and
    validation-time DNS is both a network side effect at config-parse time
    and a TOCTOU window. Bifrost does not resolve either.
    """
    normalized = _normalized_hostname(host)
    if normalized in _METADATA_HOSTNAMES:
        return True
    address = _canonical_ip(normalized)
    if address is None:
        return False
    for network in _METADATA_NETWORKS:
        # `address in network` is type-strict: an IPv4 address compared
        # against an IPv6 network raises TypeError.
        if address.version != network.version:
            continue
        if address in network:
            return True
    return False


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


def _split_host_port(raw: str) -> tuple[str, int | None]:
    """Split a bare ``host[:port]`` string (no scheme, no netloc)."""
    candidate = raw
    if candidate.startswith("["):
        end = candidate.find("]")
        if end != -1:
            host = candidate[1:end]
            rest = candidate[end + 1 :]
            port = (
                int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else None
            )
            return host.lower(), port
    head, sep, tail = candidate.rpartition(":")
    if sep and head and tail.isdigit():
        return head.lower(), int(tail)
    return candidate.split("/", 1)[0].lower(), None


def _recover_unbracketed_ipv6(netloc: str) -> tuple[str, int | None] | None:
    """Recover an IPv6 literal from a URL netloc that omitted the brackets.

    ``urlparse`` reports only the first hextet as the hostname for an
    unbracketed IPv6 (``http://fd00:ec2::254:4317`` -> ``fd00``), which
    would hide the address from the loopback and metadata checks. Such a URL
    is malformed for ``requests``, but classifying it correctly costs nothing
    and keeps the checks honest.
    """
    head, sep, tail = netloc.rpartition(":")
    if sep and head and tail.isdigit():
        try:
            address = ipaddress.ip_address(head)
        except ValueError:
            address = None
        if address is not None and address.version == 6:
            return str(address), int(tail)
    try:
        address = ipaddress.ip_address(netloc)
    except ValueError:
        return None
    if address.version != 6:
        return None
    return str(address), None


def _parse_endpoint(endpoint: str) -> tuple[str, str, int | None]:
    """Split an endpoint into ``(scheme, host, port)``.

    ``urlparse`` is the parser the exporters use, so a normal
    ``scheme://host:port`` endpoint resolves identically here. Endpoint forms
    without ``//`` (``host:port``) leave ``netloc`` empty — and ``urlparse``
    reads a leading ``localhost:`` as a *scheme* — so those fall back to
    splitting the raw string.

    The scheme returned here is the *effective* one (empty for a bare
    ``host:port``). It is deliberately not the same value as
    ``urlparse(endpoint).scheme``: the transport resolution uses the latter
    verbatim, because that is what the exporter reads.
    """
    raw = endpoint.strip()
    parsed = urlparse(raw)
    if parsed.netloc:
        try:
            port = parsed.port
        except ValueError:
            port = None
        hostname = _strip_brackets((parsed.hostname or "").lower())
        if not parsed.netloc.startswith("[") and parsed.netloc.count(":") > 1:
            recovered = _recover_unbracketed_ipv6(parsed.netloc)
            if recovered is not None:
                hostname, port = recovered
        return parsed.scheme, hostname, port

    for scheme in ("grpcs", "grpc", "https", "http"):
        if raw.lower().startswith(f"{scheme}:"):
            host, port = _split_host_port(raw[len(scheme) + 1 :])
            return scheme, host, port
    host, port = _split_host_port(raw)
    return "", host, port


def _endpoint_display(endpoint: str) -> str:
    """A loggable rendering of the endpoint: scheme, host and port only.

    The endpoint may carry ``http://user:pass@host`` userinfo, a query
    string or a fragment. None of that belongs in an exception message that
    gets logged, so only the scheme and the sanitised host are reported. The
    port is not sensitive and is kept.
    """
    scheme, host, port = _parse_endpoint(endpoint)
    location = f"{host}:{port}" if port is not None else host
    return f"{scheme}://{location}" if scheme else location


def _resolved_insecure(endpoint: str, insecure: bool | None, protocol: str) -> bool:
    """Whether the exporter would open a plaintext channel for this endpoint.

    The two protocols resolve their transport differently, so the resolution
    is protocol-aware — the guard must never reason about a transport the
    exporter will not actually use.

    ``grpc`` mirrors the gRPC exporter's own resolution
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

    ``http/protobuf`` has no such knobs: the HTTP exporters have no
    ``insecure`` parameter and never read ``OTEL_EXPORTER_OTLP_INSECURE``.
    Their transport is decided by the URL scheme alone — ``http://`` is
    plaintext, ``https://`` is TLS.

    The environment variable is read at validation time here and again at
    export time, so a change between the two is not seen by this guard.
    """
    parsed_url = urlparse(endpoint)
    if protocol == "http/protobuf":
        # The `protocol` field pattern admits no third value.
        return parsed_url.scheme == "http"
    if parsed_url.scheme == "https":
        return False
    if insecure is not None:
        return bool(insecure)
    insecure_exporter = os.environ.get("OTEL_EXPORTER_OTLP_INSECURE")
    if insecure_exporter is not None:
        return insecure_exporter.lower() == "true"
    return parsed_url.scheme == "http"


class OTLPObservabilitySettings(BaseModel):
    # Pydantic echoes the offending input into every validation error by
    # default. This model carries `headers` (vendor API keys) and `endpoint`
    # (which may embed userinfo), so that echo would leak secrets into
    # whatever logs the error. Hide the input; the error messages below
    # already carry the sanitised details an operator needs.
    model_config = ConfigDict(hide_input_in_errors=True)

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

        The transport is resolved exactly as the exporter resolves it for the
        configured protocol (see ``_resolved_insecure``), so this guard never
        rejects a config the exporter would have handled over TLS, and never
        waves through one it would have sent in the clear.

        Three ways out, in order of preference:
          1. use an ``https://`` endpoint,
          2. set ``insecure=False`` to force TLS (gRPC only),
          3. set ``allow_insecure=True`` to opt in to a plaintext
             non-loopback collector.

        ``insecure=True`` on its own is **not** a way out: it selects the
        transport, it does not grant the policy exception.
        """
        if self.protocol == "http/protobuf" and self.insecure is not None:
            # `insecure` selects the transport on gRPC only. On
            # http/protobuf it would be silently ignored — the very failure
            # mode this guard exists to prevent — so it is rejected rather
            # than ignored.
            raise ValueError(
                "OTLPObservabilitySettings.insecure: the 'http/protobuf' "
                "exporters have no 'insecure' parameter and never read "
                "OTEL_EXPORTER_OTLP_INSECURE, so the endpoint scheme alone "
                "decides the transport — an 'http://' endpoint is sent in "
                "plaintext whatever this setting says. Remove 'insecure', "
                "or use protocol='grpc' where it is meaningful."
            )

        _, host, _ = _parse_endpoint(self.endpoint)
        if _is_metadata_host(host):
            raise ValueError(
                f"OTLPObservabilitySettings.endpoint: host '{host}' is a "
                f"cloud metadata endpoint. An observability exporter must "
                f"not target AWS / GCP / Azure metadata services."
            )
        if not _resolved_insecure(self.endpoint, self.insecure, self.protocol):
            return self
        if _is_loopback(host):
            return self
        if self.allow_insecure:
            return self
        raise ValueError(
            f"OTLPObservabilitySettings.endpoint: endpoint "
            f"'{_endpoint_display(self.endpoint)}' resolves to a plaintext "
            f"channel to non-loopback host '{host}'. Telemetry would leave "
            f"the host unencrypted. Use an 'https://' endpoint, set "
            f"insecure=False to force TLS, or set allow_insecure=True to "
            f"opt in to a plaintext non-loopback collector."
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
