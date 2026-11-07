from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    instances: list[_FakeTracerProvider] = []

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
    instances: list[_FakeMeterProvider] = []

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
    def __init__(
        self, exporter: Any, *, export_interval_millis: int, export_timeout_millis: int
    ) -> None:
        self.exporter = exporter
        self.export_interval_millis = export_interval_millis
        self.export_timeout_millis = export_timeout_millis


class _FakeSpanExporter:
    instances: list[_FakeSpanExporter] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeSpanExporter.instances.append(self)


class _FakeMetricExporter:
    instances: list[_FakeMetricExporter] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeMetricExporter.instances.append(self)


@dataclass
class _FakeResource:
    attributes: dict[str, Any]


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
        OTLPObservabilitySettings(endpoint="http://localhost:4317", protocol="grpc")
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
    assert span_exporter.kwargs["endpoint"] == "http://localhost:4317"
    await adapter.cleanup()
    assert _FakeTracerProvider.instances[-1].shutdown_called is True
    assert _FakeMeterProvider.instances[-1].shutdown_called is True


@pytest.mark.asyncio
async def test_otlp_adapter_uses_http_exporters(monkeypatch) -> None:
    components = _fake_components()
    adapter = OTLPObservabilityAdapter(
        OTLPObservabilitySettings(
            endpoint="http://localhost:4318", protocol="http/protobuf"
        )
    )
    monkeypatch.setattr(
        OTLPObservabilityAdapter,
        "_import_components",
        lambda self: components,
    )
    await adapter.init()
    metric_exporter = _FakeMetricExporter.instances[-1]
    assert metric_exporter.kwargs["endpoint"] == "http://localhost:4318"


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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otlp_adapter_includes_release_in_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init() adds service.version to resource_attrs when release is set (line 86)."""
    resource_attrs_captured: list[dict] = []
    base = _fake_components()

    class CapturingResource:
        def __init__(self, attributes: dict) -> None:
            resource_attrs_captured.append(dict(attributes))

    components = _OTLPComponents(
        metrics_api=base.metrics_api,
        trace_api=base.trace_api,
        Resource=CapturingResource,
        TracerProvider=base.TracerProvider,
        BatchSpanProcessor=base.BatchSpanProcessor,
        MeterProvider=base.MeterProvider,
        MetricReader=base.MetricReader,
        grpc_span_exporter_cls=base.grpc_span_exporter_cls,
        grpc_metric_exporter_cls=base.grpc_metric_exporter_cls,
        http_span_exporter_cls=base.http_span_exporter_cls,
        http_metric_exporter_cls=base.http_metric_exporter_cls,
    )

    adapter = OTLPObservabilityAdapter(OTLPObservabilitySettings(release="v1.2.3"))
    monkeypatch.setattr(
        OTLPObservabilityAdapter,
        "_import_components",
        lambda self: components,
    )
    await adapter.init()

    assert resource_attrs_captured
    assert resource_attrs_captured[0].get("service.version") == "v1.2.3"


@pytest.mark.asyncio
async def test_otlp_import_components_returns_otlp_components() -> None:
    """_import_components() returns _OTLPComponents when all deps available (line 183)."""
    # OTLP SDK + exporter subpackages are optional in slim CI; skip when absent
    # rather than failing with LifecycleError("opentelemetry-sdk-missing").
    pytest.importorskip("opentelemetry.sdk.trace")
    pytest.importorskip("opentelemetry.sdk.metrics")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    adapter = OTLPObservabilityAdapter(OTLPObservabilitySettings())
    components = adapter._import_components()
    assert isinstance(components, _OTLPComponents)


# ---------------------------------------------------------------------------
# insecure — scheme-driven transport selection
# ---------------------------------------------------------------------------
#
# The gRPC OTLP exporters resolve their transport like this:
#
#     parsed_url = urlparse(self._endpoint)
#     if parsed_url.scheme == "https":
#         insecure = False
#     insecure_exporter = environ.get("OTEL_EXPORTER_OTLP_INSECURE")
#     if insecure is None:
#         if insecure_exporter is not None:
#             insecure = insecure_exporter.lower() == "true"
#         else:
#             insecure = parsed_url.scheme == "http"
#
# So the scheme decides only while `insecure` is unset (None). An explicit
# False *overrides* that inference and forces a TLS channel — which fails the
# handshake against a plaintext collector on 127.0.0.1:4317. The default
# therefore has to stay None.
#
# Note the asymmetry: an https:// endpoint is forced to TLS *before* the
# explicit value is consulted, so `insecure=True` cannot open a plaintext
# channel to an https:// endpoint. That is SDK behaviour, not ours.
#
# The SDK exposes no public accessor for the resolved transport, so these
# tests assert on the private `_insecure` attribute.


def _grpc_metric_exporter_cls() -> Any:
    """Return the real gRPC metric exporter class, skipping if unavailable."""
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.metric_exporter")
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
        OTLPMetricExporter,
    )

    return OTLPMetricExporter


def _build_metric_exporter(
    settings: OTLPObservabilitySettings,
) -> Any:
    """Build the metric exporter the adapter would construct for `settings`."""
    exporter_cls = _grpc_metric_exporter_cls()
    components = _fake_components()
    components.grpc_metric_exporter_cls = exporter_cls
    adapter = OTLPObservabilityAdapter(settings)
    return adapter._create_metric_exporter(components)


def test_insecure_default_is_unset() -> None:
    """The default must leave the transport to the exporter's scheme inference."""
    assert OTLPObservabilitySettings().insecure is None


def test_grpc_exporter_default_is_plaintext_for_http_endpoint() -> None:
    """Default settings + an http:// endpoint must yield a plaintext channel."""
    exporter = _build_metric_exporter(OTLPObservabilitySettings())

    assert exporter._insecure is True


def test_grpc_exporter_default_is_tls_for_https_endpoint() -> None:
    """Default settings + an https:// endpoint must yield a TLS channel."""
    exporter = _build_metric_exporter(
        OTLPObservabilitySettings(endpoint="https://collector:4317")
    )

    assert exporter._insecure is False


def test_grpc_exporter_explicit_insecure_true_forces_plaintext() -> None:
    """An explicit `insecure=True` still forces plaintext."""
    exporter = _build_metric_exporter(
        OTLPObservabilitySettings(endpoint="http://localhost:4317", insecure=True)
    )

    assert exporter._insecure is True


def test_grpc_exporter_explicit_insecure_false_forces_tls() -> None:
    """An explicit `insecure=False` still forces TLS over an http:// endpoint.

    This is the assertion that proves the explicit value survives the default
    change: the unset default would have chosen plaintext here.
    """
    exporter = _build_metric_exporter(
        OTLPObservabilitySettings(endpoint="http://collector:4317", insecure=False)
    )

    assert exporter._insecure is False


def test_https_endpoint_forces_tls_even_with_insecure_true() -> None:
    """An https:// endpoint is pinned to TLS by the SDK.

    The exporter sets `insecure = False` for the https scheme before it
    consults the explicit value, so `insecure=True` cannot open a plaintext
    channel to an https:// endpoint. Pinned so the SDK behaviour is visible
    rather than surprising.
    """
    exporter = _build_metric_exporter(
        OTLPObservabilitySettings(endpoint="https://collector:4317", insecure=True)
    )

    assert exporter._insecure is False


def test_insecure_env_var_is_honoured_when_the_field_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`OTEL_EXPORTER_OTLP_INSECURE` applies while `insecure` is unset.

    Leaving the field at None lets the operator steer the transport from the
    environment; an explicit field value wins over the variable.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", "false")
    exporter = _build_metric_exporter(
        OTLPObservabilitySettings(endpoint="http://localhost:4317")
    )
    assert exporter._insecure is False

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", "true")
    exporter = _build_metric_exporter(
        OTLPObservabilitySettings(endpoint="http://localhost:4317", insecure=False)
    )
    assert exporter._insecure is False


@pytest.mark.asyncio
async def test_otlp_adapter_passes_insecure_through_to_grpc_exporters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter hands the (possibly unset) value to the gRPC exporters."""
    components = _fake_components()
    adapter = OTLPObservabilityAdapter(OTLPObservabilitySettings())
    monkeypatch.setattr(
        OTLPObservabilityAdapter,
        "_import_components",
        lambda self: components,
    )
    await adapter.init()

    assert _FakeSpanExporter.instances[-1].kwargs["insecure"] is None
    assert _FakeMetricExporter.instances[-1].kwargs["insecure"] is None


def test_http_exporters_are_built_without_an_insecure_kwarg() -> None:
    """The HTTP/protobuf exporters have no `insecure` parameter.

    Passing one raises `TypeError: OTLPMetricExporter.__init__() got an
    unexpected keyword argument 'insecure'`, so the adapter must omit it for
    the `http/protobuf` protocol. Built with the real SDK classes so the
    signature mismatch surfaces here rather than at runtime.
    """
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.metric_exporter")
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter as HttpMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as HttpSpanExporter,
    )

    components = _fake_components()
    components.http_span_exporter_cls = HttpSpanExporter
    components.http_metric_exporter_cls = HttpMetricExporter
    adapter = OTLPObservabilityAdapter(
        OTLPObservabilitySettings(
            endpoint="http://localhost:4318", protocol="http/protobuf"
        )
    )

    assert adapter._create_span_exporter(components) is not None
    assert adapter._create_metric_exporter(components) is not None


# ---------------------------------------------------------------------------
# Plaintext-transport guard
# ---------------------------------------------------------------------------
#
# An `http://` endpoint resolves to a *plaintext* channel, so telemetry
# (metric names, labels, resource attributes) would leave the host in the
# clear. A loopback collector — the default endpoint, and the whole point of
# the substrate — needs no opt-in; a remote collector does.


@pytest.fixture(autouse=True)
def _clear_insecure_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the guard hermetic.

    `OTEL_EXPORTER_OTLP_INSECURE` steers the transport whenever `insecure` is
    unset, so an ambient value in the developer's shell would change the
    outcome of these tests. Tests that care about the variable set it
    themselves.
    """
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_INSECURE", raising=False)


def test_default_endpoint_is_loopback_and_accepted() -> None:
    """The default endpoint (127.0.0.1) is plaintext but loopback."""
    settings = OTLPObservabilitySettings()

    assert settings.endpoint == "http://127.0.0.1:4317"
    assert settings.allow_insecure is False


def test_loopback_http_endpoint_accepted_without_opt_in() -> None:
    """A loopback collector needs no opt-in — the substrate case."""
    settings = OTLPObservabilitySettings(endpoint="http://localhost:4317")

    assert settings.allow_insecure is False


def test_non_loopback_http_endpoint_rejected_by_default() -> None:
    """A remote plaintext collector is rejected without an explicit opt-in."""
    with pytest.raises(ValueError, match="allow_insecure=True"):
        OTLPObservabilitySettings(endpoint="http://collector.example.com:4317")


def test_non_loopback_http_endpoint_accepted_with_allow_insecure() -> None:
    """`allow_insecure=True` is the explicit opt-in for a remote plaintext."""
    settings = OTLPObservabilitySettings(
        endpoint="http://collector.example.com:4317", allow_insecure=True
    )

    assert settings.allow_insecure is True


def test_non_loopback_https_endpoint_accepted_without_opt_in() -> None:
    """An https:// endpoint is TLS, so no opt-in is needed."""
    settings = OTLPObservabilitySettings(endpoint="https://collector.example.com:4317")

    assert settings.allow_insecure is False


def test_non_loopback_http_endpoint_with_insecure_false_accepted() -> None:
    """`insecure=False` forces TLS, so nothing is sent in the clear."""
    settings = OTLPObservabilitySettings(
        endpoint="http://collector.example.com:4317", insecure=False
    )

    assert settings.insecure is False


def test_insecure_true_alone_does_not_bypass_the_plaintext_guard() -> None:
    """`insecure=True` selects the transport; it does not grant the exception.

    There is exactly one way in — `allow_insecure=True` — so the policy knob
    is greppable and cannot be flipped by accident alongside a transport
    tweak.
    """
    with pytest.raises(ValueError, match="allow_insecure=True"):
        OTLPObservabilitySettings(
            endpoint="http://collector.example.com:4317", insecure=True
        )


def test_plaintext_guard_applies_to_http_protobuf_protocol() -> None:
    """The guard lives on the shared settings model, so both protocols hit it."""
    with pytest.raises(ValueError, match="allow_insecure=True"):
        OTLPObservabilitySettings(
            endpoint="http://collector.example.com:4318", protocol="http/protobuf"
        )

    with pytest.raises(ValueError, match="allow_insecure=True"):
        OTLPObservabilitySettings(
            endpoint="http://collector.example.com:4317", protocol="grpc"
        )


def test_bare_host_port_endpoint_is_not_rejected() -> None:
    """A scheme-less `host:port` endpoint is TLS to the SDK, so it is allowed.

    `urlparse("collector.example.com:4317")` reports no `http` scheme, so the
    exporter resolves `insecure = (scheme == "http")` -> False and opens a
    TLS channel. The guard must agree rather than reject a secure config.
    """
    settings = OTLPObservabilitySettings(endpoint="collector.example.com:4317")

    assert settings.endpoint == "collector.example.com:4317"


def test_insecure_env_var_does_not_bypass_the_plaintext_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment variable cannot bypass the guard.

    `OTEL_EXPORTER_OTLP_INSECURE=true` makes the exporter open a plaintext
    channel, so it must not be a way around the opt-in.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", "true")

    with pytest.raises(ValueError, match="allow_insecure=True"):
        OTLPObservabilitySettings(endpoint="http://collector.example.com:4317")

    settings = OTLPObservabilitySettings(
        endpoint="http://collector.example.com:4317", allow_insecure=True
    )
    assert settings.allow_insecure is True


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",  # AWS / Azure IMDS
        "169.254.169.253",  # AWS IMDS alt
        "100.100.100.200",  # Alibaba Cloud IMDS
        "metadata.google.internal",
        "metadata.azure.com",
    ],
)
def test_metadata_endpoint_rejected_even_with_allow_insecure(host: str) -> None:
    """A cloud metadata service is never a valid OTLP target.

    The opt-in covers a plaintext *collector*; it does not permit pivoting
    the exporter at a metadata endpoint.
    """
    with pytest.raises(ValueError, match="cloud metadata endpoint"):
        OTLPObservabilitySettings(endpoint=f"http://{host}:4317", allow_insecure=True)


def test_rfc1918_host_is_allowed_with_allow_insecure() -> None:
    """An internal collector on 10.x is a legitimate destination.

    Unlike an LLM gateway, an OTLP collector is routinely deployed on a
    private address, so RFC1918 ranges are deliberately *not* blocked here.
    """
    settings = OTLPObservabilitySettings(
        endpoint="http://10.0.0.5:4317", allow_insecure=True
    )

    assert settings.endpoint == "http://10.0.0.5:4317"
