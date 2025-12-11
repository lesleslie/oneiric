"""OpenAI LLM adapter for GPT models."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import Field, SecretStr

from oneiric.adapters.llm.common import (
    LLMBase,
    LLMBaseSettings,
    LLMCapability,
    LLMMessage,
    LLMModelInfo,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
)
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class OpenAILLMSettings(LLMBaseSettings):
    """Settings for OpenAI LLM adapter."""

    # OpenAI-specific settings
    openai_api_key: SecretStr | None = Field(default=None)
    openai_organization: str | None = Field(default=None)
    openai_base_url: str = Field(default="https://api.openai.com/v1")

    # Model defaults
    model: str = Field(default="gpt-3.5-turbo")

    # Advanced OpenAI settings
    user: str | None = Field(default=None)
    logprobs: bool | None = Field(default=None)
    top_logprobs: int | None = Field(default=None, ge=0, le=5)


class OpenAILLMAdapter(LLMBase):
    """OpenAI LLM adapter implementation."""

    metadata = AdapterMetadata(
        category="llm",
        provider="openai",
        factory="oneiric.adapters.llm.openai:OpenAILLMAdapter",
        description="OpenAI GPT adapter with chat, streaming, tool-calling, and JSON mode support",
        capabilities=[
            "chat_completion",
            "streaming",
            "function_calling",
            "tool_use",
            "json_mode",
            "vision",
        ],
        stack_level=20,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=True,
        settings_model=OpenAILLMSettings,
    )

    def __init__(
        self,
        openai_api_key: str | SecretStr | None = None,
        openai_organization: str | None = None,
        openai_base_url: str | None = None,
        model: str = "gpt-3.5-turbo",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        timeout: float = 60.0,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> None:
        # Convert string api_key to SecretStr
        if isinstance(openai_api_key, str):
            openai_api_key = SecretStr(openai_api_key)

        settings = OpenAILLMSettings(
            openai_api_key=openai_api_key,
            openai_organization=openai_organization,
            openai_base_url=openai_base_url or "https://api.openai.com/v1",
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            max_retries=max_retries,
            **kwargs,
        )
        super().__init__(settings)
        self._logger = get_logger("adapter.llm.openai")

    @property
    def settings(self) -> OpenAILLMSettings:
        """Get adapter settings with correct type."""
        return self._settings  # type: ignore[return-value]

    async def init(self) -> None:
        """Initialize the OpenAI LLM adapter."""
        self._logger.info("Initializing OpenAI LLM adapter")
        await self._ensure_client()
        self._logger.info("OpenAI LLM adapter initialized successfully")

    async def health(self) -> bool:
        """Check if OpenAI service is healthy."""
        try:
            client = await self._ensure_client()
            # Simple models list call to verify connectivity
            await client.models.list()
            return True
        except Exception as e:
            self._logger.error(f"Health check failed: {e}")
            return False

    async def cleanup(self) -> None:
        """Cleanup OpenAI adapter resources."""
        self._logger.info("Cleaning up OpenAI LLM adapter")
        if self._client:
            await self._client.close()
            self._client = None
        self._logger.info("OpenAI LLM adapter cleanup complete")

    async def _ensure_client(self) -> Any:
        """Ensure OpenAI client is initialized."""
        if self._client is not None:
            return self._client

        try:
            import openai
        except ImportError as e:
            msg = "openai package required for OpenAI LLM adapter"
            raise ImportError(msg) from e

        # Get API key from settings
        api_key = self.settings.openai_api_key or self.settings.api_key
        if not api_key:
            msg = "OpenAI API key is required"
            raise ValueError(msg)

        self._client = openai.AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            organization=self.settings.openai_organization
            or self.settings.organization,
            base_url=self.settings.openai_base_url or self.settings.base_url,
            timeout=self.settings.timeout,
            max_retries=self.settings.max_retries,
        )

        self._logger.info(
            "OpenAI client initialized",
            extra={
                "model": self.settings.model,
                "base_url": self.settings.openai_base_url,
            },
        )

        return self._client

    async def _chat(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate chat completion using OpenAI."""
        client = await self._ensure_client()
        normalized_messages = self._normalize_messages(messages)

        start_time = asyncio.get_event_loop().time()

        # Build request parameters
        params = self._build_openai_request_params(
            normalized_messages, model, temperature, max_tokens, **kwargs
        )

        try:
            response = await client.chat.completions.create(**params)
            latency_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

            # Extract response data
            choice = response.choices[0]
            message = choice.message
            function_calls = self._extract_function_calls(message)

            # Get token usage and cost
            prompt_tokens, completion_tokens, total_tokens = (
                self._extract_openai_token_usage(response)
            )
            model_info = await self._get_model_info(model)
            cost = self._calculate_cost(prompt_tokens, completion_tokens, model_info)

            return LLMResponse(
                content=message.content or "",
                model=response.model,
                provider=LLMProvider.OPENAI.value,
                finish_reason=choice.finish_reason,
                tokens_used=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                function_calls=function_calls,
                cost=cost,
                metadata={
                    "system_fingerprint": getattr(response, "system_fingerprint", None),
                    "created": response.created,
                },
            )

        except Exception as e:
            self._logger.error(f"Chat completion failed: {e}", exc_info=True)
            raise

    def _build_openai_request_params(
        self,
        normalized_messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build request parameters for OpenAI API."""
        params: dict[str, Any] = {
            "model": model,
            "messages": normalized_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        # Add optional parameters from settings
        self._add_optional_settings_params(params)

        # Add function/tool calling parameters
        self._add_function_tool_params(params, kwargs)

        return params

    def _add_optional_settings_params(self, params: dict[str, Any]) -> None:
        """Add optional parameters from settings to request."""
        self._add_numeric_params(params)
        self._add_conditional_params(params)

    def _add_numeric_params(self, params: dict[str, Any]) -> None:
        """Add numeric parameters that differ from defaults."""
        optional_settings = {
            "top_p": (self.settings.top_p, 1.0),
            "frequency_penalty": (self.settings.frequency_penalty, 0.0),
            "presence_penalty": (self.settings.presence_penalty, 0.0),
            "n": (self.settings.n, 1),
        }
        for param_name, (value, default) in optional_settings.items():
            if value != default:
                params[param_name] = value

    def _add_conditional_params(self, params: dict[str, Any]) -> None:
        """Add parameters that are set (non-empty/non-None)."""
        conditional_params = [
            ("stop", self.settings.stop),
            ("logit_bias", self.settings.logit_bias),
            ("user", self.settings.user),
            ("seed", self.settings.seed),
            ("response_format", self.settings.response_format),
            ("logprobs", self.settings.logprobs),
            ("top_logprobs", self.settings.top_logprobs),
        ]
        for param_name, value in conditional_params:
            if value:
                params[param_name] = value

    def _add_function_tool_params(
        self, params: dict[str, Any], kwargs: dict[str, Any]
    ) -> None:
        """Add function and tool calling parameters to request."""
        if kwargs.get("functions"):
            params["functions"] = kwargs["functions"]
        if kwargs.get("function_call"):
            params["function_call"] = kwargs["function_call"]
        if kwargs.get("tools"):
            params["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            params["tool_choice"] = kwargs["tool_choice"]

    def _extract_function_calls(self, message: Any) -> list[dict[str, Any]] | None:
        """Extract function calls from OpenAI message."""
        if hasattr(message, "function_call") and message.function_call:
            return [
                {
                    "name": message.function_call.name,
                    "arguments": json.loads(message.function_call.arguments),
                }
            ]
        elif hasattr(message, "tool_calls") and message.tool_calls:
            return [
                {
                    "id": call.id,
                    "type": call.type,
                    "name": call.function.name,
                    "arguments": json.loads(call.function.arguments),
                }
                for call in message.tool_calls
            ]
        return None

    def _extract_openai_token_usage(self, response: Any) -> tuple[int, int, int]:
        """Extract token usage from OpenAI response."""
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        total_tokens = response.usage.total_tokens if response.usage else 0
        return prompt_tokens, completion_tokens, total_tokens

    async def _chat_stream(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk]:
        """Generate streaming chat completion using OpenAI."""
        client = await self._ensure_client()
        normalized_messages = self._normalize_messages(messages)

        # Build request parameters
        params = self._build_stream_request_params(
            normalized_messages, model, temperature, max_tokens, **kwargs
        )

        try:
            stream = await client.chat.completions.create(**params)
            async for chunk in self._process_stream_chunks(stream, model):
                yield chunk
        except Exception as e:
            self._logger.error(f"Streaming chat completion failed: {e}", exc_info=True)
            raise

    def _build_stream_request_params(
        self,
        normalized_messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build request parameters for streaming completion."""
        params: dict[str, Any] = {
            "model": model,
            "messages": normalized_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        # Add optional parameters
        self._add_stream_settings_params(params)
        self._add_stream_function_params(params, kwargs)

        return params

    def _add_stream_settings_params(self, params: dict[str, Any]) -> None:
        """Add optional settings parameters for streaming."""
        if self.settings.top_p != 1.0:
            params["top_p"] = self.settings.top_p
        if self.settings.frequency_penalty != 0.0:
            params["frequency_penalty"] = self.settings.frequency_penalty
        if self.settings.presence_penalty != 0.0:
            params["presence_penalty"] = self.settings.presence_penalty
        if self.settings.stop:
            params["stop"] = self.settings.stop
        if self.settings.user:
            params["user"] = self.settings.user
        if self.settings.seed:
            params["seed"] = self.settings.seed

    def _add_stream_function_params(
        self, params: dict[str, Any], kwargs: dict[str, Any]
    ) -> None:
        """Add function/tool calling parameters for streaming."""
        if kwargs.get("functions"):
            params["functions"] = kwargs["functions"]
        if kwargs.get("tools"):
            params["tools"] = kwargs["tools"]

    async def _process_stream_chunks(
        self, stream: Any, model: str
    ) -> AsyncGenerator[LLMStreamChunk]:
        """Process streaming response chunks."""
        async for chunk in stream:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            if not delta.content:
                continue

            yield LLMStreamChunk(
                content=delta.content,
                finish_reason=choice.finish_reason,
                model=chunk.model,
                delta=True,
            )

    async def _function_call(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        functions: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate chat completion with function calling."""
        return await self._chat(
            messages=messages,
            model=model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            stream=False,
            functions=functions,
            function_call=kwargs.get("function_call", "auto"),
        )

    async def _tool_use(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate chat completion with tool use."""
        return await self._chat(
            messages=messages,
            model=model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            stream=False,
            tools=tools,
            tool_choice=kwargs.get("tool_choice", "auto"),
        )

    async def _get_model_info(self, model: str) -> LLMModelInfo:
        """Get information about an OpenAI model."""
        if model in self._model_cache:
            return self._model_cache[model]

        # Static model information (OpenAI doesn't provide this via API)
        model_data = _OPENAI_MODEL_DATA.get(model)
        if not model_data:
            # Default fallback for unknown models
            model_data = {
                "context_length": 4096,
                "max_output_tokens": 4096,
                "capabilities": [LLMCapability.CHAT_COMPLETION],
                "supports_functions": False,
                "supports_tools": False,
                "supports_vision": False,
                "supports_json_mode": False,
                "cost_per_1k_input_tokens": None,
                "cost_per_1k_output_tokens": None,
            }

        model_info = LLMModelInfo(
            name=model,
            provider=LLMProvider.OPENAI,
            capabilities=model_data["capabilities"],
            context_length=model_data["context_length"],
            max_output_tokens=model_data["max_output_tokens"],
            supports_streaming=True,
            supports_functions=model_data["supports_functions"],
            supports_tools=model_data["supports_tools"],
            supports_vision=model_data["supports_vision"],
            supports_json_mode=model_data["supports_json_mode"],
            cost_per_1k_input_tokens=model_data["cost_per_1k_input_tokens"],
            cost_per_1k_output_tokens=model_data["cost_per_1k_output_tokens"],
        )

        self._model_cache[model] = model_info
        return model_info

    async def _list_models(self) -> list[LLMModelInfo]:
        """List available OpenAI models."""
        models = []
        for model_name in _OPENAI_MODEL_DATA.keys():
            model_info = await self._get_model_info(model_name)
            models.append(model_info)
        return models

    async def _count_tokens(self, text: str, model: str) -> int:
        """Count tokens using tiktoken."""
        try:
            import tiktoken

            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except ImportError:
            # Fallback to rough estimation
            return await super()._count_tokens(text, model)
        except Exception:
            # If model not found in tiktoken, use rough estimation
            return await super()._count_tokens(text, model)


# OpenAI model data (as of January 2025)
_OPENAI_MODEL_DATA: dict[str, dict[str, Any]] = {
    # GPT-4 Turbo
    "gpt-4-turbo": {
        "context_length": 128000,
        "max_output_tokens": 4096,
        "capabilities": [
            LLMCapability.CHAT_COMPLETION,
            LLMCapability.FUNCTION_CALLING,
            LLMCapability.TOOL_USE,
            LLMCapability.VISION,
            LLMCapability.JSON_MODE,
        ],
        "supports_functions": True,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "cost_per_1k_input_tokens": 0.01,
        "cost_per_1k_output_tokens": 0.03,
    },
    "gpt-4-turbo-preview": {
        "context_length": 128000,
        "max_output_tokens": 4096,
        "capabilities": [
            LLMCapability.CHAT_COMPLETION,
            LLMCapability.FUNCTION_CALLING,
            LLMCapability.TOOL_USE,
            LLMCapability.JSON_MODE,
        ],
        "supports_functions": True,
        "supports_tools": True,
        "supports_vision": False,
        "supports_json_mode": True,
        "cost_per_1k_input_tokens": 0.01,
        "cost_per_1k_output_tokens": 0.03,
    },
    # GPT-4
    "gpt-4": {
        "context_length": 8192,
        "max_output_tokens": 8192,
        "capabilities": [
            LLMCapability.CHAT_COMPLETION,
            LLMCapability.FUNCTION_CALLING,
            LLMCapability.TOOL_USE,
        ],
        "supports_functions": True,
        "supports_tools": True,
        "supports_vision": False,
        "supports_json_mode": False,
        "cost_per_1k_input_tokens": 0.03,
        "cost_per_1k_output_tokens": 0.06,
    },
    "gpt-4-32k": {
        "context_length": 32768,
        "max_output_tokens": 32768,
        "capabilities": [
            LLMCapability.CHAT_COMPLETION,
            LLMCapability.FUNCTION_CALLING,
            LLMCapability.TOOL_USE,
        ],
        "supports_functions": True,
        "supports_tools": True,
        "supports_vision": False,
        "supports_json_mode": False,
        "cost_per_1k_input_tokens": 0.06,
        "cost_per_1k_output_tokens": 0.12,
    },
    # GPT-3.5 Turbo
    "gpt-3.5-turbo": {
        "context_length": 16385,
        "max_output_tokens": 4096,
        "capabilities": [
            LLMCapability.CHAT_COMPLETION,
            LLMCapability.FUNCTION_CALLING,
            LLMCapability.TOOL_USE,
            LLMCapability.JSON_MODE,
        ],
        "supports_functions": True,
        "supports_tools": True,
        "supports_vision": False,
        "supports_json_mode": True,
        "cost_per_1k_input_tokens": 0.0005,
        "cost_per_1k_output_tokens": 0.0015,
    },
    "gpt-3.5-turbo-16k": {
        "context_length": 16385,
        "max_output_tokens": 4096,
        "capabilities": [
            LLMCapability.CHAT_COMPLETION,
            LLMCapability.FUNCTION_CALLING,
            LLMCapability.TOOL_USE,
        ],
        "supports_functions": True,
        "supports_tools": True,
        "supports_vision": False,
        "supports_json_mode": False,
        "cost_per_1k_input_tokens": 0.003,
        "cost_per_1k_output_tokens": 0.004,
    },
    # GPT-4 Vision
    "gpt-4-vision-preview": {
        "context_length": 128000,
        "max_output_tokens": 4096,
        "capabilities": [
            LLMCapability.CHAT_COMPLETION,
            LLMCapability.VISION,
        ],
        "supports_functions": False,
        "supports_tools": False,
        "supports_vision": True,
        "supports_json_mode": False,
        "cost_per_1k_input_tokens": 0.01,
        "cost_per_1k_output_tokens": 0.03,
    },
}
