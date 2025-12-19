"""Lifecycle and hot-swap helpers."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .logging import get_logger
from .metrics import record_swap_duration
from .observability import observed_span
from .resolution import Candidate, Resolver
from .security import load_factory_allowlist, validate_factory_string

FactoryCallable = Callable[..., Any]
LifecycleHook = Callable[[Candidate, Any, Any | None], Awaitable[None] | None]
CleanupHook = Callable[[Any], Awaitable[None] | None]


class LifecycleError(RuntimeError):
    """Raised when activation or swap fails."""


@dataclass
class LifecycleHooks:
    pre_swap: list[LifecycleHook] = field(default_factory=list)
    post_swap: list[LifecycleHook] = field(default_factory=list)
    on_cleanup: list[CleanupHook] = field(default_factory=list)

    def add_pre_swap(self, hook: LifecycleHook) -> None:
        self.pre_swap.append(hook)

    def add_post_swap(self, hook: LifecycleHook) -> None:
        self.post_swap.append(hook)

    def add_cleanup(self, hook: CleanupHook) -> None:
        self.on_cleanup.append(hook)


@dataclass
class LifecycleSafetyOptions:
    """Runtime safety knobs for lifecycle operations."""

    activation_timeout: float = 30.0
    health_timeout: float = 5.0
    cleanup_timeout: float = 10.0
    hook_timeout: float = 5.0
    shield_tasks: bool = True
    max_swap_samples: int = 20


def resolve_factory(factory: str | FactoryCallable) -> FactoryCallable:
    """Resolve factory to callable with security validation.

    Args:
        factory: Either a callable or a string in format "module.path:function"

    Returns:
        Callable factory function

    Raises:
        LifecycleError: If factory string is invalid or blocked by security policy
    """
    if callable(factory):
        return factory

    # Validate factory string format and security policy
    allowed_prefixes = load_factory_allowlist()
    is_valid, error = validate_factory_string(factory, allowed_prefixes)
    if not is_valid:
        raise LifecycleError(f"Security validation failed: {error}")

    module_path, _, attr = factory.partition(":")
    if not attr:
        module_path, _, attr = factory.rpartition(".")
    if not module_path:
        raise LifecycleError(f"Cannot import factory from '{factory}'")

    try:
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        raise LifecycleError(f"Failed to load factory '{factory}': {exc}") from exc


@dataclass
class LifecycleStatus:
    domain: str
    key: str
    state: str = "unknown"
    current_provider: str | None = None
    pending_provider: str | None = None
    last_error: str | None = None
    last_state_change_at: datetime | None = None
    last_activated_at: datetime | None = None
    last_health_at: datetime | None = None
    last_swap_duration_ms: float | None = None
    recent_swap_durations_ms: list[float] = field(default_factory=list)
    successful_swaps: int = 0
    failed_swaps: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "key": self.key,
            "state": self.state,
            "current_provider": self.current_provider,
            "pending_provider": self.pending_provider,
            "last_error": self.last_error,
            "last_state_change_at": _isoformat(self.last_state_change_at),
            "last_activated_at": _isoformat(self.last_activated_at),
            "last_health_at": _isoformat(self.last_health_at),
            "last_swap_duration_ms": self.last_swap_duration_ms,
            "recent_swap_durations_ms": self.recent_swap_durations_ms.copy(),
            "successful_swaps": self.successful_swaps,
            "failed_swaps": self.failed_swaps,
        }


def _isoformat(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.isoformat()


def _now() -> datetime:
    return datetime.now(UTC)


_UNSET = object()


class LifecycleManager:
    """Instantiate and hot-swap resolver-backed candidates."""

    def __init__(
        self,
        resolver: Resolver,
        hooks: LifecycleHooks | None = None,
        *,
        status_snapshot_path: str | None = None,
        safety: LifecycleSafetyOptions | None = None,
    ) -> None:
        self.resolver = resolver
        self.hooks = hooks or LifecycleHooks()
        self._instances: dict[tuple[str, str], Any] = {}
        self._status: dict[tuple[str, str], LifecycleStatus] = {}
        self._status_snapshot_path = (
            Path(status_snapshot_path) if status_snapshot_path else None
        )
        self._logger = get_logger("lifecycle")
        self._safety = safety or LifecycleSafetyOptions()
        self._load_status_snapshot()

    async def activate(
        self,
        domain: str,
        key: str,
        provider: str | None = None,
        *,
        force: bool = False,
    ) -> Any:
        candidate = self._require_candidate(domain, key, provider)
        return await self._apply_candidate(candidate, force=force)

    async def swap(
        self,
        domain: str,
        key: str,
        provider: str | None = None,
        *,
        force: bool = False,
    ) -> Any:
        return await self.activate(domain, key, provider=provider, force=force)

    def get_instance(self, domain: str, key: str) -> Any | None:
        return self._instances.get((domain, key))

    def get_status(self, domain: str, key: str) -> LifecycleStatus | None:
        return self._status.get((domain, key))

    def all_statuses(self) -> list[LifecycleStatus]:
        return list(self._status.values())

    async def probe_instance_health(self, domain: str, key: str) -> bool | None:
        candidate = self.resolver.resolve(domain, key)
        instance = self.get_instance(domain, key)
        if not candidate or instance is None:
            return None
        checks = self._collect_health_checks(candidate, instance)
        if not checks:
            return True
        for check in checks:
            result = await self._maybe_with_protection(
                check(),
                timeout=self._safety.health_timeout,
                label=f"health probe {domain}:{key}",
            )
            if result is False:
                self._update_status(
                    candidate,
                    last_health_at=_now(),
                )
                return False
        self._update_status(
            candidate,
            last_health_at=_now(),
        )
        return True

    # internal -----------------------------------------------------------------

    def _require_candidate(
        self, domain: str, key: str, provider: str | None
    ) -> Candidate:
        candidate = self.resolver.resolve(domain, key, provider=provider)
        if not candidate:
            raise LifecycleError(f"No candidate registered for {domain}:{key}")
        return candidate

    async def _apply_candidate(self, candidate: Candidate, *, force: bool) -> Any:
        log_context = {
            "domain": candidate.domain,
            "key": candidate.key,
            "provider": candidate.provider,
        }
        span_attrs = {
            "oneiric.domain": candidate.domain,
            "oneiric.key": candidate.key,
            "oneiric.provider": candidate.provider or "unknown",
        }
        with observed_span(
            "lifecycle.swap",
            component=f"lifecycle.{candidate.domain}",
            attributes=span_attrs,
            log_context=log_context,
        ) as span:
            started_at = time.perf_counter()
            success = False
            instance_key = (candidate.domain, candidate.key)
            previous = self._instances.get(instance_key)
            instance: Any | None = None
            self._update_status(
                candidate,
                state="activating",
                pending_provider=candidate.provider,
                last_error=None,
            )
            try:
                instance = await self._instantiate_candidate(candidate)
                await self._run_health(candidate, instance, force=force)
                await self._run_hooks(
                    self.hooks.pre_swap, candidate, instance, previous
                )
                self._instances[instance_key] = instance
                now = _now()
                self._update_status(
                    candidate,
                    state="ready",
                    current_provider=candidate.provider,
                    pending_provider=None,
                    last_error=None,
                    last_activated_at=now,
                )
                await self._cleanup_instance(previous)
                await self._run_hooks(
                    self.hooks.post_swap, candidate, instance, previous
                )
                self._logger.info(
                    "swap-complete",
                    domain=candidate.domain,
                    key=candidate.key,
                    provider=candidate.provider,
                )
                success = True
                return instance
            except Exception as exc:
                error_message = str(exc)
                span.record_exception(exc)
                self._logger.error(
                    "swap-failed",
                    domain=candidate.domain,
                    key=candidate.key,
                    provider=candidate.provider,
                    exc_info=exc,
                )
                if instance is not None and instance is not previous:
                    try:
                        await self._cleanup_instance(instance)
                    except Exception as cleanup_exc:  # pragma: no cover - defensive log
                        self._logger.warning(
                            "swap-cleanup-failed",
                            domain=candidate.domain,
                            key=candidate.key,
                            provider=candidate.provider,
                            error=str(cleanup_exc),
                        )
                self._update_status(
                    candidate,
                    state="failed",
                    pending_provider=None,
                    last_error=error_message,
                )
                await self._rollback(candidate, previous, force=force)
                if force:
                    return previous
                if isinstance(exc, LifecycleError):
                    raise
                raise LifecycleError(
                    f"Swap failed for {candidate.domain}:{candidate.key} ({candidate.provider})"
                ) from exc
            finally:
                duration_ms = (time.perf_counter() - started_at) * 1000
                span.set_attributes(
                    {
                        "oneiric.lifecycle.success": success,
                        "oneiric.lifecycle.duration_ms": duration_ms,
                    }
                )
                self._record_swap_metrics(candidate, duration_ms, success)
                record_swap_duration(
                    candidate.domain,
                    candidate.key,
                    candidate.provider,
                    duration_ms,
                    success=success,
                )

    async def _instantiate_candidate(self, candidate: Candidate) -> Any:
        factory = resolve_factory(candidate.factory)
        product = factory()
        return await self._maybe_with_protection(
            product,
            timeout=self._safety.activation_timeout,
            label=f"activate {candidate.domain}:{candidate.key}",
        )

    async def _run_health(
        self, candidate: Candidate, instance: Any, *, force: bool
    ) -> None:
        health_checks = self._collect_health_checks(candidate, instance)
        for check in health_checks:
            result = await self._maybe_with_protection(
                check(),
                timeout=self._safety.health_timeout,
                label=f"health {candidate.domain}:{candidate.key}",
            )
            if result is False and not force:
                raise LifecycleError(
                    f"Health check failed for {candidate.domain}:{candidate.key} ({candidate.provider})"
                )
        if health_checks:
            self._update_status(
                candidate,
                last_health_at=_now(),
            )

    def _collect_health_checks(
        self, candidate: Candidate, instance: Any
    ) -> list[Callable[[], Any]]:
        health_checks: list[Callable[[], Any]] = []
        if candidate.health:
            health_checks.append(candidate.health)
        for attr in ("health", "check_health", "ready", "is_healthy"):
            method = getattr(instance, attr, None)
            if callable(method):
                health_checks.append(method)
                break
        return health_checks

    async def _cleanup_instance(self, instance: Any | None) -> None:
        if not instance:
            return
        cleanup_methods = ["cleanup", "close", "shutdown"]
        for method_name in cleanup_methods:
            method = getattr(instance, method_name, None)
            if callable(method):
                await self._maybe_with_protection(
                    method(),
                    timeout=self._safety.cleanup_timeout,
                    label=f"cleanup {type(instance).__name__}",
                )
                break
        for hook in self.hooks.on_cleanup:
            await self._maybe_with_protection(
                hook(instance),
                timeout=self._safety.hook_timeout,
                label="cleanup hook",
            )

    async def _run_hooks(
        self,
        hooks: list[LifecycleHook],
        candidate: Candidate,
        new_instance: Any,
        old_instance: Any | None,
    ) -> None:
        for hook in hooks:
            await self._maybe_with_protection(
                hook(candidate, new_instance, old_instance),
                timeout=self._safety.hook_timeout,
                label="lifecycle hook",
            )

    async def _rollback(
        self, candidate: Candidate, previous: Any | None, *, force: bool
    ) -> None:
        if not force and previous:
            self._instances[(candidate.domain, candidate.key)] = previous
            self._logger.warning(
                "swap-rollback",
                domain=candidate.domain,
                key=candidate.key,
                provider=candidate.provider,
            )
            self._update_status(
                candidate,
                pending_provider=None,
            )

    def _update_status(
        self,
        candidate: Candidate,
        *,
        state: str | None = None,
        current_provider: str | None = None,
        pending_provider: Any = _UNSET,
        last_error: Any = _UNSET,
        last_activated_at: datetime | None = None,
        last_health_at: datetime | None = None,
    ) -> None:
        status = self._ensure_status_entry(candidate)
        if state is not None:
            status.state = state
            status.last_state_change_at = _now()
        if current_provider is not None:
            status.current_provider = current_provider
        if pending_provider is not _UNSET:
            status.pending_provider = pending_provider
        if last_error is not _UNSET:
            status.last_error = last_error
        if last_activated_at is not None:
            status.last_activated_at = last_activated_at
        if last_health_at is not None:
            status.last_health_at = last_health_at
        self._persist_status_snapshot()

    def _load_status_snapshot(self) -> None:
        if not self._status_snapshot_path or not self._status_snapshot_path.exists():
            return
        try:
            data = json.loads(self._status_snapshot_path.read_text())
        except Exception as exc:  # pragma: no cover - log diagnostic
            self._logger.warning(
                "lifecycle-status-load-failed",
                path=str(self._status_snapshot_path),
                error=str(exc),
            )
            return
        if not isinstance(data, list):
            return
        for entry in data:
            status = _status_from_dict(entry)
            if not status:
                continue
            self._status[(status.domain, status.key)] = status

    def _persist_status_snapshot(self) -> None:
        if not self._status_snapshot_path:
            return
        payload = [status.as_dict() for status in self._status.values()]
        path = self._status_snapshot_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload))
        tmp_path.replace(path)

    def _ensure_status_entry(self, candidate: Candidate) -> LifecycleStatus:
        key = (candidate.domain, candidate.key)
        status = self._status.get(key)
        if not status:
            status = LifecycleStatus(domain=candidate.domain, key=candidate.key)
            self._status[key] = status
        return status

    def _record_swap_metrics(
        self, candidate: Candidate, duration_ms: float, success: bool
    ) -> None:
        status = self._ensure_status_entry(candidate)
        status.last_swap_duration_ms = duration_ms
        if success:
            status.successful_swaps += 1
        else:
            status.failed_swaps += 1
        status.recent_swap_durations_ms.append(duration_ms)
        max_samples = max(1, self._safety.max_swap_samples)
        if len(status.recent_swap_durations_ms) > max_samples:
            del status.recent_swap_durations_ms[:-max_samples]

    async def _maybe_with_protection(
        self, call: Awaitable[Any] | Any, *, timeout: float, label: str
    ) -> Any:
        if inspect.isawaitable(call):
            return await self._await_with_timeout(call, timeout, label)
        return call

    async def _await_with_timeout(
        self, awaitable: Awaitable[Any], timeout: float, label: str
    ) -> Any:
        task: Awaitable[Any] = awaitable
        if self._safety.shield_tasks:
            task = asyncio.shield(task)  # type: ignore[assignment]
        if timeout and timeout > 0:
            try:
                return await asyncio.wait_for(task, timeout)
            except TimeoutError as exc:  # pragma: no cover - exercised via unit tests
                raise LifecycleError(f"{label} timed out after {timeout:.2f}s") from exc
        return await task


def _status_from_dict(entry: Any) -> LifecycleStatus | None:
    if not isinstance(entry, dict):
        return None
    domain = entry.get("domain")
    key = entry.get("key")
    if not domain or not key:
        return None
    status = LifecycleStatus(domain=domain, key=key)
    status.state = entry.get("state", status.state)
    status.current_provider = entry.get("current_provider")
    status.pending_provider = entry.get("pending_provider")
    status.last_error = entry.get("last_error")
    status.last_state_change_at = _parse_timestamp(entry.get("last_state_change_at"))
    status.last_activated_at = _parse_timestamp(entry.get("last_activated_at"))
    status.last_health_at = _parse_timestamp(entry.get("last_health_at"))
    last_duration = entry.get("last_swap_duration_ms")
    if _is_number(last_duration):
        assert last_duration is not None  # Type guard for mypy
        status.last_swap_duration_ms = float(last_duration)
    history: Any = entry.get("recent_swap_durations_ms") or []
    if isinstance(history, list):
        status.recent_swap_durations_ms = [
            float(value) for value in history if _is_number(value)
        ]
    status.successful_swaps = int(entry.get("successful_swaps") or 0)
    status.failed_swaps = int(entry.get("failed_swaps") or 0)
    return status


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
