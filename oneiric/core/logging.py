"""Structured logging helpers with configurable sinks + OTel context."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlparse

import structlog
from opentelemetry import trace
from pydantic import BaseModel, Field
from structlog.contextvars import bind_contextvars, clear_contextvars, unbind_contextvars
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
    path: Optional[str] = Field(default=None, description="File path when target=file.")
    max_bytes: int = Field(
        default=DEFAULT_FILE_SIZE,
        description="Max bytes for rotating file handler (target=file).",
    )
    backup_count: int = Field(
        default=5,
        description="Number of rotated files to keep (target=file).",
    )
    endpoint: Optional[str] = Field(
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


def _otel_context_processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    span = trace.get_current_span()
    context = span.get_span_context()
    if context and context.is_valid:
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


def _build_handlers(cfg: LoggingConfig) -> list[logging.Handler]:
    sinks = cfg.sinks or [LoggingSinkConfig()]
    handlers: list[logging.Handler] = []
    for sink in sinks:
        target = sink.target
        if target == "stdout":
            handler: logging.Handler = logging.StreamHandler(sys.stdout)
        elif target == "stderr":
            handler = logging.StreamHandler(sys.stderr)
        elif target == "file":
            path = Path(sink.path or "oneiric.log")
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=max(sink.max_bytes, 1024),
                backupCount=max(sink.backup_count, 1),
                encoding="utf-8",
            )
        elif target == "http":
            if not sink.endpoint:
                raise ValueError("HTTP sink requires 'endpoint'.")
            parsed = urlparse(sink.endpoint)
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("HTTP sink endpoint must be http(s).")
            host = parsed.netloc
            url = parsed.path or "/"
            handler = logging.handlers.HTTPHandler(
                host,
                url,
                method=(sink.method or "POST").upper(),
                secure=parsed.scheme == "https",
            )
        else:
            raise ValueError(f"Unsupported logging target: {target}")

        handler.setLevel(getattr(logging, sink.level.upper(), logging.INFO))
        handler.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(handler)
    return handlers


def configure_logging(config: Optional[LoggingConfig] = None) -> None:
    """Configure structlog and the stdlib logging bridge."""

    cfg = config or LoggingConfig()

    timestamper = structlog.processors.TimeStamper(fmt=cfg.timestamper_format)
    processor_chain: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
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
    logging.basicConfig(level=getattr(logging, cfg.level.upper(), logging.INFO), handlers=handlers, force=True)

    structlog.configure(
        processors=processor_chain,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, cfg.level.upper(), logging.INFO)),
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


def get_logger(name: Optional[str] = None, **initial_values: Any) -> BoundLogger:
    """Return a structlog bound logger configured for the service."""

    logger = structlog.get_logger(name or DEFAULT_LOGGER_NAME)
    if initial_values:
        return logger.bind(**initial_values)
    return logger
