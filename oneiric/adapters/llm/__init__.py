"""LLM adapters for Oneiric."""

from oneiric.adapters.llm.anthropic import (
    AnthropicLLM,
    AnthropicLLMSettings,
)
from oneiric.adapters.llm.common import (
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

__all__ = [
    # Base classes
    "LLMBase",
    "LLMBaseSettings",
    # Enums
    "LLMProvider",
    "LLMCapability",
    "MessageRole",
    # Models
    "LLMMessage",
    "LLMResponse",
    "LLMStreamChunk",
    "LLMModelInfo",
    "LLMFunctionCall",
    "LLMToolCall",
    # Anthropic
    "AnthropicLLM",
    "AnthropicLLMSettings",
    # OpenAI
    "OpenAILLMAdapter",
    "OpenAILLMSettings",
]
