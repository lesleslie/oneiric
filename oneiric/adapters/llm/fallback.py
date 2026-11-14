"""Fallback chain with circuit breaker for LLM providers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.resolution import CandidateSource

from ._security import sanitize_error as _sanitize_error
from .config import LLMSettings
from .exceptions import AllProvidersExhaustedError, LLMError
from .provider import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Simple circuit breaker for a single provider.

    Opens after `failure_threshold` consecutive failures, resets after
    `reset_timeout` seconds. Half-open state allows a single probe.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._failure_count = 0
        self._last_failure_time: float = 0

    @property
    def is_open(self) -> bool:
        """Whether the circuit breaker is open (provider should be skipped)."""
        if self._failure_count >= self.failure_threshold:
            elapsed = time.monotonic() - self._last_failure_time
            # Half-open: allow one attempt when reset_timeout has elapsed
            return elapsed < self.reset_timeout
        return False

    def record_success(self) -> None:
        """Record a successful call — resets the breaker."""
        self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call — increments failure count."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()


class FallbackChain:
    """Ordered provider list with per-tier retry and circuit breaker.

    Tries providers in order with up to `max_attempts_per_tier` retries
    per provider before advancing to the next tier. Circuit breakers count
    per tier-call (after all retries exhausted), not per attempt.
    asyncio.CancelledError always propagates immediately.
    """

    metadata: ClassVar[AdapterMetadata] = AdapterMetadata(
        category="llm",
        provider="fallback",
        factory="oneiric.adapters.llm.fallback: FallbackChain",
        description=(
            "Ordered provider list with per-tier retry and a circuit breaker "
            "per provider"
        ),
        capabilities=["chat_completion", "fallback_chain"],
        stack_level=10,
        priority=100,
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=False,
        settings_model=LLMSettings,
    )

    def __init__(
        self,
        providers: list[OpenAICompatibleProvider] | None = None,
        max_attempts_per_tier: int = 3,
    ) -> None:
        """Build a chain over an ordered provider list.

        ``providers`` is optional so the class satisfies the
        zero-argument factory contract the adapter registry uses
        (``LifecycleManager._instantiate_candidate`` calls ``factory()``).
        An empty chain is well-formed but cannot serve a request.
        """
        self._providers = list(providers) if providers else []
        self._max_attempts = max_attempts_per_tier
        self._circuit_breakers: dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
            for p in self._providers
        }

    @classmethod
    def from_settings(cls, settings: LLMSettings) -> FallbackChain:
        """Create a FallbackChain from LLMSettings.

        Args:
            settings: LLMSettings with provider configurations.

        Returns:
            FallbackChain with providers ordered by fallback_chain.
        """
        providers = [
            OpenAICompatibleProvider(provider_config)
            for provider_config in settings.get_enabled_providers()
        ]
        return cls(providers)

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Try providers in order with per-tier retry before advancing.

        Args:
            task: Dict with 'model', 'messages', and optional params.

        Returns:
            Dict with 'content', 'provider', 'model', 'usage'.

        Raises:
            AllProvidersExhaustedError: When all providers fail.
        """
        last_error: Exception | None = None

        for provider in self._providers:
            breaker = self._circuit_breakers[provider.name]
            if breaker.is_open:
                logger.debug("Skipping %s (circuit breaker open)", provider.name)
                continue

            tier_succeeded = False
            timeout = getattr(provider, "timeout_seconds", 30)

            for attempt in range(self._max_attempts):
                try:
                    result = await asyncio.wait_for(
                        provider.execute(task),
                        timeout=timeout,
                    )
                    if result.get("content"):
                        breaker.record_success()
                        tier_succeeded = True
                        return result
                    raise ValueError("Provider returned empty content")

                except asyncio.CancelledError:
                    raise  # never swallow

                except Exception as e:  # broad except is intentional
                    last_error = e
                    sanitized = _sanitize_error(str(e))
                    if attempt < self._max_attempts - 1:
                        backoff = 2**attempt  # 1s, 2s, 4s
                        logger.debug(
                            "Provider %s attempt %d/%d failed (%s), retrying in %ds",
                            provider.name,
                            attempt + 1,
                            self._max_attempts,
                            sanitized,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.warning(
                            "Provider %s exhausted %d attempts: %s",
                            provider.name,
                            self._max_attempts,
                            sanitized,
                        )

            if not tier_succeeded:
                breaker.record_failure()  # counts once per tier-call

        sanitized_last = _sanitize_error(str(last_error)) if last_error else "unknown"
        if last_error is not None:
            # Sanitize the chained cause too: `raise ... from e` puts the
            # cause's own rendering into the traceback, so a key in the
            # original message would still be printed. An exception that
            # renders itself from somewhere other than args is not
            # chained at all.
            last_error.args = (sanitized_last,)
        if last_error is not None and str(last_error) != sanitized_last:
            raise AllProvidersExhaustedError(
                f"All {len(self._providers)} providers failed. Last: {sanitized_last}"
            ) from None
        raise AllProvidersExhaustedError(
            f"All {len(self._providers)} providers failed. Last: {sanitized_last}"
        ) from last_error

    async def init(self) -> None:
        """Warm up every provider in the chain.

        Idempotent -- each provider's ``init`` tolerates repeat calls, so
        a hot-swap can re-run this without rebuilding live clients.

        Fault-tolerant, like :meth:`health` and :meth:`cleanup`: one
        provider failing to warm up must not strand the others. The
        failures are collected and raised together, so a caller learns
        that setup was incomplete without losing the providers that did
        come up.
        """
        failures: list[str] = []
        for provider in self._providers:
            try:
                await provider.init()
            except Exception as e:
                failures.append(f"{provider.name}: {_sanitize_error(str(e))}")
                logger.warning(
                    "Provider %s failed to initialize: %s",
                    provider.name,
                    _sanitize_error(str(e)),
                )
        if failures:
            raise LLMError(
                "Fallback chain initialization failed for: " + "; ".join(failures)
            )

    async def health(self) -> bool:
        """Return whether at least one provider in the chain is reachable.

        A fallback chain exists to survive a provider being down, so a
        single healthy provider is enough. Never raises -- the monitoring
        layer relies on a ``bool``.
        """
        if not self._providers:
            return False
        for provider in self._providers:
            try:
                if await provider.health():
                    return True
            except Exception as e:
                logger.warning(
                    "Health check raised for %s: %s",
                    provider.name,
                    _sanitize_error(str(e)),
                )
        return False

    async def cleanup(self) -> None:
        """Release every provider in the chain.

        Idempotent, and never raises -- one provider failing to close
        must not strand the others.
        """
        for provider in self._providers:
            try:
                await provider.cleanup()
            except Exception as e:
                logger.warning(
                    "Cleanup failed for %s: %s",
                    provider.name,
                    _sanitize_error(str(e)),
                )
