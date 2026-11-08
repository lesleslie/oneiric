"""Regression tests for the ("adapter", "queue") provider pin.

Queue adapters register under ``domain="adapter", key="queue"`` and the
resolver ranks them by
``(override_score, capability_score, priority, stack_level, registration_sequence)``.
Nothing else in the fleet sets a ``selections`` override, so without one the
slot is decided purely by priority — and the top-priority queue adapter is
``pubsub`` (410, a GCP adapter that cannot run locally), not
``redis-streams`` (300), the provider the Bodai event bus actually uses.

``settings/oneiric.yaml`` pins the slot through ``adapters.selections``, the
tier-1 "explicit override" in the 4-tier precedence. ``override_score`` is the
FIRST element of the scoring tuple, so the pin dominates priority outright and
holds regardless of what the priorities happen to be.

See ``docs/plans/2026-11-08-lavinmq-provider-pinning.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from oneiric.adapters.bootstrap import (
    builtin_adapter_metadata,
    register_builtin_adapters,
)
from oneiric.core.config import load_settings, resolver_settings_from_config
from oneiric.core.resolution import Resolver, ResolverSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
PIN_FILE = REPO_ROOT / "settings" / "oneiric.yaml"

ADAPTER_DOMAIN = "adapter"
QUEUE_KEY = "queue"
PINNED_PROVIDER = "redis-streams"


def _resolver(selection: str | None = None) -> Resolver:
    """Build a resolver with the builtin adapters registered.

    ``selection`` of ``None`` means "no explicit override", which is the
    priority-only race the pin is meant to remove.
    """
    settings = (
        ResolverSettings(selections={ADAPTER_DOMAIN: {QUEUE_KEY: selection}})
        if selection is not None
        else ResolverSettings()
    )
    resolver = Resolver(settings=settings)
    register_builtin_adapters(resolver)
    return resolver


class TestQueueProviderPinFile:
    """The committed pin file carries the selection."""

    def test_pin_file_exists(self) -> None:
        assert PIN_FILE.is_file(), f"missing pin file: {PIN_FILE}"

    def test_pin_file_declares_redis_streams_for_queue(self) -> None:
        raw: dict[str, Any] = yaml.safe_load(PIN_FILE.read_text()) or {}
        selections = (raw.get("adapters") or {}).get("selections") or {}
        assert selections.get(QUEUE_KEY) == PINNED_PROVIDER


class TestQueueProviderSelection:
    """The pin decides the slot; priority does not."""

    def test_pinned_resolution_returns_redis_streams(self) -> None:
        candidate = _resolver(PINNED_PROVIDER).resolve(ADAPTER_DOMAIN, QUEUE_KEY)
        assert candidate is not None
        assert candidate.provider == PINNED_PROVIDER

    def test_pin_is_load_bearing(self) -> None:
        """Without the pin, priority alone picks a different provider.

        This is what the pin exists to prevent. Asserted as "not the pinned
        provider" rather than against a specific priority so the test does
        not churn when adapter priorities are retuned.
        """
        candidate = _resolver().resolve(ADAPTER_DOMAIN, QUEUE_KEY)
        assert candidate is not None
        assert candidate.provider != PINNED_PROVIDER

    def test_pin_survives_the_settings_chain(self) -> None:
        """The pin reaches the resolver through the real layered config."""
        settings = load_settings(project_root=REPO_ROOT)
        assert settings.adapters.selections.get(QUEUE_KEY) == PINNED_PROVIDER

        resolver_settings = resolver_settings_from_config(settings)
        assert resolver_settings.selection_for(ADAPTER_DOMAIN, QUEUE_KEY) == (
            PINNED_PROVIDER
        )


class TestLavinMQReregistration:
    """LavinMQ is registered and reachable by explicit opt-in."""

    def test_lavinmq_is_in_builtin_metadata(self) -> None:
        queue_adapters = {
            m.provider: m for m in builtin_adapter_metadata() if m.category == QUEUE_KEY
        }
        assert PINNED_PROVIDER in queue_adapters
        assert "lavinmq" in queue_adapters

    def test_lavinmq_priority_outranks_redis_streams(self) -> None:
        """Documents WHY the pin is required.

        Priority alone can never hand the queue slot to redis-streams:
        ``pubsub`` (410) and ``cloudtasks`` (400) are GCP adapters that
        outrank it, and ``lavinmq`` (330) outranks it too. redis-streams
        sits at 300, mid-pack. Only an explicit selection can put it on
        top — which is exactly what the pin does.
        """
        queue_adapters = {
            m.provider: m for m in builtin_adapter_metadata() if m.category == QUEUE_KEY
        }
        lavinmq_priority = queue_adapters["lavinmq"].priority
        redis_priority = queue_adapters[PINNED_PROVIDER].priority

        assert lavinmq_priority is not None
        assert redis_priority is not None
        assert lavinmq_priority > redis_priority

    def test_explicit_opt_in_selects_lavinmq(self) -> None:
        """`use("queue", provider="lavinmq")` still works with the pin in place."""
        resolver = _resolver(PINNED_PROVIDER)
        candidate = resolver.resolve(ADAPTER_DOMAIN, QUEUE_KEY, provider="lavinmq")
        assert candidate is not None
        assert candidate.provider == "lavinmq"
