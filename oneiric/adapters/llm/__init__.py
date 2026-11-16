"""Lazy-loaded llm adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.llm import SomeAdapter`` still works and
``import oneiric.adapters.llm`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "REASONING_EFFORT_LEVELS",
    "AllProvidersExhaustedError",
    "AnthropicLLM",
    "AnthropicLLMSettings",
    "BifrostLLMRouter",
    "BifrostLLMSettings",
    "CircuitBreaker",
    "FallbackChain",
    "LLMBase",
    "LLMBaseSettings",
    "LLMCapability",
    "LLMError",
    "LLMFunctionCall",
    "LLMMessage",
    "LLMModelInfo",
    "LLMProvider",
    "LLMResponse",
    "LLMSettings",
    "LLMStreamChunk",
    "LLMToolCall",
    "MessageRole",
    "OpenAICompatibleProvider",
    "OpenAILLMAdapter",
    "OpenAILLMSettings",
    "ProviderConfig",
    "ProviderUnavailableError",
    "RouteKind",
    "TaskType",
    "UnsupportedModalityError",
    "get_router",
    "reset_router_for_tests",
]


if TYPE_CHECKING:
    from oneiric.adapters.llm.anthropic import (
        AnthropicLLM,
        AnthropicLLMSettings,
    )
    from oneiric.adapters.llm.bifrost import (
        BifrostLLMRouter,
        BifrostLLMSettings,
        RouteKind,
        get_router,
        reset_router_for_tests,
    )
    from oneiric.adapters.llm.config import (
        REASONING_EFFORT_LEVELS,
        LLMSettings,
        ProviderConfig,
    )
    from oneiric.adapters.llm.exceptions import (
        AllProvidersExhaustedError,
        LLMError,
        ProviderUnavailableError,
        UnsupportedModalityError,
    )
    from oneiric.adapters.llm.fallback import (
        CircuitBreaker,
        FallbackChain,
    )
    from oneiric.adapters.llm.llm_interface import (
        LLMBase,
        LLMBaseSettings,
        LLMCapability,
        LLMFunctionCall,
        LLMMessage,
        LLMModelInfo,
        LLMProvider,
        LLMResponse,
        LLMStreamChunk,
        LLMToolCall,
        MessageRole,
    )
    from oneiric.adapters.llm.openai import (
        OpenAILLMAdapter,
        OpenAILLMSettings,
    )
    from oneiric.adapters.llm.provider import OpenAICompatibleProvider
    from oneiric.adapters.llm.types import TaskType


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AllProvidersExhaustedError": (
        "oneiric.adapters.llm.exceptions",
        "AllProvidersExhaustedError",
    ),
    "AnthropicLLM": ("oneiric.adapters.llm.anthropic", "AnthropicLLM"),
    "AnthropicLLMSettings": ("oneiric.adapters.llm.anthropic", "AnthropicLLMSettings"),
    "BifrostLLMRouter": ("oneiric.adapters.llm.bifrost", "BifrostLLMRouter"),
    "BifrostLLMSettings": ("oneiric.adapters.llm.bifrost", "BifrostLLMSettings"),
    "CircuitBreaker": ("oneiric.adapters.llm.fallback", "CircuitBreaker"),
    "FallbackChain": ("oneiric.adapters.llm.fallback", "FallbackChain"),
    "LLMBase": ("oneiric.adapters.llm.llm_interface", "LLMBase"),
    "LLMBaseSettings": ("oneiric.adapters.llm.llm_interface", "LLMBaseSettings"),
    "LLMCapability": ("oneiric.adapters.llm.llm_interface", "LLMCapability"),
    "LLMError": ("oneiric.adapters.llm.exceptions", "LLMError"),
    "LLMFunctionCall": ("oneiric.adapters.llm.llm_interface", "LLMFunctionCall"),
    "LLMMessage": ("oneiric.adapters.llm.llm_interface", "LLMMessage"),
    "LLMModelInfo": ("oneiric.adapters.llm.llm_interface", "LLMModelInfo"),
    "LLMProvider": ("oneiric.adapters.llm.llm_interface", "LLMProvider"),
    "LLMResponse": ("oneiric.adapters.llm.llm_interface", "LLMResponse"),
    "LLMSettings": ("oneiric.adapters.llm.config", "LLMSettings"),
    "LLMStreamChunk": ("oneiric.adapters.llm.llm_interface", "LLMStreamChunk"),
    "LLMToolCall": ("oneiric.adapters.llm.llm_interface", "LLMToolCall"),
    "MessageRole": ("oneiric.adapters.llm.llm_interface", "MessageRole"),
    "OpenAICompatibleProvider": (
        "oneiric.adapters.llm.provider",
        "OpenAICompatibleProvider",
    ),
    "OpenAILLMAdapter": ("oneiric.adapters.llm.openai", "OpenAILLMAdapter"),
    "OpenAILLMSettings": ("oneiric.adapters.llm.openai", "OpenAILLMSettings"),
    "ProviderConfig": ("oneiric.adapters.llm.config", "ProviderConfig"),
    "ProviderUnavailableError": (
        "oneiric.adapters.llm.exceptions",
        "ProviderUnavailableError",
    ),
    "REASONING_EFFORT_LEVELS": (
        "oneiric.adapters.llm.config",
        "REASONING_EFFORT_LEVELS",
    ),
    "RouteKind": ("oneiric.adapters.llm.bifrost", "RouteKind"),
    "TaskType": ("oneiric.adapters.llm.types", "TaskType"),
    "UnsupportedModalityError": (
        "oneiric.adapters.llm.exceptions",
        "UnsupportedModalityError",
    ),
    "get_router": ("oneiric.adapters.llm.bifrost", "get_router"),
    "reset_router_for_tests": (
        "oneiric.adapters.llm.bifrost",
        "reset_router_for_tests",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported adapter on first attribute access (PEP 562)."""
    from oneiric.adapters._lazy import resolve_lazy_export

    value = resolve_lazy_export(__name__, name, _LAZY_EXPORTS)
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
