"""Dead-flag regression test for ``BifrostLLMRouter.resolve``.

REQ-BIFROST-002's dead-flag slice: the structural guarantee that no
consumer can produce inert wiring. The original bug was
``settings/mahavishnu.yaml`` setting ``route_qwen_code: True`` while
``bifrost.enabled`` defaulted to ``False`` — a per-worker flag that
short-circuited on the parent. The new router's ``resolve(provider)``
returns ``None`` (not a flag, not a stub) when disabled, so any call
site that consults it cannot produce inert wiring.
"""

from __future__ import annotations

import pytest

from oneiric.adapters.llm.bifrost import (
    BifrostLLMRouter,
    BifrostLLMSettings,
    RouteKind,
)
from oneiric.adapters.llm.llm_interface import LLMProvider


def test_resolve_disabled_with_full_routes_returns_none() -> None:
    """The structural regression test.

    Even with BOTH routes configured, ``enabled=False`` must short-circuit
    every call to ``None``. The old shape had a per-worker ``route_*_code``
    flag that the parent short-circuited; the new shape collapses the two
    knobs so there's no way to be "set but unreachable".
    """
    settings = BifrostLLMSettings(
        enabled=False,
        routes={RouteKind.CLAUDE_ROUTE, RouteKind.QWEN_ROUTE},
    )
    router = BifrostLLMRouter(settings=settings)
    # The two routable providers
    assert router.resolve(LLMProvider.ANTHROPIC) is None
    assert router.resolve(LLMProvider.OPENAI) is None


def test_resolve_enabled_without_route_returns_none() -> None:
    """The other half of the contract: enabled but the route is not configured
    is also ``None``. The two failure modes (disabled, route-missing) are
    indistinguishable from the caller's perspective — that's the point.
    """
    settings = BifrostLLMSettings(
        enabled=True,
        routes=set(),  # no routes configured
    )
    router = BifrostLLMRouter(settings=settings)
    assert router.resolve(LLMProvider.ANTHROPIC) is None
    assert router.resolve(LLMProvider.OPENAI) is None


@pytest.mark.parametrize("provider", [LLMProvider.ANTHROPIC, LLMProvider.OPENAI])
def test_resolve_toggle_is_atomic(provider: LLMProvider) -> None:
    """Toggling ``enabled`` from False to True flips the answer from ``None``
    to a non-empty string with NO other state change. This is what
    guarantees the new design has no dead-flag surface.
    """
    disabled_router = BifrostLLMRouter(
        settings=BifrostLLMSettings(
            enabled=False,
            routes={RouteKind.CLAUDE_ROUTE, RouteKind.QWEN_ROUTE},
        )
    )
    enabled_router = BifrostLLMRouter(
        settings=BifrostLLMSettings(
            enabled=True,
            routes={RouteKind.CLAUDE_ROUTE, RouteKind.QWEN_ROUTE},
        )
    )
    assert disabled_router.resolve(provider) is None
    assert enabled_router.resolve(provider) is not None
    assert enabled_router.resolve(provider) != ""
