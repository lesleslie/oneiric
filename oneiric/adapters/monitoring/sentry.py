"""Sentry monitoring adapter."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

try:  # pragma: no cover - optional dependency import
    import sentry_sdk  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency import
    sentry_sdk = None  # type: ignore[assignment]


class SentryMonitoringSettings(BaseModel):
    """Configuration for the Sentry adapter."""

    dsn: SecretStr | None = Field(
        default=None,
        description="Sentry DSN; falls back to SENTRY_DSN env var when omitted.",
    )
    environment: str = Field(
        default="development", description="Deployment environment tag."
    )
    release: str | None = Field(
        default=None, description="Optional release identifier."
    )
    traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    profiles_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    enable_tracing: bool = Field(
        default=True, description="Toggle Sentry tracing pipelines."
    )
    attach_stacktrace: bool = Field(default=True)
    send_default_pii: bool = Field(default=False)


class SentryMonitoringAdapter:
    """Adapter that configures sentry-sdk with async-friendly cleanup."""

    metadata = AdapterMetadata(
        category="monitoring",
        provider="sentry",
        factory="oneiric.adapters.monitoring.sentry:SentryMonitoringAdapter",
        capabilities=["logging", "tracing", "errors"],
        stack_level=27,
        priority=210,
        source=CandidateSource.LOCAL_PKG,
        owner="Observability",
        requires_secrets=True,
        settings_model=SentryMonitoringSettings,
    )

    def __init__(self, settings: SentryMonitoringSettings | None = None) -> None:
        self._settings = settings or SentryMonitoringSettings()
        self._logger = get_logger("adapter.monitoring.sentry").bind(
            domain="adapter",
            key="monitoring",
            provider="sentry",
        )
        self._configured = False

    async def init(self) -> None:
        sdk = self._require_sdk()
        dsn = self._resolve_dsn()
        options: dict[str, Any] = {
            "dsn": dsn,
            "environment": self._settings.environment,
            "release": self._settings.release,
            "traces_sample_rate": self._settings.traces_sample_rate,
            "profiles_sample_rate": self._settings.profiles_sample_rate,
            "enable_tracing": self._settings.enable_tracing,
            "attach_stacktrace": self._settings.attach_stacktrace,
            "send_default_pii": self._settings.send_default_pii,
        }
        options = {k: v for k, v in options.items() if v is not None}
        try:
            sdk.init(**options)
        except Exception as exc:  # pragma: no cover - depends on sentry install
            raise LifecycleError("sentry-init-failed") from exc
        self._configured = True
        self._logger.info(
            "adapter-init", adapter="sentry", environment=self._settings.environment
        )

    async def health(self) -> bool:
        return self._configured

    async def cleanup(self) -> None:
        sdk = sentry_sdk
        if sdk is None:
            return
        flush: Callable[..., Any] | None = getattr(sdk, "flush", None)
        if callable(flush):
            await asyncio.to_thread(flush)
        shutdown: Callable[..., Any] | None = getattr(sdk, "shutdown", None)
        if callable(shutdown):  # pragma: no cover - defensive logging path
            await asyncio.to_thread(shutdown)
        self._configured = False
        self._logger.info("adapter-cleanup-complete", adapter="sentry")

    def _resolve_dsn(self) -> str:
        if self._settings.dsn:
            return self._settings.dsn.get_secret_value()
        env_dsn = os.getenv("SENTRY_DSN")
        if env_dsn:
            return env_dsn
        raise LifecycleError("sentry-dsn-missing")

    def _require_sdk(self) -> Any:
        if sentry_sdk is None:
            raise LifecycleError("sentry-sdk-missing")
        return sentry_sdk
