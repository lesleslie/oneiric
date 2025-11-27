"""Tests for logging configuration helpers."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from structlog.contextvars import get_contextvars

from oneiric.core.logging import (
    LoggingConfig,
    LoggingSinkConfig,
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
)


def _flush_handlers() -> None:
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:  # pragma: no cover - defensive best-effort flush
            pass


def test_file_sink_writes_json_payload(tmp_path: Path) -> None:
    log_file = tmp_path / "oneiric.log"
    config = LoggingConfig(
        emit_json=True,
        sinks=[LoggingSinkConfig(target="file", path=str(log_file), max_bytes=4096, backup_count=1)],
    )
    configure_logging(config)
    logger = get_logger("test")
    logger.info("file-sink", domain="adapter", key="demo")
    _flush_handlers()
    contents = log_file.read_text().strip()
    assert "file-sink" in contents
    assert "\"domain\": \"adapter\"" in contents


def test_bind_and_clear_log_context() -> None:
    bind_log_context(domain="adapter", key="demo", provider="builtin")
    context = get_contextvars()
    assert context["domain"] == "adapter"
    assert context["key"] == "demo"
    clear_log_context("domain", "key", "provider")
    context = get_contextvars()
    assert "domain" not in context
    assert "key" not in context


def test_http_sink_requires_endpoint() -> None:
    config = LoggingConfig(sinks=[LoggingSinkConfig(target="http")])
    with pytest.raises(ValueError):
        configure_logging(config)
