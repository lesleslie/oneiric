"""Lifecycle and hot-swap helpers."""

from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from opentelemetry.trace import Span

from .logging import get_logger
from .observability import get_tracer
from .resolution import Candidate, Resolver
from .security import load_factory_allowlist, validate_factory_string

FactoryCallable = Callable[..., Any]
LifecycleHook = Callable[[Candidate, Any, Optional[Any]], Awaitable[None] | None]
CleanupHook = Callable[[Any], Awaitable[None] | None]


class LifecycleError(RuntimeError):
    """Raised when activation or swap fails."""


@dataclass
class LifecycleHooks:
    pre_swap: List[LifecycleHook] = field(default_factory=list)
    post_swap: List[LifecycleHook] = field(default_factory=list)
    on_cleanup: List[CleanupHook] = field(default_factory=list)

    def add_pre_swap(self, hook: LifecycleHook) -> None:
        self.pre_swap.append(hook)

    def add_post_swap(self, hook: LifecycleHook) -> None:
        self.post_swap.append(hook)

    def add_cleanup(self, hook: CleanupHook) -> None:
        self.on_cleanup.append(hook)


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


async def _maybe_await(call: Awaitable[Any] | Any) -> Any:
    if inspect.isawaitable(call):
        return await call
    return call


@dataclass
class LifecycleStatus:
    domain: str
    key: str
    state: str = "unknown"
    current_provider: Optional[str] = None
    pending_provider: Optional[str] = None
    last_error: Optional[str] = None
    last_state_change_at: Optional[datetime] = None
    last_activated_at: Optional[datetime] = None
    last_health_at: Optional[datetime] = None

    def as_dict(self) -> Dict[str, Any]:
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
        }


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


_UNSET = object()


class LifecycleManager:
    """Instantiate and hot-swap resolver-backed candidates."""

    def __init__(
        self,
        resolver: Resolver,
        hooks: Optional[LifecycleHooks] = None,
        *,
        status_snapshot_path: Optional[str] = None,
    ) -> None:
        self.resolver = resolver
        self.hooks = hooks or LifecycleHooks()
        self._instances: Dict[Tuple[str, str], Any] = {}
        self._status: Dict[Tuple[str, str], LifecycleStatus] = {}
        self._status_snapshot_path = Path(status_snapshot_path) if status_snapshot_path else None
        self._logger = get_logger("lifecycle")
        self._load_status_snapshot()

    async def activate(self, domain: str, key: str, provider: Optional[str] = None, *, force: bool = False) -> Any:
        candidate = self._require_candidate(domain, key, provider)
        return await self._apply_candidate(candidate, force=force)

    async def swap(self, domain: str, key: str, provider: Optional[str] = None, *, force: bool = False) -> Any:
        return await self.activate(domain, key, provider=provider, force=force)

    def get_instance(self, domain: str, key: str) -> Optional[Any]:
        return self._instances.get((domain, key))

    def get_status(self, domain: str, key: str) -> Optional[LifecycleStatus]:
        return self._status.get((domain, key))

    def all_statuses(self) -> List[LifecycleStatus]:
        return list(self._status.values())

    async def probe_instance_health(self, domain: str, key: str) -> Optional[bool]:
        candidate = self.resolver.resolve(domain, key)
        instance = self.get_instance(domain, key)
        if not candidate or instance is None:
            return None
        checks = self._collect_health_checks(candidate, instance)
        if not checks:
            return True
        for check in checks:
            result = await _maybe_await(check())
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

    def _require_candidate(self, domain: str, key: str, provider: Optional[str]) -> Candidate:
        candidate = self.resolver.resolve(domain, key, provider=provider)
        if not candidate:
            raise LifecycleError(f"No candidate registered for {domain}:{key}")
        return candidate

    async def _apply_candidate(self, candidate: Candidate, *, force: bool) -> Any:
        span = self._start_span(candidate)
        instance_key = (candidate.domain, candidate.key)
        previous = self._instances.get(instance_key)
        self._update_status(
            candidate,
            state="activating",
            pending_provider=candidate.provider,
            last_error=None,
        )
        try:
            instance = await self._instantiate_candidate(candidate)
            await self._run_health(candidate, instance, force=force)
            await self._run_hooks(self.hooks.pre_swap, candidate, instance, previous)
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
            await self._run_hooks(self.hooks.post_swap, candidate, instance, previous)
            self._logger.info(
                "swap-complete",
                domain=candidate.domain,
                key=candidate.key,
                provider=candidate.provider,
            )
            return instance
        except Exception as exc:
            error_message = str(exc)
            self._logger.error(
                "swap-failed",
                domain=candidate.domain,
                key=candidate.key,
                provider=candidate.provider,
                exc_info=exc,
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
            raise LifecycleError(
                f"Swap failed for {candidate.domain}:{candidate.key} ({candidate.provider})"
            ) from exc
        finally:
            span.end()

    async def _instantiate_candidate(self, candidate: Candidate) -> Any:
        factory = resolve_factory(candidate.factory)
        product = factory()
        return await _maybe_await(product)

    async def _run_health(self, candidate: Candidate, instance: Any, *, force: bool) -> None:
        health_checks = self._collect_health_checks(candidate, instance)
        for check in health_checks:
            result = await _maybe_await(check())
            if result is False and not force:
                raise LifecycleError(
                    f"Health check failed for {candidate.domain}:{candidate.key} ({candidate.provider})"
                )
        if health_checks:
            self._update_status(
                candidate,
                last_health_at=_now(),
            )

    def _collect_health_checks(self, candidate: Candidate, instance: Any) -> List[Callable[[], Any]]:
        health_checks: List[Callable[[], Any]] = []
        if candidate.health:
            health_checks.append(candidate.health)
        for attr in ("health", "check_health", "ready", "is_healthy"):
            method = getattr(instance, attr, None)
            if callable(method):
                health_checks.append(method)
                break
        return health_checks

    async def _cleanup_instance(self, instance: Optional[Any]) -> None:
        if not instance:
            return
        cleanup_methods = ["cleanup", "close", "shutdown"]
        for method_name in cleanup_methods:
            method = getattr(instance, method_name, None)
            if callable(method):
                await _maybe_await(method())
                break
        for hook in self.hooks.on_cleanup:
            await _maybe_await(hook(instance))

    async def _run_hooks(
        self,
        hooks: List[LifecycleHook],
        candidate: Candidate,
        new_instance: Any,
        old_instance: Optional[Any],
    ) -> None:
        for hook in hooks:
            await _maybe_await(hook(candidate, new_instance, old_instance))

    async def _rollback(self, candidate: Candidate, previous: Optional[Any], *, force: bool) -> None:
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

    def _start_span(self, candidate: Candidate) -> Span:
        tracer = get_tracer(f"lifecycle.{candidate.domain}")
        span = tracer.start_span(
            "lifecycle.swap",
            attributes={
                "domain": candidate.domain,
                "key": candidate.key,
                "provider": candidate.provider or "unknown",
            },
        )
        return span

    def _update_status(
        self,
        candidate: Candidate,
        *,
        state: Optional[str] = None,
        current_provider: Optional[str] = None,
        pending_provider: Any = _UNSET,
        last_error: Any = _UNSET,
        last_activated_at: Optional[datetime] = None,
        last_health_at: Optional[datetime] = None,
    ) -> None:
        key = (candidate.domain, candidate.key)
        status = self._status.get(key)
        if not status:
            status = LifecycleStatus(domain=candidate.domain, key=candidate.key)
            self._status[key] = status
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


def _status_from_dict(entry: Any) -> Optional[LifecycleStatus]:
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
    return status


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
