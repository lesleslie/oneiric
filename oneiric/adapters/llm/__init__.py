"""LLM adapters and shared LLM infrastructure for the Bodai ecosystem.

Hosts the LLM *providers* (``anthropic``, ``bifrost``, ``openai``) and the
chaining layer that sits over them (:class:`FallbackChain` and
:class:`OpenAICompatibleProvider`), plus the YAML-driven settings that
configure them.

Usage:
    >>> from oneiric.adapters.llm import LLMSettings, FallbackChain, TaskType
    >>> settings = LLMSettings.from_yaml("settings/models.yaml")
    >>> chain = FallbackChain.from_settings(settings)
    >>> result = await chain.execute({"model": "MiniMax-M3", "messages": [...]})
"""

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

from .config import LLMSettings, ProviderConfig
from .exceptions import (
    AllProvidersExhaustedError,
    LLMError,
    ProviderUnavailableError,
    UnsupportedModalityError,
)
from .fallback import CircuitBreaker, FallbackChain
from .provider import OpenAICompatibleProvider
from .types import TaskType

__all__ = [
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
