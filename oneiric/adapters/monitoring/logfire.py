"""Logfire monitoring adapter."""

from __future__ import annotations

import inspect
import os

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

try:  # pragma: no cover - optional dependency
    import logfire  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    logfire = None  # type: ignore[assignment]


class LogfireMonitoringSettings(BaseModel):
    token: SecretStr | None = Field(
        default=None,
        description="API token for Logfire; falls back to LOGFIRE_TOKEN env var.",
    )
    service_name: str = Field(
        default="oneiric",
        description="Service name reported to Logfire.",
    )
    environment: str | None = Field(
        default=None,
        description="Optional deployment environment tag.",
    )
    release: str | None = Field(
        default=None,
        description="Optional release identifier.",
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Additional tags forwarded to Logfire when supported.",
    )
    enable_system_metrics: bool = True
    instrument_httpx: bool = True
    instrument_pydantic: bool = True


class LogfireMonitoringAdapter:
    metadata = AdapterMetadata(
        category="monitoring",
        provider="logfire",
        factory="oneiric.adapters.monitoring.logfire:LogfireMonitoringAdapter",
        capabilities=["logging", "metrics"],
        stack_level=25,
        priority=200,
        source=CandidateSource.LOCAL_PKG,
        owner="Observability",
        requires_secrets=True,
        settings_model=LogfireMonitoringSettings,
    )

    def __init__(self, settings: LogfireMonitoringSettings | None = None) -> None:
        self._settings = settings or LogfireMonitoringSettings()
        self._logger = get_logger("adapter.monitoring.logfire").bind(
            domain="adapter",
            key="monitoring",
            provider="logfire",
        )
        self._configured = False

    async def init(self) -> None:
        if logfire is None:  # pragma: no cover - depends on optional import
            raise LifecycleError("logfire-not-installed")
        token = self._resolve_token()
        try:
            kwargs = self._build_config_kwargs(token)
            logfire.configure(**kwargs)
            self._maybe_call(
                "instrument_system_metrics", self._settings.enable_system_metrics
            )
            self._maybe_call("instrument_httpx", self._settings.instrument_httpx)
            self._maybe_call("instrument_pydantic", self._settings.instrument_pydantic)
            self._configured = True
            self._logger.info("logfire-configured", service=self._settings.service_name)
        except Exception as exc:  # pragma: no cover - depends on logfire internals
            raise LifecycleError("logfire-config-failed") from exc

    async def health(self) -> bool:
        return self._configured

    async def cleanup(self) -> None:
        if logfire is None:
            return
        shutdown = getattr(logfire, "shutdown", None)
        if callable(shutdown):  # pragma: no branch
            shutdown()
        self._configured = False
        self._logger.info("adapter-cleanup-complete", adapter="logfire")

    def _resolve_token(self) -> str:
        if self._settings.token:
            return self._settings.token.get_secret_value()
        env_token = os.getenv("LOGFIRE_TOKEN")
        if env_token:
            return env_token
        raise LifecycleError("logfire-token-missing")

    def _maybe_call(self, name: str, enabled: bool) -> None:
        if not enabled:
            return
        if logfire is None:  # pragma: no cover - optional dependency
            return
        func = getattr(logfire, name, None)
        if callable(func):
            func()

    def _build_config_kwargs(self, token: str) -> dict[str, object]:
        base_tags = dict(self._settings.tags or {})
        if self._settings.environment:
            base_tags.setdefault("deployment.environment", self._settings.environment)
        if self._settings.release:
            base_tags.setdefault("service.version", self._settings.release)
        kwargs: dict[str, object] = {
            "token": token,
            "service_name": self._settings.service_name,
        }
        if base_tags:
            kwargs["tags"] = base_tags
        configure = getattr(logfire, "configure", None)
        if not callable(configure):
            return kwargs
        try:
            params = inspect.signature(configure).parameters
        except (TypeError, ValueError):
            return kwargs
        return {key: value for key, value in kwargs.items() if key in params}
