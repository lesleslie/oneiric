"""Structured logging helpers with OpenTelemetry-friendly defaults."""

from __future__ import annotations

import logging
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from structlog.stdlib import BoundLogger

DEFAULT_LOGGER_NAME = "oneiric"


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


def _load_extra_processors(names: list[str]) -> list[Any]:
    extras: list[Any] = []
    for dotted in names:
        module_name, _, attr = dotted.rpartition(".")
        module = __import__(module_name, fromlist=[attr])
        extras.append(getattr(module, attr))
    return extras


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

    processor_chain.extend(_load_extra_processors(cfg.extra_processors))

    if cfg.emit_json:
        processor_chain.append(structlog.processors.JSONRenderer())
    else:
        processor_chain.append(structlog.dev.ConsoleRenderer())

    logging.basicConfig(level=getattr(logging, cfg.level))

    structlog.configure(
        processors=processor_chain,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, cfg.level)),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None, **initial_values: Any) -> BoundLogger:
    """Return a structlog bound logger configured for the service."""

    logger = structlog.get_logger(name or DEFAULT_LOGGER_NAME)
    if initial_values:
        return logger.bind(**initial_values)
    return logger
