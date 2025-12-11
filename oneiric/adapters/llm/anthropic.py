"""Anthropic Claude LLM adapter for Oneiric."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import (
    LLMBase,
    LLMBaseSettings,
    LLMCapability,
    LLMMessage,
    LLMModelInfo,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
)

logger = get_logger("adapter.llm.anthropic")


class AnthropicLLMSettings(LLMBaseSettings):
    """Settings for Anthropic Claude LLM adapter."""

    # Anthropic-specific defaults
    model: str = Field(default="claude-sonnet-4-20250514")
    base_url: str = Field(default="https://api.anthropic.com")
    api_version: str = Field(default="2023-06-01")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.7)

    # Anthropic-specific API settings
    anthropic_api_key: SecretStr | None = Field(default=None)

    # Claude-specific settings
    thinking_enabled: bool = Field(default=False)
    thinking_budget_tokens: int = Field(default=10000)
    top_k: int = Field(default=-1)  # -1 means disabled


class AnthropicLLM(LLMBase):
    """Anthropic Claude LLM adapter implementation."""

    metadata = AdapterMetadata(
        category="llm",
        provider="anthropic",
        factory="oneiric.adapters.llm.anthropic:AnthropicLLM",
        description="Anthropic Claude adapter with streaming, tool use, and extended thinking support",
        capabilities=[
            "chat_completion",
            "streaming",
            "tool_calling",
            "vision",
            "extended_thinking",
        ],
        stack_level=15,
        priority=480,
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=True,
        settings_model=AnthropicLLMSettings,
    )

    def __init__(self, **kwargs: Any) -> None:
        settings = AnthropicLLMSettings(**kwargs)
        super().__init__(settings)
        self._logger = get_logger("adapter.llm.anthropic")

    @property
    def settings(self) -> AnthropicLLMSettings:
        """Get adapter settings with correct type."""
        return self._settings  # type: ignore[return-value]

    async def init(self) -> None:
        """Initialize the Anthropic adapter."""
        try:
            self._client = await self._create_client()
            self._logger.info(
                "anthropic-init-complete",
                model=self.settings.model,
                base_url=self.settings.base_url,
            )
        except Exception as exc:
            self._logger.error(
                "anthropic-init-failed",
                error=str(exc),
                model=self.settings.model,
            )
            raise LifecycleError(
                f"Failed to initialize Anthropic adapter: {exc}"
            ) from exc

    async def health(self) -> bool:
        """Check if the Anthropic service is healthy."""
        try:
            client = await self._ensure_client()
            # Simple health check - try to list models or make a minimal request
            # Anthropic doesn't have a dedicated health endpoint, so we'll check client init
            return client is not None
        except Exception as exc:
            self._logger.warning(
                "anthropic-health-check-failed",
                error=str(exc),
            )
            return False

    async def cleanup(self) -> None:
        """Cleanup Anthropic adapter resources."""
        try:
            if self._client:
                # Anthropic client doesn't require explicit cleanup
                # But we'll close it if it has a close method
                if hasattr(self._client, "close"):
                    await self._client.close()
                self._client = None
                self._logger.info("anthropic-cleanup-complete")
        except Exception as exc:
            self._logger.error(
                "anthropic-cleanup-failed",
                error=str(exc),
            )
            raise LifecycleError(f"Failed to cleanup Anthropic adapter: {exc}") from exc

    async def _create_client(self) -> Any:
        """Create Anthropic client."""
        try:
            import anthropic
        except ImportError as exc:
            raise LifecycleError(
                "anthropic package required. Install with: pip install anthropic"
            ) from exc

        api_key = self.settings.anthropic_api_key or self.settings.api_key
        if not api_key:
            raise LifecycleError("Anthropic API key required")

        return anthropic.AsyncAnthropic(
            api_key=api_key.get_secret_value(),
            base_url=self.settings.base_url,
            timeout=self.settings.timeout,
            max_retries=self.settings.max_retries,
        )

    async def _ensure_client(self) -> Any:
        """Ensure client is initialized."""
        if self._client is None:
            self._client = await self._create_client()
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
        """Generate chat completion using Anthropic Claude."""
        if stream:
            return await self._handle_streaming_chat(
                messages, model, temperature, max_tokens, **kwargs
            )

        client = await self._ensure_client()
        normalized_messages = self._normalize_messages(messages)

        # Build and execute request
        request_params = self._build_chat_request_params(
            normalized_messages, model, temperature, max_tokens, **kwargs
        )

        start_time = time.time()
        try:
            response = await client.messages.create(**request_params)
            latency_ms = int((time.time() - start_time) * 1000)

            # Extract content and tool calls
            content, tool_calls = self._extract_response_content(response)

            # Extract token usage
            prompt_tokens, completion_tokens, tokens_used = self._extract_token_usage(
                response
            )

            self._logger.info(
                "anthropic-chat-complete",
                model=model,
                latency_ms=latency_ms,
                tokens=tokens_used,
            )

            return LLMResponse(
                content=content,
                model=response.model,
                provider=LLMProvider.ANTHROPIC.value,
                finish_reason=response.stop_reason,
                tool_calls=tool_calls,
                tokens_used=tokens_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                metadata={"stop_sequence": response.stop_sequence},
            )

        except Exception as exc:
            self._logger.error("anthropic-chat-failed", error=str(exc), model=model)
            raise LifecycleError(f"Failed to generate chat completion: {exc}") from exc

    async def _handle_streaming_chat(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Handle streaming chat by accumulating chunks."""
        chunks = []
        final_chunk = None
        async for chunk in self._chat_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            if chunk.content:
                chunks.append(chunk.content)
            if chunk.finish_reason:
                final_chunk = chunk

        content = "".join(chunks)
        return LLMResponse(
            content=content,
            model=model,
            provider=LLMProvider.ANTHROPIC.value,
            finish_reason=final_chunk.finish_reason if final_chunk else None,
        )

    def _build_chat_request_params(
        self,
        normalized_messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build request parameters for Anthropic API."""
        system_prompt, api_messages = self._extract_system_message(normalized_messages)

        request_params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }

        if system_prompt:
            request_params["system"] = system_prompt

        # Add optional parameters
        if self.settings.top_p < 1.0:
            request_params["top_p"] = self.settings.top_p
        if self.settings.top_k > 0:
            request_params["top_k"] = self.settings.top_k

        # Add tools if provided
        if "tools" in kwargs and kwargs["tools"]:
            request_params["tools"] = self._format_anthropic_tools(kwargs["tools"])

        # Add thinking budget if enabled
        if self.settings.thinking_enabled:
            request_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.settings.thinking_budget_tokens,
            }

        # Merge additional kwargs
        extra_kwargs = {k: v for k, v in kwargs.items() if k != "tools"}
        request_params.update(extra_kwargs)

        return request_params

    def _extract_system_message(
        self, normalized_messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Extract system message from messages list."""
        system_prompt = None
        api_messages = []
        for msg in normalized_messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                api_messages.append(msg)
        return system_prompt, api_messages

    def _extract_response_content(
        self, response: Any
    ) -> tuple[str, list[dict[str, Any]] | None]:
        """Extract content and tool calls from response."""
        content = ""
        tool_calls = None

        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
            elif hasattr(block, "tool_use"):
                if tool_calls is None:
                    tool_calls = []
                # tool_calls is now guaranteed to be a list
                assert tool_calls is not None  # for type checker
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": block.input,
                        },
                    }
                )

        return content, tool_calls

    def _extract_token_usage(
        self, response: Any
    ) -> tuple[int | None, int | None, int | None]:
        """Extract token usage from response."""
        prompt_tokens = (
            response.usage.input_tokens if hasattr(response, "usage") else None
        )
        completion_tokens = (
            response.usage.output_tokens if hasattr(response, "usage") else None
        )
        tokens_used = None
        if prompt_tokens is not None and completion_tokens is not None:
            tokens_used = prompt_tokens + completion_tokens
        return prompt_tokens, completion_tokens, tokens_used

    async def _chat_stream(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk]:
        """Generate streaming chat completion using Anthropic Claude."""
        client = await self._ensure_client()
        normalized_messages = self._normalize_messages(messages)

        system_prompt, api_messages = self._extract_system_message(normalized_messages)
        request_params = self._build_stream_request_params(
            model, max_tokens, temperature, api_messages, system_prompt, kwargs
        )

        try:
            async with client.messages.stream(**request_params) as stream:
                async for text in stream.text_stream:
                    yield LLMStreamChunk(
                        content=text,
                        model=model,
                        delta=True,
                    )

                # Get final message for stop reason
                final_message = await stream.get_final_message()
                yield LLMStreamChunk(
                    content="",
                    model=model,
                    finish_reason=final_message.stop_reason,
                    delta=False,
                )

        except Exception as exc:
            self._logger.error(
                "anthropic-stream-failed",
                error=str(exc),
                model=model,
            )
            raise LifecycleError(f"Failed to stream chat completion: {exc}") from exc

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
            temperature=kwargs.get("temperature", self.settings.temperature),
            max_tokens=kwargs.get("max_tokens", self.settings.max_tokens),
            stream=False,
            tools=tools,
            **kwargs,
        )

    async def _get_model_info(self, model: str) -> LLMModelInfo:
        """Get information about an Anthropic model."""
        # Anthropic doesn't have a models API, so we return static info
        model_info_map = {
            "claude-opus-4-20250514": LLMModelInfo(
                name="claude-opus-4-20250514",
                provider=LLMProvider.ANTHROPIC,
                capabilities=[
                    LLMCapability.CHAT_COMPLETION,
                    LLMCapability.TOOL_USE,
                    LLMCapability.VISION,
                    LLMCapability.STREAMING,
                ],
                context_length=200000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                cost_per_1k_input_tokens=0.015,
                cost_per_1k_output_tokens=0.075,
            ),
            "claude-sonnet-4-20250514": LLMModelInfo(
                name="claude-sonnet-4-20250514",
                provider=LLMProvider.ANTHROPIC,
                capabilities=[
                    LLMCapability.CHAT_COMPLETION,
                    LLMCapability.TOOL_USE,
                    LLMCapability.VISION,
                    LLMCapability.STREAMING,
                ],
                context_length=200000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                cost_per_1k_input_tokens=0.003,
                cost_per_1k_output_tokens=0.015,
            ),
            "claude-haiku-4-20250514": LLMModelInfo(
                name="claude-haiku-4-20250514",
                provider=LLMProvider.ANTHROPIC,
                capabilities=[
                    LLMCapability.CHAT_COMPLETION,
                    LLMCapability.TOOL_USE,
                    LLMCapability.VISION,
                    LLMCapability.STREAMING,
                ],
                context_length=200000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                cost_per_1k_input_tokens=0.0008,
                cost_per_1k_output_tokens=0.004,
            ),
            "claude-3-opus-20240229": LLMModelInfo(
                name="claude-3-opus-20240229",
                provider=LLMProvider.ANTHROPIC,
                capabilities=[
                    LLMCapability.CHAT_COMPLETION,
                    LLMCapability.TOOL_USE,
                    LLMCapability.VISION,
                    LLMCapability.STREAMING,
                ],
                context_length=200000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                cost_per_1k_input_tokens=0.015,
                cost_per_1k_output_tokens=0.075,
            ),
            "claude-3-sonnet-20240229": LLMModelInfo(
                name="claude-3-sonnet-20240229",
                provider=LLMProvider.ANTHROPIC,
                capabilities=[
                    LLMCapability.CHAT_COMPLETION,
                    LLMCapability.TOOL_USE,
                    LLMCapability.VISION,
                    LLMCapability.STREAMING,
                ],
                context_length=200000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                cost_per_1k_input_tokens=0.003,
                cost_per_1k_output_tokens=0.015,
            ),
            "claude-3-haiku-20240307": LLMModelInfo(
                name="claude-3-haiku-20240307",
                provider=LLMProvider.ANTHROPIC,
                capabilities=[
                    LLMCapability.CHAT_COMPLETION,
                    LLMCapability.TOOL_USE,
                    LLMCapability.STREAMING,
                ],
                context_length=200000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=False,
                cost_per_1k_input_tokens=0.00025,
                cost_per_1k_output_tokens=0.00125,
            ),
        }

        if model not in model_info_map:
            # Return a generic model info if not found
            return LLMModelInfo(
                name=model,
                provider=LLMProvider.ANTHROPIC,
                capabilities=[
                    LLMCapability.CHAT_COMPLETION,
                    LLMCapability.STREAMING,
                ],
                context_length=200000,
                max_output_tokens=4096,
                supports_streaming=True,
            )

        return model_info_map[model]

    async def _list_models(self) -> list[LLMModelInfo]:
        """List available Anthropic models."""
        return [
            await self._get_model_info("claude-opus-4-20250514"),
            await self._get_model_info("claude-sonnet-4-20250514"),
            await self._get_model_info("claude-haiku-4-20250514"),
            await self._get_model_info("claude-3-opus-20240229"),
            await self._get_model_info("claude-3-sonnet-20240229"),
            await self._get_model_info("claude-3-haiku-20240307"),
        ]

    def _build_stream_request_params(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        api_messages: list[dict[str, Any]],
        system_prompt: str | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Build request parameters for streaming."""
        request_params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }

        if system_prompt:
            request_params["system"] = system_prompt

        self._add_sampling_params(request_params)
        self._add_tools_if_present(request_params, kwargs)
        self._add_thinking_if_enabled(request_params)

        # Merge any additional kwargs
        extra_kwargs = {k: v for k, v in kwargs.items() if k != "tools"}
        request_params.update(extra_kwargs)

        return request_params

    def _add_sampling_params(self, params: dict[str, Any]) -> None:
        """Add top_p and top_k sampling parameters if configured."""
        if self.settings.top_p < 1.0:
            params["top_p"] = self.settings.top_p
        if self.settings.top_k > 0:
            params["top_k"] = self.settings.top_k

    def _add_tools_if_present(
        self, params: dict[str, Any], kwargs: dict[str, Any]
    ) -> None:
        """Add tools to parameters if provided."""
        if "tools" in kwargs and kwargs["tools"]:
            params["tools"] = self._format_anthropic_tools(kwargs["tools"])

    def _add_thinking_if_enabled(self, params: dict[str, Any]) -> None:
        """Add thinking budget if enabled."""
        if self.settings.thinking_enabled:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.settings.thinking_budget_tokens,
            }

    def _format_anthropic_tools(
        self,
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Format tools for Anthropic API."""
        return [
            {
                "name": tool.get("name", tool.get("function", {}).get("name")),
                "description": tool.get(
                    "description", tool.get("function", {}).get("description")
                ),
                "input_schema": tool.get(
                    "parameters", tool.get("function", {}).get("parameters")
                ),
            }
            for tool in tools
        ]
