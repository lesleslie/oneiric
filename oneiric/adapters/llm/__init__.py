"""LLM adapters and shared LLM infrastructure for the Bodai ecosystem.

Hosts the LLM *providers* (``anthropic``, ``bifrost``, ``openai``) and the
chaining layer that sits over them (:class:`FallbackChain` and
:class:`OpenAICompatibleProvider`), plus the YAML-driven settings that
configure them.

:class:`FallbackChain` and :class:`OpenAICompatibleProvider` satisfy the
``OneiricAdapter`` Protocol -- they carry ``AdapterMetadata`` and the
``init``/``health``/``cleanup`` lifecycle -- but they are **not** in the
adapter resolution catalog. They are *consumer-constructed*: their
essential input is a caller-supplied :class:`LLMSettings` or
:class:`ProviderConfig`, and the catalog instantiates a factory with no
arguments, so a catalog entry could never be activated. See
``docs/plans/2026-10-11-move-llm-from-mcp-common-to-oneiric.md``.

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

from .config import REASONING_EFFORT_LEVELS, LLMSettings, ProviderConfig
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
