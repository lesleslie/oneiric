"""Base LLM adapter interface for AI language model operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.core.logging import get_logger


class LLMProvider(str, Enum):
    """LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    GOOGLE_VERTEX = "google_vertex"
    AWS_BEDROCK = "aws_bedrock"
    OLLAMA = "ollama"
    LOCAL = "local"


class LLMCapability(str, Enum):
    """LLM capabilities."""

    TEXT_GENERATION = "text_generation"
    CHAT_COMPLETION = "chat_completion"
    FUNCTION_CALLING = "function_calling"
    TOOL_USE = "tool_use"
    VISION = "vision"
    AUDIO = "audio"
    CODE_GENERATION = "code_generation"
    STREAMING = "streaming"
    JSON_MODE = "json_mode"


class MessageRole(str, Enum):
    """Message roles in conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"
    TOOL = "tool"


@dataclass
class LLMMessage:
    """Single message in a conversation."""

    role: MessageRole | str
    content: str
    name: str | None = None
    function_call: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class LLMFunctionCall:
    """Function call from LLM."""

    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class LLMToolCall:
    """Tool call from LLM."""

    id: str
    type: str
    function: dict[str, Any]


class LLMResponse(BaseModel):
    """LLM response with metadata."""

    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    tokens_used: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    function_calls: list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    cost: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMStreamChunk(BaseModel):
    """Streaming chunk from LLM."""

    content: str
    finish_reason: str | None = None
    model: str
    delta: bool = True


@dataclass
class LLMModelInfo:
    """Information about an LLM model."""

    name: str
    provider: LLMProvider
    capabilities: list[LLMCapability]
    context_length: int
    max_output_tokens: int
    supports_streaming: bool = True
    supports_functions: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    cost_per_1k_input_tokens: float | None = None
    cost_per_1k_output_tokens: float | None = None


class LLMBaseSettings(BaseModel):
    """Base settings for LLM adapters."""

    # Model configuration
    model: str = Field(default="gpt-3.5-turbo")
    max_tokens: int = Field(default=1000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    n: int = Field(default=1, ge=1)

    # API configuration
    api_key: SecretStr | None = Field(default=None)
    base_url: str | None = Field(default=None)
    organization: str | None = Field(default=None)
    timeout: float = Field(default=60.0)
    max_retries: int = Field(default=3)

    # Advanced settings
    stream: bool = Field(default=False)
    response_format: dict[str, Any] | None = Field(default=None)
    seed: int | None = Field(default=None)
    stop: list[str] | None = Field(default=None)
    logit_bias: dict[int, float] | None = Field(default=None)

    # Function/Tool calling
    functions: list[dict[str, Any]] | None = Field(default=None)
    function_call: str | dict[str, str] | None = Field(default=None)
    tools: list[dict[str, Any]] | None = Field(default=None)
    tool_choice: str | dict[str, Any] | None = Field(default=None)


class LLMBase(ABC):
    """Base LLM adapter with standard interface and lifecycle integration."""

    def __init__(self, settings: LLMBaseSettings) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._model_cache: dict[str, LLMModelInfo] = {}
        self._logger = get_logger("adapter.llm.base")

    @property
    def settings(self) -> LLMBaseSettings:
        """Get adapter settings."""
        return self._settings

    @property
    def client(self) -> Any:
        """Get the LLM client."""
        return self._client

    # Lifecycle hooks (to be implemented by Oneiric lifecycle manager)
    @abstractmethod
    async def init(self) -> None:
        """Initialize the LLM adapter."""
        ...

    @abstractmethod
    async def health(self) -> bool:
        """Check if the LLM service is healthy."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup LLM adapter resources."""
        ...

    # Public API Methods

    async def chat(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate chat completion."""
        return await self._chat(
            messages=messages,
            model=model or self._settings.model,
            temperature=temperature
            if temperature is not None
            else self._settings.temperature,
            max_tokens=max_tokens or self._settings.max_tokens,
            stream=stream if stream is not None else self._settings.stream,
            **kwargs,
        )

    async def chat_stream(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk]:
        """Generate streaming chat completion."""
        async for chunk in self._chat_stream(
            messages=messages,
            model=model or self._settings.model,
            temperature=temperature
            if temperature is not None
            else self._settings.temperature,
            max_tokens=max_tokens or self._settings.max_tokens,
            **kwargs,
        ):
            yield chunk

    async def complete(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate text completion."""
        return await self._complete(
            prompt=prompt,
            model=model or self._settings.model,
            temperature=temperature
            if temperature is not None
            else self._settings.temperature,
            max_tokens=max_tokens or self._settings.max_tokens,
            **kwargs,
        )

    async def complete_stream(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk]:
        """Generate streaming text completion."""
        async for chunk in self._complete_stream(
            prompt=prompt,
            model=model or self._settings.model,
            temperature=temperature
            if temperature is not None
            else self._settings.temperature,
            max_tokens=max_tokens or self._settings.max_tokens,
            **kwargs,
        ):
            yield chunk

    async def function_call(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        functions: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate chat completion with function calling."""
        return await self._function_call(
            messages=messages,
            functions=functions,
            model=model or self._settings.model,
            **kwargs,
        )

    async def tool_use(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate chat completion with tool use."""
        return await self._tool_use(
            messages=messages,
            tools=tools,
            model=model or self._settings.model,
            **kwargs,
        )

    async def get_model_info(
        self,
        model: str | None = None,
    ) -> LLMModelInfo:
        """Get information about an LLM model."""
        return await self._get_model_info(model or self._settings.model)

    async def list_models(self) -> list[LLMModelInfo]:
        """List available LLM models."""
        return await self._list_models()

    async def count_tokens(
        self,
        text: str,
        model: str | None = None,
    ) -> int:
        """Count tokens in text."""
        return await self._count_tokens(text, model or self._settings.model)

    # Abstract methods that implementations must provide

    @abstractmethod
    async def _ensure_client(self) -> Any:
        """Ensure client is initialized."""
        ...

    @abstractmethod
    async def _chat(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        **kwargs: Any,
    ) -> LLMResponse:
        """Implementation-specific chat completion."""
        ...

    @abstractmethod
    async def _chat_stream(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk]:
        """Implementation-specific streaming chat completion."""
        # This is an async generator function, not a regular async function
        # The return type annotation is correct despite mypy warnings
        if False:  # pragma: no cover - type stub only
            yield  # type: ignore[unreachable]
        raise NotImplementedError

    async def _complete(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Implementation-specific text completion (default: convert to chat)."""
        messages: list[LLMMessage | dict[str, Any]] = [
            LLMMessage(role=MessageRole.USER, content=prompt)
        ]
        return await self._chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            **kwargs,
        )

    async def _complete_stream(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk]:
        """Implementation-specific streaming text completion (default: convert to chat)."""
        messages: list[LLMMessage | dict[str, Any]] = [
            LLMMessage(role=MessageRole.USER, content=prompt)
        ]
        async for chunk in self._chat_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            yield chunk

    async def _function_call(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        functions: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> LLMResponse:
        """Implementation-specific function calling (default: not supported)."""
        msg = f"{self.__class__.__name__} does not support function calling"
        raise NotImplementedError(msg)

    async def _tool_use(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> LLMResponse:
        """Implementation-specific tool use (default: not supported)."""
        msg = f"{self.__class__.__name__} does not support tool use"
        raise NotImplementedError(msg)

    @abstractmethod
    async def _get_model_info(self, model: str) -> LLMModelInfo:
        """Implementation-specific model information."""
        ...

    @abstractmethod
    async def _list_models(self) -> list[LLMModelInfo]:
        """Implementation-specific model listing."""
        ...

    async def _count_tokens(self, text: str, model: str) -> int:
        """Default token counting (rough estimation)."""
        # Simple estimation: ~4 characters per token for English text
        return len(text) // 4

    # Utility methods

    def _normalize_messages(
        self,
        messages: list[LLMMessage | dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Normalize messages to dict format."""
        return [
            self._normalize_single_message(msg) if isinstance(msg, LLMMessage) else msg
            for msg in messages
        ]

    def _normalize_single_message(self, msg: LLMMessage) -> dict[str, Any]:
        """Convert a single LLMMessage to dict format."""
        msg_dict: dict[str, Any] = {
            "role": msg.role.value if isinstance(msg.role, MessageRole) else msg.role,
            "content": msg.content,
        }
        if msg.name:
            msg_dict["name"] = msg.name
        if msg.function_call:
            msg_dict["function_call"] = msg.function_call
        if msg.tool_calls:
            msg_dict["tool_calls"] = msg.tool_calls
        return msg_dict

    def _calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model_info: LLMModelInfo,
    ) -> float | None:
        """Calculate cost based on token usage."""
        if (
            model_info.cost_per_1k_input_tokens is None
            or model_info.cost_per_1k_output_tokens is None
        ):
            return None

        input_cost = (prompt_tokens / 1000) * model_info.cost_per_1k_input_tokens
        output_cost = (completion_tokens / 1000) * model_info.cost_per_1k_output_tokens

        return input_cost + output_cost
