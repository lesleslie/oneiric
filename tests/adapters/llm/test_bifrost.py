"""Tests for ``BifrostLLMRouter`` and ``BifrostLLMSettings``.

Phase 1 of the bifrost plan. Covers:

- REQ-BIFROST-001: router metadata is registered in the catalog
- REQ-BIFROST-002: resolve returns ``None`` when disabled
- REQ-BIFROST-015: router is NOT a subclass of ``LLMBase``
- REQ-BIFROST-019: ``AdapterMetadata`` shape matches the AnthropicLLM shape
- REQ-BIFROST-020: ``LLMProvider`` → ``RouteKind`` mapping is explicit

The parametrization is over all 8 ``LLMProvider`` values (the plan
referenced 7, but ``LLAMA_SERVER`` was added in the ollama plan 5
and is now part of the enum).
"""

from __future__ import annotations

import pytest

from oneiric.adapters.bootstrap import builtin_adapter_metadata
from oneiric.adapters.llm.bifrost import (
    BifrostLLMRouter,
    BifrostLLMSettings,
    RouteKind,
    get_router,
)
from oneiric.adapters.llm.llm_interface import LLMBase, LLMProvider
from oneiric.core.resolution import CandidateSource


# ---------------------------------------------------------------------------
# REQ-BIFROST-001: catalog registration
# ---------------------------------------------------------------------------


def test_metadata_registered() -> None:
    """The router appears in ``builtin_adapter_metadata()`` exactly once."""
    metadata = builtin_adapter_metadata()
    bifrost_entries = [m for m in metadata if m.provider == "bifrost"]
    assert len(bifrost_entries) == 1
    assert bifrost_entries[0] is BifrostLLMRouter.metadata


def test_catalog_count_after_addition() -> None:
    """The catalog grew by exactly one entry (sanity check vs. the plan's
    ``>=58`` validation matrix line)."""
    metadata = builtin_adapter_metadata()
    # 57 base entries per plan §7 + 1 new = 58
    assert len(metadata) >= 58


# ---------------------------------------------------------------------------
# REQ-BIFROST-015: NOT a subclass of LLMBase
# ---------------------------------------------------------------------------


def test_router_not_subclass_of_llmbase() -> None:
    """The router is a standalone class; subclassing ``LLMBase`` would
    force eight abstract HTTP-transport methods that the URL resolver
    doesn't need (5-agent review's decisive argument against).
    """
    assert issubclass(BifrostLLMRouter, LLMBase) is False


# ---------------------------------------------------------------------------
# REQ-BIFROST-019: AdapterMetadata shape
# ---------------------------------------------------------------------------


def test_metadata_shape() -> None:
    """AdapterMetadata fields match the AnthropicLLM reference shape."""
    m = BifrostLLMRouter.metadata
    assert m.category == "llm"
    assert m.provider == "bifrost"
    # Note: space after the colon in factory string (3-agent F7 fix).
    assert m.factory == "oneiric.adapters.llm.bifrost: BifrostLLMRouter"
    assert m.description is not None
    assert isinstance(m.capabilities, list)
    assert m.stack_level is not None
    assert m.stack_level < 20
    assert m.priority is not None
    assert m.priority < 500
    assert m.source == CandidateSource.LOCAL_PKG
    assert m.owner == "AI Platform"
    assert m.requires_secrets is False
    assert m.settings_model is BifrostLLMSettings


# ---------------------------------------------------------------------------
# REQ-BIFROST-020: 8→2 LLMProvider → RouteKind mapping
# ---------------------------------------------------------------------------


class TestProviderRouteMapping:
    """``_PROVIDER_ROUTE`` is explicit: 2 mapped providers, 6 unmapped."""

    @pytest.mark.parametrize(
        ("provider", "expected_route"),
        [
            (LLMProvider.ANTHROPIC, RouteKind.CLAUDE_ROUTE),
            (LLMProvider.OPENAI, RouteKind.QWEN_ROUTE),
        ],
    )
    def test_mapped_providers(
        self, provider: LLMProvider, expected_route: RouteKind
    ) -> None:
        assert BifrostLLMRouter._PROVIDER_ROUTE[provider] is expected_route

    @pytest.mark.parametrize(
        "provider",
        [
            LLMProvider.AZURE_OPENAI,
            LLMProvider.GOOGLE_VERTEX,
            LLMProvider.AWS_BEDROCK,
            LLMProvider.LOCAL,
            LLMProvider.ZAI,
            LLMProvider.LLAMA_SERVER,
        ],
    )
    def test_unmapped_providers_raise_keyerror(self, provider: LLMProvider) -> None:
        with pytest.raises(KeyError):
            BifrostLLMRouter._PROVIDER_ROUTE[provider]


# ---------------------------------------------------------------------------
# REQ-BIFROST-002: resolve() returns None when disabled (parametrized)
# ---------------------------------------------------------------------------


class TestResolveDisabled:
    """``resolve()`` returns ``None`` for every provider when ``enabled=False``."""

    @pytest.mark.parametrize("provider", list(LLMProvider))
    def test_resolve_disabled_returns_none(self, provider: LLMProvider) -> None:
        # routes is fully populated so we know the only reason for None
        # is ``enabled=False`` — not a missing route
        settings = BifrostLLMSettings(
            enabled=False,
            routes={RouteKind.CLAUDE_ROUTE, RouteKind.QWEN_ROUTE},
        )
        router = BifrostLLMRouter(settings=settings)
        assert router.resolve(provider) is None


# ---------------------------------------------------------------------------
# REQ-BIFROST-002 (positive case): resolve() returns URL when enabled+routed
# ---------------------------------------------------------------------------


class TestResolveEnabled:
    """``resolve()`` returns the gateway URL when enabled and routed."""

    def test_resolve_anthropic(self) -> None:
        settings = BifrostLLMSettings(
            enabled=True,
            routes={RouteKind.CLAUDE_ROUTE},
        )
        router = BifrostLLMRouter(settings=settings)
        result = router.resolve(LLMProvider.ANTHROPIC)
        assert result is not None
        # Default anthropic_base_url is http://127.0.0.1:8471/anthropic
        # HttpUrl normalizes with a trailing slash; strip it for the assert.
        assert result.rstrip("/") == "http://127.0.0.1:8471/anthropic"

    def test_resolve_openai(self) -> None:
        settings = BifrostLLMSettings(
            enabled=True,
            routes={RouteKind.QWEN_ROUTE},
        )
        router = BifrostLLMRouter(settings=settings)
        result = router.resolve(LLMProvider.OPENAI)
        assert result is not None
        # Default base_url must include ``/v1`` — the OpenAI-compatible
        # endpoint on Bifrost is served at ``/v1/chat/completions``,
        # not ``/chat/completions``. Restores the legacy
        # ``BifrostClient.DEFAULT_BASE_URL = "http://localhost:8471/v1"``
        # contract (cross-repo B2 BLOCKER fix in oneiric 0.33+).
        assert result.rstrip("/") == "http://127.0.0.1:8471/v1"

    def test_resolve_routes_mismatch_returns_none(self) -> None:
        """Enabled but the required route is absent from settings.routes."""
        settings = BifrostLLMSettings(
            enabled=True,
            routes={RouteKind.CLAUDE_ROUTE},  # no qwen_route
        )
        router = BifrostLLMRouter(settings=settings)
        assert router.resolve(LLMProvider.OPENAI) is None

    def test_resolve_unmapped_provider_raises_keyerror(self) -> None:
        """A caller asking for a non-routable provider surfaces a clear bug."""
        settings = BifrostLLMSettings(
            enabled=True,
            routes={RouteKind.CLAUDE_ROUTE, RouteKind.QWEN_ROUTE},
        )
        router = BifrostLLMRouter(settings=settings)
        with pytest.raises(KeyError):
            router.resolve(LLMProvider.AZURE_OPENAI)


# ---------------------------------------------------------------------------
# get_router() singleton
# ---------------------------------------------------------------------------


def test_get_router_returns_singleton() -> None:
    """Repeated calls return the same instance (process-cached)."""
    a = get_router()
    b = get_router()
    assert a is b


def test_get_router_uses_default_settings() -> None:
    """Without env-var overrides, the singleton is constructed with defaults."""
    router = get_router()
    # enabled defaults to False
    assert router.resolve(LLMProvider.ANTHROPIC) is None
