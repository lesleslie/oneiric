"""Structured logging helpers with configurable sinks + OTel context."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import structlog
from opentelemetry import trace
from pydantic import BaseModel, Field
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    get_contextvars,
    unbind_contextvars,
)
from structlog.stdlib import BoundLogger

DEFAULT_LOGGER_NAME = "oneiric"
DEFAULT_FILE_SIZE = 5 * 1024 * 1024


class LoggingSinkConfig(BaseModel):
    """Declarative sink configuration for stdlib logging handlers."""

    target: Literal["stdout", "stderr", "file", "http"] = Field(
        default="stdout",
        description="Handler target (stdout/stderr/file/http).",
    )
    level: str = Field(default="INFO", description="Minimum level for this sink.")
    path: str | None = Field(default=None, description="File path when target=file.")
    max_bytes: int = Field(
        default=DEFAULT_FILE_SIZE,
        description="Max bytes for rotating file handler (target=file).",
    )
    backup_count: int = Field(
        default=5,
        description="Number of rotated files to keep (target=file).",
    )
    endpoint: str | None = Field(
        default=None,
        description="HTTP(S) endpoint when target=http (e.g., https://logs.local/ingest).",
    )
    method: str = Field(default="POST", description="HTTP method for HTTP sink.")


class LoggingConfig(BaseModel):
    """Configuration payload for structlog + stdlib logging."""

    level: str = Field(default="INFO", description="Root log level.")
    emit_json: bool = Field(
        default=True,
        description="Emit JSON logs suitable for log aggregation systems.",
    )
    service_name: str = Field(
        default="oneiric",
        description="Value for the service metadata field.",
    )
    environment: str | None = Field(
        default=None,
        description="Optional deployment environment tag.",
    )
    release: str | None = Field(
        default=None,
        description="Optional service release/version identifier.",
    )
    timestamper_format: str = Field(
        default="iso",
        description="structlog timestamper format hint.",
    )
    extra_processors: list[str] = Field(
        default_factory=list,
        description="Names of additional structlog processors to import and append.",
    )
    include_trace_context: bool = Field(
        default=True,
        description="Bind OpenTelemetry trace/span ids when available.",
    )
    sinks: list[LoggingSinkConfig] = Field(
        default_factory=lambda: [LoggingSinkConfig()],
        description="List of logging sink configurations.",
    )


def _otel_context_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    if (
        context := (span := trace.get_current_span()).get_span_context()
    ) and context.is_valid:
        event_dict.setdefault("trace_id", f"{context.trace_id:032x}")
        event_dict.setdefault("span_id", f"{context.span_id:016x}")
    return event_dict


def _load_extra_processors(names: list[str]) -> list[Any]:
    extras: list[Any] = []
    for dotted in names:
        module_name, _, attr = dotted.rpartition(".")
        module = __import__(module_name, fromlist=[attr])
        extras.append(getattr(module, attr))
    return extras


def _add_service_metadata(
    cfg: LoggingConfig,
) -> Callable[[Any, str, dict[str, Any]], dict[str, Any]]:
    def _processor(
        logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        event_dict.setdefault("service.name", cfg.service_name)
        if cfg.environment:
            event_dict.setdefault("deployment.environment", cfg.environment)
        if cfg.release:
            event_dict.setdefault("service.version", cfg.release)
        return event_dict

    return _processor


def _normalize_oneiric_tags(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    tag_map = {
        "domain": "oneiric.domain",
        "key": "oneiric.key",
        "provider": "oneiric.provider",
        "workflow": "oneiric.workflow",
        "run_id": "oneiric.run_id",
        "node": "oneiric.node",
        "event_topic": "oneiric.event.topic",
        "event_handler": "oneiric.event.handler",
        "operation": "oneiric.operation",
        "adapter": "oneiric.adapter",
        "category": "oneiric.category",
    }
    for source, target in tag_map.items():
        if source in event_dict and target not in event_dict:
            event_dict[target] = event_dict[source]
    return event_dict


def _build_handlers(cfg: LoggingConfig) -> list[logging.Handler]:
    sinks = cfg.sinks or [LoggingSinkConfig()]
    return [_create_handler(sink) for sink in sinks]


def _create_handler(sink: LoggingSinkConfig) -> logging.Handler:
    """Create a logging handler from sink configuration."""
    handler = _create_handler_for_target(sink)
    handler.setLevel(getattr(logging, sink.level.upper(), logging.INFO))
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def _create_handler_for_target(sink: LoggingSinkConfig) -> logging.Handler:
    """Create handler based on target type."""
    target = sink.target

    if target == "stdout":
        return logging.StreamHandler(sys.stdout)

    if target == "stderr":
        return logging.StreamHandler(sys.stderr)

    if target == "file":
        return _create_file_handler(sink)

    if target == "http":
        return _create_http_handler(sink)

    raise ValueError(f"Unsupported logging target: {target}")


def _create_file_handler(sink: LoggingSinkConfig) -> logging.Handler:
    """Create rotating file handler."""
    path = Path(sink.path or "oneiric.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    return logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max(sink.max_bytes, 1024),
        backupCount=max(sink.backup_count, 1),
        encoding="utf-8",
    )


def _create_http_handler(sink: LoggingSinkConfig) -> logging.Handler:
    """Create HTTP handler."""
    if not sink.endpoint:
        raise ValueError("HTTP sink requires 'endpoint'.")

    parsed = urlparse(sink.endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("HTTP sink endpoint must be http(s).")

    return logging.handlers.HTTPHandler(
        parsed.netloc,
        parsed.path or "/",
        method=(sink.method or "POST").upper(),
        secure=parsed.scheme == "https",
    )


def configure_logging(config: LoggingConfig | None = None) -> None:
    """Configure structlog and the stdlib logging bridge."""

    cfg = config or LoggingConfig()

    timestamper = structlog.processors.TimeStamper(fmt=cfg.timestamper_format)
    processor_chain: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        _add_service_metadata(cfg),
        _normalize_oneiric_tags,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if cfg.include_trace_context:
        processor_chain.append(_otel_context_processor)

    processor_chain.extend(_load_extra_processors(cfg.extra_processors))

    if cfg.emit_json:
        processor_chain.append(structlog.processors.JSONRenderer())
    else:
        processor_chain.append(structlog.dev.ConsoleRenderer())

    handlers = _build_handlers(cfg)
    logging.basicConfig(
        level=getattr(logging, cfg.level.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )

    structlog.configure(
        processors=processor_chain,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, cfg.level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def bind_log_context(**values: Any) -> None:
    """Bind structured context (domain/key/provider/etc.) for subsequent logs."""

    filtered = {key: value for key, value in values.items() if value is not None}
    if filtered:
        bind_contextvars(**filtered)


def clear_log_context(*keys: str) -> None:
    """Clear bound context for the provided keys (or all when empty)."""

    if keys:
        unbind_contextvars(*keys)
    else:
        clear_contextvars()


@contextmanager
def scoped_log_context(**values: Any) -> Any:
    """Bind structured context for a scope and restore prior values."""

    previous = get_contextvars()
    bind_log_context(**values)
    try:
        yield
    finally:
        keys = tuple(values.keys())
        clear_log_context(*keys)
        restore = {key: previous[key] for key in keys if key in previous}
        if restore:
            bind_contextvars(**restore)


def get_logger(name: str | None = None, **initial_values: Any) -> BoundLogger:
    """Return a structlog bound logger configured for the service."""

    logger = structlog.get_logger(name or DEFAULT_LOGGER_NAME)
    if initial_values:
        return logger.bind(**initial_values)
    return logger
