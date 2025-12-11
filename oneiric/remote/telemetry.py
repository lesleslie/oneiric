"""Telemetry helpers for remote refresh loops."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oneiric.core.logging import get_logger

TELEMETRY_FILENAME = "remote_status.json"
telemetry_logger = get_logger("remote.telemetry")


@dataclass
class RemoteSyncTelemetry:
    last_success_at: str | None = None
    last_failure_at: str | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    last_source: str | None = None
    last_registered: int | None = None
    last_duration_ms: float | None = None
    last_digest_checks: int | None = None
    last_per_domain: dict[str, int] = None  # type: ignore[assignment]
    last_skipped: int | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("last_per_domain") is None:
            data["last_per_domain"] = {}
        return data


def load_remote_telemetry(cache_dir: str) -> RemoteSyncTelemetry:
    path = _telemetry_path(cache_dir)
    if not path.exists():
        return RemoteSyncTelemetry()
    try:
        return RemoteSyncTelemetry(**json.loads(path.read_text()))
    except Exception:
        return RemoteSyncTelemetry()


def record_remote_success(
    cache_dir: str,
    *,
    source: str,
    registered: int,
    duration_ms: float | None = None,
    digest_checks: int | None = None,
    per_domain: dict[str, int] | None = None,
    skipped: int | None = None,
) -> None:
    telemetry = load_remote_telemetry(cache_dir)
    telemetry.last_success_at = _timestamp()
    telemetry.last_source = source
    telemetry.last_registered = registered
    telemetry.last_error = None
    telemetry.consecutive_failures = 0
    telemetry.last_duration_ms = duration_ms
    telemetry.last_digest_checks = digest_checks
    telemetry.last_per_domain = per_domain or {}
    telemetry.last_skipped = skipped
    _write(cache_dir, telemetry)
    telemetry_logger.info(
        "remote-telemetry-success",
        cache=cache_dir,
        last_success_at=telemetry.last_success_at,
        source=source,
        registered=registered,
        duration_ms=duration_ms,
        digest_checks=digest_checks,
        per_domain=telemetry.last_per_domain,
        skipped=skipped,
    )


def record_remote_failure(cache_dir: str, error: str) -> None:
    telemetry = load_remote_telemetry(cache_dir)
    telemetry.last_failure_at = _timestamp()
    telemetry.last_error = error
    telemetry.consecutive_failures += 1
    _write(cache_dir, telemetry)
    telemetry_logger.warning(
        "remote-telemetry-failure",
        cache=cache_dir,
        last_failure_at=telemetry.last_failure_at,
        error=error,
        consecutive_failures=telemetry.consecutive_failures,
    )


def _write(cache_dir: str, telemetry: RemoteSyncTelemetry) -> None:
    path = _telemetry_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(telemetry.as_dict()))
    tmp_path.replace(path)


def _telemetry_path(cache_dir: str) -> Path:
    return Path(cache_dir) / TELEMETRY_FILENAME


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
