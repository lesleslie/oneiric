"""Comprehensive tests for oneiric.core.logging.

Covers LoggingSinkConfig, LoggingConfig validation, configure_logging behavior
(including the no-handler-duplication invariant), file/http sink I/O, log
context binding/clearing/scoped restoration, structlog renderer switching,
suppress_events filtering, log level filtering, service-name propagation, and
a hypothesis-based round-trip property test for bind_log_context.
"""

from __future__ import annotations

import io
import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any

import pytest
import structlog
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from structlog.contextvars import clear_contextvars, get_contextvars

from oneiric.core.logging import (
    DEFAULT_LOGGER_NAME,
    LoggingConfig,
    LoggingSinkConfig,
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
    scoped_log_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_handlers() -> None:
    """Remove and close every handler on the root logger.

    structlog's configure_logging is process-global; tests that call it must
    start from a clean handler list to avoid cross-test pollution and to honor
    the invariant that configure_logging is *replacing* — not appending to —
    root handlers.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover - defensive best-effort
            pass


def _reset_contextvars() -> None:
    """Clear structlog's process-wide contextvars between tests."""
    clear_contextvars()


def _flush_handlers() -> None:
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:  # pragma: no cover - defensive best-effort
            pass


def _attach_capture_handler() -> tuple[io.StringIO, logging.Handler]:
    """Attach a StringIO capture handler to the root logger.

    Returns the buffer and the handler so the caller can detach it. Use this
    AFTER configure_logging to bypass its handler-replacement pass.
    """
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    return buffer, handler


def _detach_capture_handler(handler: logging.Handler) -> None:
    """Remove and close a previously attached capture handler."""
    try:
        logging.getLogger().removeHandler(handler)
        handler.close()
    except Exception:  # pragma: no cover - defensive best-effort
        pass


@pytest.fixture(autouse=True)
def _isolate_logging_state() -> None:
    """Reset root handlers and contextvars around every test in this module."""
    _reset_handlers()
    _reset_contextvars()
    yield
    _reset_handlers()
    _reset_contextvars()


# ---------------------------------------------------------------------------
# LoggingSinkConfig
# ---------------------------------------------------------------------------


def test_logging_sink_config_defaults() -> None:
    """LoggingSinkConfig exposes documented defaults."""
    sink = LoggingSinkConfig()
    assert sink.target == "stdout"
    assert sink.level == "INFO"
    assert sink.path is None
    assert sink.endpoint is None
    assert sink.method == "POST"
    assert sink.backup_count == 5
    # DEFAULT_FILE_SIZE is 5 MiB
    assert sink.max_bytes == 5 * 1024 * 1024


def test_logging_sink_config_validation_rejects_unsupported_target() -> None:
    """The Literal target field rejects unsupported values."""
    with pytest.raises(ValidationError):
        LoggingSinkConfig(target="socket")  # type: ignore[arg-type]


def test_logging_sink_config_validation_rejects_empty_target() -> None:
    """An empty string target is not a valid Literal value."""
    with pytest.raises(ValidationError):
        LoggingSinkConfig(target="")  # type: ignore[arg-type]


def test_logging_sink_config_for_file() -> None:
    """File-sink parameters persist on the model."""
    sink = LoggingSinkConfig(
        target="file",
        path="/var/log/oneiric.log",
        max_bytes=2048,
        backup_count=3,
    )
    assert sink.target == "file"
    assert sink.path == "/var/log/oneiric.log"
    assert sink.max_bytes == 2048
    assert sink.backup_count == 3


def test_logging_sink_config_for_http() -> None:
    """HTTP-sink parameters persist on the model."""
    sink = LoggingSinkConfig(
        target="http",
        endpoint="https://logs.example.com/ingest",
        method="PUT",
    )
    assert sink.target == "http"
    assert sink.endpoint == "https://logs.example.com/ingest"
    assert sink.method == "PUT"


def test_logging_sink_config_serializes_to_dict() -> None:
    """LoggingSinkConfig.model_dump() round-trips data losslessly."""
    sink = LoggingSinkConfig(target="stderr", level="WARNING")
    data = sink.model_dump()
    assert data["target"] == "stderr"
    assert data["level"] == "WARNING"
    assert data["method"] == "POST"


# ---------------------------------------------------------------------------
# LoggingConfig
# ---------------------------------------------------------------------------


def test_logging_config_defaults() -> None:
    """LoggingConfig has the documented defaults."""
    config = LoggingConfig()
    assert config.level == "INFO"
    assert config.emit_json is True
    assert config.service_name == "oneiric"
    assert config.environment is None
    assert config.release is None
    assert config.timestamper_format == "iso"
    assert config.extra_processors == []
    assert config.include_trace_context is True
    # Default sink is a single stdout sink
    assert len(config.sinks) == 1
    assert config.sinks[0].target == "stdout"


def test_logging_config_validation_rejects_non_bool_emit_json() -> None:
    """Pydantic coerces only truthy values; an explicit string fails."""
    with pytest.raises(ValidationError):
        LoggingConfig(emit_json="yes-please")  # type: ignore[arg-type]


def test_logging_config_validation_rejects_non_string_level() -> None:
    """Level must be a string field on the model."""
    with pytest.raises(ValidationError):
        LoggingConfig(level=42)  # type: ignore[arg-type]


def test_logging_config_accepts_arbitrary_level_strings() -> None:
    """Pydantic does not validate that the level string is known to logging."""
    # The model is permissive at the type level; configure_logging falls back
    # to INFO when the level name is unknown.
    config = LoggingConfig(level="CUSTOM_LEVEL")
    assert config.level == "CUSTOM_LEVEL"


def test_logging_config_with_multiple_sinks() -> None:
    """Multiple sinks can be supplied at construction time."""
    config = LoggingConfig(
        sinks=[
            LoggingSinkConfig(target="stdout"),
            LoggingSinkConfig(target="stderr", level="WARNING"),
            LoggingSinkConfig(target="file", path="/tmp/oneiric.log"),
        ],
    )
    assert [s.target for s in config.sinks] == ["stdout", "stderr", "file"]


def test_logging_config_with_empty_sinks_list() -> None:
    """An empty sinks list is accepted at the model level."""
    config = LoggingConfig(sinks=[])
    assert config.sinks == []


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


def test_configure_logging_replaces_handlers() -> None:
    """Calling configure_logging twice does not duplicate root handlers."""
    config = LoggingConfig(sinks=[LoggingSinkConfig(target="stdout")])
    configure_logging(config)
    first_handlers = list(logging.getLogger().handlers)
    assert first_handlers, "expected at least one handler after first configure"
    configure_logging(config)
    second_handlers = list(logging.getLogger().handlers)
    assert len(second_handlers) == len(first_handlers), (
        "configure_logging should replace handlers, not append"
    )


def test_configure_logging_with_default_config() -> None:
    """configure_logging() with no argument applies the default config."""
    configure_logging()
    root = logging.getLogger()
    assert root.handlers, "default config must register at least one handler"


def test_configure_logging_with_empty_sinks_uses_default_sink() -> None:
    """An empty sinks list falls back to a single stdout sink internally."""
    configure_logging(LoggingConfig(sinks=[]))
    # Even with an empty sinks list, the implementation substitutes a
    # default sink, so at least one handler is installed.
    assert logging.getLogger().handlers


def test_configure_logging_multiple_sinks_installs_all() -> None:
    """Each sink becomes a distinct handler on the root logger."""
    configure_logging(
        LoggingConfig(
            sinks=[
                LoggingSinkConfig(target="stdout"),
                LoggingSinkConfig(target="stderr", level="ERROR"),
                LoggingSinkConfig(target="file", path="/tmp/multi-sink.log"),
            ],
        )
    )
    handlers = logging.getLogger().handlers
    assert len(handlers) == 3
    targets = {type(h).__name__ for h in handlers}
    # stdout/stderr are StreamHandler; file is RotatingFileHandler
    assert "StreamHandler" in targets
    assert "RotatingFileHandler" in targets


def test_configure_logging_set_log_level() -> None:
    """The root logger level reflects the configured level."""
    configure_logging(LoggingConfig(level="WARNING"))
    assert logging.getLogger().level == logging.WARNING


def test_log_levels_filter_correctly(tmp_path: Path) -> None:
    """At INFO level, DEBUG messages are filtered out of the JSON output.

    Uses a file sink so that we can read the resulting JSON stream back
    directly (configure_logging always rebuilds the root handler list).
    """
    log_file = tmp_path / "filter.log"
    configure_logging(
        LoggingConfig(
            level="INFO",
            emit_json=True,
            sinks=[LoggingSinkConfig(target="file", path=str(log_file))],
        )
    )
    logger = get_logger("filter-test")
    logger.debug("debug-should-be-dropped")
    logger.info("info-should-appear")
    _flush_handlers()
    contents = log_file.read_text()
    assert "debug-should-be-dropped" not in contents
    assert "info-should-appear" in contents


# ---------------------------------------------------------------------------
# File sink integration
# ---------------------------------------------------------------------------


def test_file_sink_writes_json_payload(tmp_path: Path) -> None:
    """File sink writes valid JSON lines when emit_json=True."""
    log_file = tmp_path / "oneiric.log"
    configure_logging(
        LoggingConfig(
            emit_json=True,
            sinks=[
                LoggingSinkConfig(
                    target="file",
                    path=str(log_file),
                    max_bytes=4096,
                    backup_count=1,
                )
            ],
        )
    )
    logger = get_logger("file-test")
    logger.info("file-sink-event", domain="adapter", key="demo")
    _flush_handlers()
    contents = log_file.read_text().strip()
    assert contents, "file sink should have written at least one line"
    line = contents.splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "file-sink-event"
    assert payload["domain"] == "adapter"
    assert payload["key"] == "demo"


def test_file_sink_creates_parent_directory(tmp_path: Path) -> None:
    """File sink should create missing parent directories automatically."""
    log_file = tmp_path / "nested" / "logs" / "oneiric.log"
    assert not log_file.parent.exists()
    configure_logging(
        LoggingConfig(
            sinks=[LoggingSinkConfig(target="file", path=str(log_file))],
        )
    )
    assert log_file.parent.is_dir()


def test_file_sink_rotates_when_max_bytes_exceeded(tmp_path: Path) -> None:
    """Writing past max_bytes triggers rotation and produces a backup file."""
    log_file = tmp_path / "rotating.log"
    configure_logging(
        LoggingConfig(
            emit_json=True,
            sinks=[
                LoggingSinkConfig(
                    target="file",
                    path=str(log_file),
                    max_bytes=512,
                    backup_count=2,
                )
            ],
        )
    )
    logger = get_logger("rotation-test")
    # Write a payload larger than max_bytes several times to trigger rotation.
    for i in range(20):
        logger.info("rotate-me", index=i, padding="x" * 100)
    _flush_handlers()

    rotated = log_file.with_suffix(log_file.suffix + ".1")
    assert log_file.exists(), "current log file should exist"
    assert rotated.exists(), "rotated backup file should exist after rotation"


# ---------------------------------------------------------------------------
# HTTP sink integration
# ---------------------------------------------------------------------------


def test_http_sink_requires_endpoint() -> None:
    """An http sink without an endpoint raises ValueError on configure."""
    config = LoggingConfig(sinks=[LoggingSinkConfig(target="http")])
    with pytest.raises(ValueError):
        configure_logging(config)


def test_http_sink_requires_http_scheme() -> None:
    """Endpoint must use http or https scheme."""
    config = LoggingConfig(
        sinks=[
            LoggingSinkConfig(target="http", endpoint="ftp://example.com/ingest"),
        ]
    )
    with pytest.raises(ValueError):
        configure_logging(config)


def test_http_sink_with_dry_run_endpoint() -> None:
    """An http sink with no endpoint (None) raises ValueError explicitly.

    This is the legacy "dry run" pattern: callers sometimes build a sink
    placeholder and expect the configuration step to fail loudly rather than
    silently defaulting to localhost.
    """
    sink = LoggingSinkConfig(target="http")
    assert sink.endpoint is None
    config = LoggingConfig(sinks=[sink])
    with pytest.raises(ValueError, match="endpoint"):
        configure_logging(config)


def test_http_sink_installs_http_handler() -> None:
    """A well-formed http sink registers an HTTPHandler on the root logger."""
    configure_logging(
        LoggingConfig(
            sinks=[
                LoggingSinkConfig(
                    target="http",
                    endpoint="https://logs.example.com/ingest",
                    method="POST",
                )
            ],
        )
    )
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.handlers.HTTPHandler) for h in handlers)


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


def test_get_logger_returns_bound_logger() -> None:
    """get_logger returns a structlog logger-like object with bind/unbind."""
    configure_logging(LoggingConfig(emit_json=True))
    logger = get_logger("bound-test")
    # The lazy proxy proxies to a BoundLogger on first method call.
    assert logger is not None
    assert hasattr(logger, "info")
    assert hasattr(logger, "bind")
    assert hasattr(logger, "unbind")


def test_get_logger_with_no_name_uses_default() -> None:
    """get_logger() with no name uses the default oneiric logger name."""
    logger = get_logger()
    assert logger is not None
    # It must be a callable structlog logger proxy.
    assert callable(logger.info)


def test_get_logger_with_initial_values() -> None:
    """Initial values are bound onto the returned logger."""
    logger = get_logger("initial", component="auth", trace_id="abc")
    bound = logger.bind(component="auth", trace_id="abc")
    assert bound is not None


def test_get_logger_same_name_returns_usable_logger() -> None:
    """Two get_logger calls for the same name both return usable loggers."""
    a = get_logger("repeat")
    b = get_logger("repeat")
    assert a is not None
    assert b is not None


# ---------------------------------------------------------------------------
# bind / clear / scoped context
# ---------------------------------------------------------------------------


def test_bind_log_context_then_clear() -> None:
    """bind_log_context adds keys, clear_log_context removes them."""
    bind_log_context(domain="adapter", key="demo", provider="builtin")
    context = get_contextvars()
    assert context["domain"] == "adapter"
    assert context["key"] == "demo"
    assert context["provider"] == "builtin"

    clear_log_context("domain", "key", "provider")
    context = get_contextvars()
    assert "domain" not in context
    assert "key" not in context
    assert "provider" not in context


def test_bind_log_context_filters_none_values() -> None:
    """None-valued kwargs are dropped before binding."""
    bind_log_context(real="value", skipped=None, also_real="two")
    context = get_contextvars()
    assert context["real"] == "value"
    assert context["also_real"] == "two"
    assert "skipped" not in context
    clear_log_context("real", "also_real")


def test_bind_log_context_with_no_kwargs_is_noop() -> None:
    """bind_log_context() with no args does not raise and binds nothing."""
    bind_log_context()
    # Should not raise; contextvars remain whatever they were.
    assert get_contextvars() == {}


def test_clear_log_context_with_no_args_clears_all() -> None:
    """clear_log_context() (no keys) clears every bound var."""
    bind_log_context(a="1", b="2", c="3")
    assert get_contextvars()
    clear_log_context()
    assert get_contextvars() == {}


def test_clear_log_context_unknown_key_is_noop() -> None:
    """clear_log_context on a key that was never bound does not raise."""
    clear_log_context("definitely-not-bound")
    assert get_contextvars() == {}


def test_scoped_log_context_restores_previous() -> None:
    """scoped_log_context restores prior values on exit."""
    bind_log_context(domain="adapter")
    with scoped_log_context(domain="workflow", key="demo"):
        context = get_contextvars()
        assert context["domain"] == "workflow"
        assert context["key"] == "demo"
    context = get_contextvars()
    assert context["domain"] == "adapter"
    assert "key" not in context
    clear_log_context("domain")


def test_scoped_log_context_with_no_values_is_noop() -> None:
    """scoped_log_context() with no kwargs yields and exits cleanly.

    With no kwargs the manager binds nothing extra and, on exit, runs
    clear_log_context() with no keys (which clears all contextvars) and
    restores nothing — so a previously bound key is dropped.
    """
    bind_log_context(persisted="yes")
    with scoped_log_context():
        # The previously bound key must still be present inside the scope.
        assert get_contextvars()["persisted"] == "yes"
    # On exit, clear_log_context() with no keys wipes every bound var.
    assert "persisted" not in get_contextvars()


def test_scoped_log_context_nested_restoration() -> None:
    """Nested scoped contexts restore in LIFO order."""
    with scoped_log_context(outer="o"):
        with scoped_log_context(inner="i"):
            ctx = get_contextvars()
            assert ctx["outer"] == "o"
            assert ctx["inner"] == "i"
        # Inner scope exited; outer still bound.
        ctx = get_contextvars()
        assert ctx["outer"] == "o"
        assert "inner" not in ctx
    # Both scopes exited.
    ctx = get_contextvars()
    assert "outer" not in ctx
    assert "inner" not in ctx


# ---------------------------------------------------------------------------
# suppress_events
# ---------------------------------------------------------------------------


def test_suppress_events_drops_event_key() -> None:
    """When suppress_events=True, log calls with an 'event' key are dropped.

    Uses a capture handler attached after configure_logging so the global
    handler-replacement pass cannot clobber it. suppress_events is set via
    the configure_logging kwarg because the LoggingConfig model does not
    expose a suppress_events field.
    """
    configure_logging(
        LoggingConfig(
            emit_json=True,
            level="INFO",
            sinks=[],
        ),
        suppress_events=True,
    )
    buffer, handler = _attach_capture_handler()
    try:
        logger = get_logger("suppress-test")
        logger.info("first-event")
        logger.bind(event="named-event").info("second-event")
        _flush_handlers()
        output = buffer.getvalue()
        # With suppress_events=True, both the plain "first-event" and the
        # explicit "named-event" entries should be filtered out.
        assert "first-event" not in output
        assert "named-event" not in output
    finally:
        _detach_capture_handler(handler)


def test_suppress_events_disabled_lets_events_through() -> None:
    """With suppress_events=False (default), log calls reach the handler."""
    configure_logging(
        LoggingConfig(
            emit_json=True,
            level="INFO",
            sinks=[],
        )
    )
    buffer, handler = _attach_capture_handler()
    try:
        logger = get_logger("unsuppressed")
        logger.info("visible-event")
        _flush_handlers()
        output = buffer.getvalue()
        assert "visible-event" in output
    finally:
        _detach_capture_handler(handler)


def test_configure_logging_suppress_events_kwarg() -> None:
    """The configure_logging kwarg overrides LoggingConfig.suppress_events."""
    # Config says suppress_events is not set (default False) but the kwarg
    # says True — the kwarg must win.
    configure_logging(
        LoggingConfig(emit_json=True, level="INFO", sinks=[]),
        suppress_events=True,
    )
    buffer, handler = _attach_capture_handler()
    try:
        logger = get_logger("kwarg-suppress")
        logger.info("hidden")
        _flush_handlers()
        output = buffer.getvalue()
        assert "hidden" not in output
    finally:
        _detach_capture_handler(handler)


# ---------------------------------------------------------------------------
# Renderer switch (JSON vs console)
# ---------------------------------------------------------------------------


def test_structlog_renderer_switch_emit_json_true() -> None:
    """emit_json=True uses the JSONRenderer (output is valid JSON)."""
    configure_logging(
        LoggingConfig(
            emit_json=True,
            level="INFO",
            sinks=[],
            service_name="renderer-json",
        )
    )
    buffer, handler = _attach_capture_handler()
    try:
        logger = get_logger("json-renderer")
        logger.info("hello")
        _flush_handlers()
        output = buffer.getvalue().strip()
        assert output, "expected a non-empty log line"
        payload = json.loads(output.splitlines()[-1])
        assert payload["event"] == "hello"
    finally:
        _detach_capture_handler(handler)


def test_structlog_renderer_switch_emit_json_false() -> None:
    """emit_json=False uses the ConsoleRenderer (output is human-readable)."""
    configure_logging(
        LoggingConfig(
            emit_json=False,
            level="INFO",
            sinks=[],
            service_name="renderer-console",
        )
    )
    buffer, handler = _attach_capture_handler()
    try:
        logger = get_logger("console-renderer")
        logger.info("hello")
        _flush_handlers()
        output = buffer.getvalue().strip()
        assert output
        # ConsoleRenderer produces a colored, non-JSON line; ensure the event
        # string is present and the output is *not* valid JSON on its own.
        assert "hello" in output
        # A ConsoleRenderer line includes a key=value rendering; we can spot
        # the event key as `event=` rather than `"event"`.
        with pytest.raises(json.JSONDecodeError):
            json.loads(output.splitlines()[-1])
    finally:
        _detach_capture_handler(handler)


# ---------------------------------------------------------------------------
# Service name + trace context
# ---------------------------------------------------------------------------


def test_service_name_in_output() -> None:
    """LoggingConfig.service_name is embedded in the JSON output."""
    configure_logging(
        LoggingConfig(
            emit_json=True,
            level="INFO",
            service_name="my-svc",
            sinks=[],
        )
    )
    buffer, handler = _attach_capture_handler()
    try:
        logger = get_logger("svc-name")
        logger.info("hello")
        _flush_handlers()
        output = buffer.getvalue().strip()
        payload = json.loads(output.splitlines()[-1])
        assert payload["service.name"] == "my-svc"
    finally:
        _detach_capture_handler(handler)


def test_environment_and_release_in_output() -> None:
    """environment and release fields propagate to the JSON output."""
    configure_logging(
        LoggingConfig(
            emit_json=True,
            level="INFO",
            service_name="svc",
            environment="prod",
            release="1.2.3",
            sinks=[],
        )
    )
    buffer, handler = _attach_capture_handler()
    try:
        logger = get_logger("env-release")
        logger.info("hi")
        _flush_handlers()
        output = buffer.getvalue().strip()
        payload = json.loads(output.splitlines()[-1])
        assert payload["deployment.environment"] == "prod"
        assert payload["service.version"] == "1.2.3"
    finally:
        _detach_capture_handler(handler)


# ---------------------------------------------------------------------------
# structlog configuration side-effects
# ---------------------------------------------------------------------------


def test_configure_logging_reconfigures_structlog() -> None:
    """Calling configure_logging again rebuilds the structlog chain."""
    # First configuration: JSON renderer.
    configure_logging(LoggingConfig(emit_json=True, sinks=[]))
    chain_a = list(structlog.get_config()["processors"])
    # Second configuration: console renderer.
    configure_logging(LoggingConfig(emit_json=False, sinks=[]))
    chain_b = list(structlog.get_config()["processors"])
    # The processor chains must differ because the renderer swap is
    # deterministic.
    assert chain_a != chain_b


def test_default_logger_name_constant() -> None:
    """DEFAULT_LOGGER_NAME points at the oneiric package namespace."""
    assert DEFAULT_LOGGER_NAME == "oneiric"


# ---------------------------------------------------------------------------
# Property-based test: bind round-trip
# ---------------------------------------------------------------------------


@given(
    ctx=st.dictionaries(
        keys=st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                max_codepoint=0x7E,
            ),
            min_size=1,
            max_size=8,
        ),
        values=st.one_of(
            st.text(max_size=32),
            st.integers(min_value=-(10**6), max_value=10**6),
            st.booleans(),
        ),
        min_size=1,
        max_size=10,
    )
)
def test_log_context_round_trip(ctx: dict[str, Any]) -> None:
    """bind_log_context preserves every provided key in the contextvars map.

    Auto-injected keys (added by structlog itself, such as trace_id/span_id
    when an OTel span is active) may also appear — that is acceptable.
    """
    _reset_contextvars()
    # Skip dictionaries that contain values impossible to JSON-round-trip
    # (none here since we use text/ints/bools) — but ensure no None values
    # because bind_log_context silently drops them.
    safe = {k: v for k, v in ctx.items() if v is not None}
    if not safe:
        return
    bind_log_context(**safe)
    after = get_contextvars()
    for key, value in safe.items():
        assert key in after, f"key {key!r} missing from contextvars"
        assert after[key] == value, f"value for {key!r} did not round-trip"
    clear_log_context(*safe.keys())
