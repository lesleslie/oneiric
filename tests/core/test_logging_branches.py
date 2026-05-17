from __future__ import annotations

import logging
from pathlib import Path

import pytest

from oneiric.core.logging import (
    LoggingConfig,
    LoggingSinkConfig,
    _add_service_metadata,
    _create_handler_for_target,
    _filter_event_logs,
    _load_extra_processors,
    configure_early_logging,
)


def test_create_handler_for_target_variants(tmp_path) -> None:
    stdout_handler = _create_handler_for_target(LoggingSinkConfig(target="stdout"))
    stderr_handler = _create_handler_for_target(LoggingSinkConfig(target="stderr"))
    file_handler = _create_handler_for_target(
        LoggingSinkConfig(target="file", path=str(tmp_path / "oneiric.log"))
    )
    http_handler = _create_handler_for_target(
        LoggingSinkConfig(target="http", endpoint="https://example.com/ingest")
    )

    assert isinstance(stdout_handler, logging.StreamHandler)
    assert isinstance(stderr_handler, logging.StreamHandler)
    assert file_handler.baseFilename.endswith("oneiric.log")
    assert isinstance(http_handler, logging.handlers.HTTPHandler)


def test_create_handler_for_target_invalid() -> None:
    with pytest.raises(ValueError, match="Unsupported logging target"):
        _create_handler_for_target(LoggingSinkConfig(target="stdout").model_copy(update={"target": "bogus"}))


def test_load_extra_processors_and_service_metadata(tmp_path, monkeypatch) -> None:
    module_path = tmp_path / "extra_logging.py"
    module_path.write_text(
        """
def processor(logger, method_name, event_dict):
    event_dict["extra"] = True
    return event_dict
"""
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    processors = _load_extra_processors(["extra_logging.processor"])
    assert len(processors) == 1
    assert processors[0](None, "info", {})["extra"] is True

    metadata_processor = _add_service_metadata(
        LoggingConfig(service_name="svc", environment="prod", release="1.2.3")
    )
    payload = metadata_processor(None, "info", {})
    assert payload["service.name"] == "svc"
    assert payload["deployment.environment"] == "prod"
    assert payload["service.version"] == "1.2.3"


def test_filter_event_logs_respects_suppression() -> None:
    configure_early_logging(True)
    try:
        assert _filter_event_logs(None, None, {"event": "demo"}) == {}
    finally:
        configure_early_logging(False)

    assert _filter_event_logs(None, None, {"event": "demo"}) == {"event": "demo"}
