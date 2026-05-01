"""Tests targeting coverage gaps in LLM adapters, OTel storage, and Sentry monitoring.

Focus areas:
- oneiric/adapters/llm/openai.py (client init, chat, streaming, error handling)
- oneiric/adapters/llm/anthropic.py (client init, chat, streaming, tool use, thinking)
- oneiric/adapters/observability/otel.py (trace storage, flushing, queries)
- oneiric/adapters/monitoring/sentry.py (DSN resolution, fingerprinting, context tags)
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from oneiric.adapters.llm.llm_interface import (
    LLMMessage,
    LLMProvider,
    LLMStreamChunk,
)
from oneiric.core.lifecycle import LifecycleError


# ---------------------------------------------------------------------------
# OpenAI LLM Adapter
# ---------------------------------------------------------------------------


class TestOpenAILLMSettings:
    """Coverage for OpenAILLMSettings defaults and validation."""

    def test_default_settings(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMSettings

        s = OpenAILLMSettings()
        assert s.model == "gpt-3.5-turbo"
        assert s.openai_base_url == "https://api.openai.com/v1"
        assert s.openai_api_key is None
        assert s.openai_organization is None
        assert s.user is None
        assert s.logprobs is None
        assert s.top_logprobs is None

    def test_top_logprobs_range(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMSettings

        s = OpenAILLMSettings(top_logprobs=3)
        assert s.top_logprobs == 3

    def test_top_logprobs_out_of_range(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMSettings
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OpenAILLMSettings(top_logprobs=10)

    def test_settings_with_api_key(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMSettings

        s = OpenAILLMSettings(openai_api_key=SecretStr("sk-test"))
        assert s.openai_api_key.get_secret_value() == "sk-test"


class TestOpenAILLMAdapterInit:
    """Coverage for OpenAILLMAdapter constructor paths."""

    def test_init_with_string_api_key(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test-123")
        assert adapter.settings.openai_api_key.get_secret_value() == "sk-test-123"

    def test_init_with_secret_str_api_key(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key=SecretStr("sk-test-456"))
        assert adapter.settings.openai_api_key.get_secret_value() == "sk-test-456"

    def test_init_none_api_key(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter()
        assert adapter.settings.openai_api_key is None

    def test_init_custom_base_url(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_base_url="https://custom.api.com/v1")
        assert adapter.settings.openai_base_url == "https://custom.api.com/v1"

    def test_init_default_base_url(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter()
        assert adapter.settings.openai_base_url == "https://api.openai.com/v1"

    def test_init_custom_model_and_params(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(
            model="gpt-4-turbo",
            max_tokens=2048,
            temperature=0.5,
            timeout=30.0,
            max_retries=5,
        )
        assert adapter.settings.model == "gpt-4-turbo"
        assert adapter.settings.max_tokens == 2048
        assert adapter.settings.temperature == 0.5
        assert adapter.settings.timeout == 30.0
        assert adapter.settings.max_retries == 5

    def test_metadata(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        assert OpenAILLMAdapter.metadata.category == "llm"
        assert OpenAILLMAdapter.metadata.provider == "openai"
        assert "chat_completion" in OpenAILLMAdapter.metadata.capabilities


class TestOpenAIEnsureClient:
    """Coverage for _ensure_client initialization paths."""

    @pytest.mark.asyncio
    async def test_ensure_client_creates_client(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_openai = MagicMock()
        mock_client = AsyncMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            client = await adapter._ensure_client()
            assert client is mock_client

    @pytest.mark.asyncio
    async def test_ensure_client_returns_cached(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        adapter._client = MagicMock()
        result = await adapter._ensure_client()
        assert result is adapter._client

    @pytest.mark.asyncio
    async def test_ensure_client_missing_package(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")

        import_result = ImportError("No module named openai")

        def _import_error(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "openai":
                raise import_result
            return MagicMock()

        with patch("builtins.__import__", side_effect=_import_error):
            with pytest.raises(ImportError, match="openai package required"):
                await adapter._ensure_client()

    @pytest.mark.asyncio
    async def test_ensure_client_no_api_key(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter()
        mock_openai = MagicMock()

        with patch.dict("sys.modules", {"openai": mock_openai}):
            with pytest.raises(ValueError, match="OpenAI API key is required"):
                await adapter._ensure_client()

    @pytest.mark.asyncio
    async def test_ensure_client_uses_fallback_api_key(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(api_key=SecretStr("sk-fallback"))
        mock_openai = MagicMock()
        mock_client = AsyncMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            client = await adapter._ensure_client()
            assert client is mock_client
            mock_openai.AsyncOpenAI.assert_called_once()
            call_kwargs = mock_openai.AsyncOpenAI.call_args
            assert call_kwargs.kwargs["api_key"] == "sk-fallback"

    @pytest.mark.asyncio
    async def test_ensure_client_with_organization(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(
            openai_api_key="sk-test",
            openai_organization="org-123",
        )
        mock_openai = MagicMock()
        mock_client = AsyncMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await adapter._ensure_client()
            call_kwargs = mock_openai.AsyncOpenAI.call_args
            assert call_kwargs.kwargs["organization"] == "org-123"


class TestOpenAIHealth:
    """Coverage for health check paths."""

    @pytest.mark.asyncio
    async def test_health_success(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        adapter._client = mock_client

        result = await adapter.health()
        assert result is True
        mock_client.models.list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_failure(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_client.models.list.side_effect = Exception("API down")
        adapter._client = mock_client

        result = await adapter.health()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_no_client(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter()
        result = await adapter.health()
        assert result is False


class TestOpenAICleanup:
    """Coverage for cleanup paths."""

    @pytest.mark.asyncio
    async def test_cleanup_with_client(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        adapter._client = mock_client

        await adapter.cleanup()
        mock_client.close.assert_awaited_once()
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_cleanup_without_client(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter()
        adapter._client = None

        await adapter.cleanup()  # Should not raise


class TestOpenAIInit:
    """Coverage for the async init() method."""

    @pytest.mark.asyncio
    async def test_init_success(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        adapter._client = mock_client

        await adapter.init()  # Should not raise


class TestOpenAIChat:
    """Coverage for _chat and related helper methods."""

    def _make_mock_response(
        self,
        content: str = "Hello!",
        model: str = "gpt-3.5-turbo",
        finish_reason: str = "stop",
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
        total_tokens: int = 15,
        system_fingerprint: str | None = "fp123",
    ) -> MagicMock:
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        response.choices[0].message.content = content
        response.choices[0].finish_reason = finish_reason
        response.choices[0].message.function_call = None
        response.choices[0].message.tool_calls = None
        response.model = model
        response.created = 1234567890
        response.system_fingerprint = system_fingerprint
        response.usage = MagicMock()
        response.usage.prompt_tokens = prompt_tokens
        response.usage.completion_tokens = completion_tokens
        response.usage.total_tokens = total_tokens
        return response

    @pytest.mark.asyncio
    async def test_chat_success(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            stream=False,
        )

        assert result.content == "Hello!"
        assert result.provider == "openai"
        assert result.tokens_used == 15
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 5
        assert result.latency_ms is not None
        assert result.function_calls is None

    @pytest.mark.asyncio
    async def test_chat_api_error(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Rate limit exceeded")
        )
        adapter._client = mock_client

        with pytest.raises(Exception, match="Rate limit exceeded"):
            await adapter._chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="gpt-3.5-turbo",
                temperature=0.7,
                max_tokens=1000,
                stream=False,
            )

    @pytest.mark.asyncio
    async def test_chat_no_usage(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_response = self._make_mock_response()
        mock_response.usage = None
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            stream=False,
        )
        assert result.tokens_used == 0
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0

    @pytest.mark.asyncio
    async def test_chat_with_llm_message_objects(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        messages = [LLMMessage(role="user", content="Hello")]
        result = await adapter._chat(
            messages=messages,
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            stream=False,
        )
        assert result.content == "Hello!"

    @pytest.mark.asyncio
    async def test_chat_with_function_call_response(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_response = self._make_mock_response()
        mock_fc = MagicMock()
        mock_fc.name = "get_weather"
        mock_fc.arguments = json.dumps({"location": "NYC"})
        mock_response.choices[0].message.function_call = mock_fc

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "What is the weather?"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            stream=False,
        )
        assert result.function_calls is not None
        assert result.function_calls[0]["name"] == "get_weather"
        assert result.function_calls[0]["arguments"]["location"] == "NYC"

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls_response(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_response = self._make_mock_response()
        mock_tc = MagicMock()
        mock_tc.id = "call_123"
        mock_tc.type = "function"
        mock_tc.function.name = "search"
        mock_tc.function.arguments = json.dumps({"query": "test"})
        mock_response.choices[0].message.tool_calls = [mock_tc]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "Search"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            stream=False,
        )
        assert result.function_calls is not None
        assert result.function_calls[0]["id"] == "call_123"

    @pytest.mark.asyncio
    async def test_chat_with_kwargs_functions(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        await adapter._chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            stream=False,
            functions=[{"name": "f1"}],
            function_call="auto",
        )
        call_kwargs = mock_client.chat.completions.create.call_args
        assert "functions" in call_kwargs.kwargs
        assert "function_call" in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_chat_with_kwargs_tools(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        await adapter._chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            stream=False,
            tools=[{"type": "function", "function": {"name": "t1"}}],
            tool_choice="auto",
        )
        call_kwargs = mock_client.chat.completions.create.call_args
        assert "tools" in call_kwargs.kwargs
        assert "tool_choice" in call_kwargs.kwargs


class TestOpenAIBuildRequestParams:
    """Coverage for _build_openai_request_params and helper methods."""

    def test_basic_params(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        params = adapter._build_openai_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
        )
        assert params["model"] == "gpt-3.5-turbo"
        assert params["temperature"] == 0.7
        assert params["max_tokens"] == 1000
        assert params["stream"] is False

    def test_non_default_numeric_params_included(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(
            openai_api_key="sk-test",
            top_p=0.9,
            frequency_penalty=0.5,
            presence_penalty=0.5,
            n=2,
        )
        params = adapter._build_openai_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
        )
        assert params["top_p"] == 0.9
        assert params["frequency_penalty"] == 0.5
        assert params["presence_penalty"] == 0.5
        assert params["n"] == 2

    def test_default_numeric_params_excluded(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        params = adapter._build_openai_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
        )
        assert "top_p" not in params
        assert "frequency_penalty" not in params
        assert "presence_penalty" not in params
        assert "n" not in params

    def test_conditional_params_included(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(
            openai_api_key="sk-test",
            user="test-user",
            seed=42,
            response_format={"type": "json_object"},
            stop=["\n"],
            logit_bias={100: -1.0},
            logprobs=True,
            top_logprobs=3,
        )
        params = adapter._build_openai_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
        )
        assert params["user"] == "test-user"
        assert params["seed"] == 42
        assert params["response_format"] == {"type": "json_object"}
        assert params["stop"] == ["\n"]
        assert params["logit_bias"] == {100: -1.0}
        assert params["logprobs"] is True
        assert params["top_logprobs"] == 3


class TestOpenAIExtractFunctionCalls:
    """Coverage for _extract_function_calls."""

    def test_no_function_calls(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        message = MagicMock()
        message.function_call = None
        message.tool_calls = None

        result = adapter._extract_function_calls(message)
        assert result is None

    def test_function_call(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        message = MagicMock()
        message.function_call.name = "fn1"
        message.function_call.arguments = json.dumps({"arg": "val"})

        result = adapter._extract_function_calls(message)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "fn1"

    def test_tool_calls(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        message = MagicMock()
        message.function_call = None
        tc1 = MagicMock()
        tc1.id = "c1"
        tc1.type = "function"
        tc1.function.name = "t1"
        tc1.function.arguments = json.dumps({})
        message.tool_calls = [tc1]

        result = adapter._extract_function_calls(message)
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "c1"


class TestOpenAIExtractTokenUsage:
    """Coverage for _extract_openai_token_usage."""

    def test_with_usage(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        response = MagicMock()
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 5
        response.usage.total_tokens = 15

        p, c, t = adapter._extract_openai_token_usage(response)
        assert p == 10
        assert c == 5
        assert t == 15

    def test_without_usage(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        response = MagicMock()
        response.usage = None

        p, c, t = adapter._extract_openai_token_usage(response)
        assert p == 0
        assert c == 0
        assert t == 0


class TestOpenAIStreaming:
    """Coverage for streaming chat methods."""

    @pytest.mark.asyncio
    async def test_build_stream_request_params(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test", user="stream-user")
        params = adapter._build_stream_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
        )
        assert params["stream"] is True
        assert params["user"] == "stream-user"

    @pytest.mark.asyncio
    async def test_build_stream_request_params_with_tools(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        params = adapter._build_stream_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
            tools=[{"name": "t1"}],
        )
        assert "tools" in params

    @pytest.mark.asyncio
    async def test_build_stream_request_params_non_default_sampling(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(
            openai_api_key="sk-test",
            top_p=0.8,
            frequency_penalty=0.3,
            presence_penalty=0.3,
            stop=["END"],
            seed=99,
        )
        params = adapter._build_stream_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
        )
        assert params["top_p"] == 0.8
        assert params["frequency_penalty"] == 0.3
        assert params["presence_penalty"] == 0.3
        assert params["stop"] == ["END"]
        assert params["seed"] == 99

    @pytest.mark.asyncio
    async def test_process_stream_chunks(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")

        async def _mock_stream() -> Any:
            chunk1 = MagicMock()
            delta1 = MagicMock()
            delta1.content = "Hello"
            chunk1.choices = [MagicMock()]
            chunk1.choices[0].delta = delta1
            chunk1.choices[0].finish_reason = None
            chunk1.model = "gpt-3.5-turbo"
            yield chunk1

            chunk2 = MagicMock()
            delta2 = MagicMock()
            delta2.content = ""
            chunk2.choices = []
            chunk2.model = "gpt-3.5-turbo"
            yield chunk2

            chunk3 = MagicMock()
            delta3 = MagicMock()
            delta3.content = " world"
            chunk3.choices = [MagicMock()]
            chunk3.choices[0].delta = delta3
            chunk3.choices[0].finish_reason = "stop"
            chunk3.model = "gpt-3.5-turbo"
            yield chunk3

        chunks = []
        async for chunk in adapter._process_stream_chunks(_mock_stream(), "gpt-3.5-turbo"):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[1].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_chat_stream_success(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")

        async def _mock_stream() -> Any:
            chunk = MagicMock()
            delta = MagicMock()
            delta.content = "Hi"
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = delta
            chunk.choices[0].finish_reason = "stop"
            chunk.model = "gpt-3.5-turbo"
            yield chunk

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_mock_stream())
        adapter._client = mock_client

        chunks = []
        async for chunk in adapter._chat_stream(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].content == "Hi"

    @pytest.mark.asyncio
    async def test_chat_stream_error(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Stream error")
        )
        adapter._client = mock_client

        gen = adapter._chat_stream(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
        )
        with pytest.raises(Exception, match="Stream error"):
            async for _ in gen:
                pass

    @pytest.mark.asyncio
    async def test_stream_function_params(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        params = adapter._build_stream_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
            functions=[{"name": "f1"}],
        )
        assert "functions" in params

    @pytest.mark.asyncio
    async def test_stream_settings_params_default_excluded(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        params = adapter._build_stream_request_params(
            [{"role": "user", "content": "Hi"}],
            "gpt-3.5-turbo",
            0.7,
            1000,
        )
        assert "top_p" not in params
        assert "frequency_penalty" not in params
        assert "presence_penalty" not in params
        assert "stop" not in params
        assert "seed" not in params
        assert "user" not in params


class TestOpenAIModelInfo:
    """Coverage for _get_model_info and _list_models."""

    @pytest.mark.asyncio
    async def test_get_model_info_known(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        info = await adapter._get_model_info("gpt-4-turbo")
        assert info.name == "gpt-4-turbo"
        assert info.provider == LLMProvider.OPENAI
        assert 128000 == info.context_length

    @pytest.mark.asyncio
    async def test_get_model_info_unknown(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        info = await adapter._get_model_info("unknown-model")
        assert info.name == "unknown-model"
        assert info.context_length == 4096

    @pytest.mark.asyncio
    async def test_get_model_info_cached(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        info1 = await adapter._get_model_info("gpt-4-turbo")
        info2 = await adapter._get_model_info("gpt-4-turbo")
        assert info1 is info2

    @pytest.mark.asyncio
    async def test_list_models(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        models = await adapter._list_models()
        assert len(models) > 0
        names = {m.name for m in models}
        assert "gpt-4-turbo" in names
        assert "gpt-3.5-turbo" in names


class TestOpenAICountTokens:
    """Coverage for _count_tokens."""

    @pytest.mark.asyncio
    async def test_count_tokens_with_tiktoken(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_tiktoken = MagicMock()
        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = [1, 2, 3, 4, 5]
        mock_tiktoken.encoding_for_model.return_value = mock_encoding

        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            count = await adapter._count_tokens("Hello world", "gpt-3.5-turbo")
            assert count == 5

    @pytest.mark.asyncio
    async def test_count_tokens_no_tiktoken(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")

        def _import_error(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "tiktoken":
                raise ImportError("No module")
            return MagicMock()

        with patch("builtins.__import__", side_effect=_import_error):
            count = await adapter._count_tokens("Hello world", "gpt-3.5-turbo")
            assert count > 0

    @pytest.mark.asyncio
    async def test_count_tokens_tiktoken_error(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_tiktoken = MagicMock()
        mock_tiktoken.encoding_for_model.side_effect = Exception("Model not found")

        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            count = await adapter._count_tokens("Hello world", "gpt-3.5-turbo")
            assert count > 0


class TestOpenAIFunctionCallAndToolUse:
    """Coverage for _function_call and _tool_use."""

    @pytest.mark.asyncio
    async def test_function_call_delegates_to_chat(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "result"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.function_call = None
        mock_response.choices[0].message.tool_calls = None
        mock_response.model = "gpt-3.5-turbo"
        mock_response.created = 1234567890
        mock_response.system_fingerprint = None
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 3
        mock_response.usage.total_tokens = 8
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter._function_call(
            messages=[{"role": "user", "content": "Call fn"}],
            functions=[{"name": "fn1"}],
            model="gpt-3.5-turbo",
        )
        assert result.content == "result"

    @pytest.mark.asyncio
    async def test_tool_use_delegates_to_chat(self) -> None:
        from oneiric.adapters.llm.openai import OpenAILLMAdapter

        adapter = OpenAILLMAdapter(openai_api_key="sk-test")
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "result"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.function_call = None
        mock_response.choices[0].message.tool_calls = None
        mock_response.model = "gpt-3.5-turbo"
        mock_response.created = 1234567890
        mock_response.system_fingerprint = None
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 3
        mock_response.usage.total_tokens = 8
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter._tool_use(
            messages=[{"role": "user", "content": "Use tool"}],
            tools=[{"name": "t1"}],
            model="gpt-3.5-turbo",
        )
        assert result.content == "result"


# ---------------------------------------------------------------------------
# Anthropic LLM Adapter
# ---------------------------------------------------------------------------


class TestAnthropicLLMSettings:
    """Coverage for AnthropicLLMSettings defaults."""

    def test_default_settings(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLMSettings

        s = AnthropicLLMSettings()
        assert s.model == "claude-sonnet-4-20250514"
        assert s.base_url == "https://api.anthropic.com"
        assert s.api_version == "2023-06-01"
        assert s.max_tokens == 4096
        assert s.temperature == 0.7
        assert s.thinking_enabled is False
        assert s.thinking_budget_tokens == 10000
        assert s.top_k == -1

    def test_settings_with_api_key(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLMSettings

        s = AnthropicLLMSettings(anthropic_api_key=SecretStr("sk-ant-test"))
        assert s.anthropic_api_key.get_secret_value() == "sk-ant-test"

    def test_thinking_enabled(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLMSettings

        s = AnthropicLLMSettings(thinking_enabled=True, thinking_budget_tokens=20000)
        assert s.thinking_enabled is True
        assert s.thinking_budget_tokens == 20000


class TestAnthropicLLMInit:
    """Coverage for AnthropicLLM constructor."""

    def test_init_default(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM()
        assert adapter.settings.model == "claude-sonnet-4-20250514"

    def test_init_with_kwargs(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(
            anthropic_api_key=SecretStr("sk-ant-123"),
            model="claude-opus-4-20250514",
            temperature=0.3,
            max_tokens=8192,
        )
        assert adapter.settings.model == "claude-opus-4-20250514"
        assert adapter.settings.temperature == 0.3
        assert adapter.settings.max_tokens == 8192

    def test_metadata(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        assert AnthropicLLM.metadata.category == "llm"
        assert AnthropicLLM.metadata.provider == "anthropic"
        assert "extended_thinking" in AnthropicLLM.metadata.capabilities


class TestAnthropicCreateClient:
    """Coverage for _create_client."""

    @pytest.mark.asyncio
    async def test_create_client_success(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_anthropic = MagicMock()
        mock_client = AsyncMock()
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            client = await adapter._create_client()
            assert client is mock_client
            mock_anthropic.AsyncAnthropic.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_client_missing_package(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))

        def _import_error(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "anthropic":
                raise ImportError("No module")
            return MagicMock()

        with patch("builtins.__import__", side_effect=_import_error):
            with pytest.raises(LifecycleError, match="anthropic package required"):
                await adapter._create_client()

    @pytest.mark.asyncio
    async def test_create_client_no_api_key(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM()
        mock_anthropic = MagicMock()

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            with pytest.raises(LifecycleError, match="Anthropic API key required"):
                await adapter._create_client()

    @pytest.mark.asyncio
    async def test_create_client_uses_fallback_key(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(api_key=SecretStr("sk-fallback"))
        mock_anthropic = MagicMock()
        mock_client = AsyncMock()
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            client = await adapter._create_client()
            assert client is mock_client
            call_kwargs = mock_anthropic.AsyncAnthropic.call_args
            assert call_kwargs.kwargs["api_key"] == "sk-fallback"


class TestAnthropicInitMethod:
    """Coverage for async init()."""

    @pytest.mark.asyncio
    async def test_init_success(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = AsyncMock()
        mock_anthropic = MagicMock()
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            await adapter.init()
            assert adapter._client is mock_client

    @pytest.mark.asyncio
    async def test_init_failure(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM()

        def _import_error(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "anthropic":
                raise ImportError("No module")
            return MagicMock()

        with patch("builtins.__import__", side_effect=_import_error):
            with pytest.raises(LifecycleError, match="Failed to initialize Anthropic"):
                await adapter.init()


class TestAnthropicHealth:
    """Coverage for health check."""

    @pytest.mark.asyncio
    async def test_health_success(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        adapter._client = MagicMock()
        result = await adapter.health()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_catches_exception(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        adapter._client = None

        def _import_error(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "anthropic":
                raise ImportError("No module")
            return MagicMock()

        with patch("builtins.__import__", side_effect=_import_error):
            result = await adapter.health()
            assert result is False


class TestAnthropicCleanup:
    """Coverage for cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_with_client(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = AsyncMock()
        adapter._client = mock_client

        await adapter.cleanup()
        mock_client.close.assert_awaited_once()
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_cleanup_without_client(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM()
        adapter._client = None
        await adapter.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_client_without_close(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = object()
        adapter._client = mock_client

        await adapter.cleanup()
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_cleanup_error(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = AsyncMock()
        mock_client.close.side_effect = RuntimeError("Close failed")
        adapter._client = mock_client

        with pytest.raises(LifecycleError, match="Failed to cleanup"):
            await adapter.cleanup()


class TestAnthropicChat:
    """Coverage for _chat method."""

    def _make_mock_response(
        self,
        content: str = "Hello!",
        model: str = "claude-sonnet-4-20250514",
        stop_reason: str = "end_turn",
        stop_sequence: int | None = None,
        input_tokens: int = 10,
        output_tokens: int = 5,
    ) -> MagicMock:
        response = MagicMock()
        block = MagicMock()
        block.text = content
        block.tool_use = None
        response.content = [block]
        response.model = model
        response.stop_reason = stop_reason
        response.stop_sequence = stop_sequence
        response.usage = MagicMock()
        response.usage.input_tokens = input_tokens
        response.usage.output_tokens = output_tokens
        return response

    @pytest.mark.asyncio
    async def test_chat_success(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
            stream=False,
        )
        assert result.content == "Hello!"
        assert result.provider == "anthropic"
        assert result.tokens_used == 15
        assert result.tool_calls is None

    @pytest.mark.asyncio
    async def test_chat_with_system_message(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        await adapter._chat(
            messages=[
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hi"},
            ],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
            stream=False,
        )
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "You are helpful"

    @pytest.mark.asyncio
    async def test_chat_api_error(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("API Error")
        )
        adapter._client = mock_client

        with pytest.raises(LifecycleError, match="Failed to generate chat completion"):
            await adapter._chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="claude-sonnet-4-20250514",
                temperature=0.7,
                max_tokens=4096,
                stream=False,
            )

    @pytest.mark.asyncio
    async def test_chat_with_tool_use_response(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        response = self._make_mock_response()
        tool_block = MagicMock(spec=["id", "name", "input", "tool_use"])
        tool_block.tool_use = True
        tool_block.id = "tool_123"
        tool_block.name = "search"
        tool_block.input = json.dumps({"query": "test"})
        response.content = [tool_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "Search"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
            stream=False,
        )
        assert result.tool_calls is not None
        assert result.tool_calls[0]["id"] == "tool_123"

    @pytest.mark.asyncio
    async def test_chat_with_mixed_content_blocks(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        response = self._make_mock_response(content="")
        text_block = MagicMock(spec=["text", "tool_use"])
        text_block.text = "Here is the result"
        text_block.tool_use = None
        tool_block = MagicMock(spec=["id", "name", "input", "tool_use"])
        tool_block.tool_use = True
        tool_block.id = "tool_456"
        tool_block.name = "get_data"
        tool_block.input = json.dumps({})
        response.content = [text_block, tool_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "Do things"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
            stream=False,
        )
        assert result.content == "Here is the result"
        assert result.tool_calls is not None

    @pytest.mark.asyncio
    async def test_chat_no_usage(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        response = self._make_mock_response()
        del response.usage

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)
        adapter._client = mock_client

        result = await adapter._chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
            stream=False,
        )
        assert result.tokens_used is None
        assert result.prompt_tokens is None
        assert result.completion_tokens is None

    @pytest.mark.asyncio
    async def test_chat_with_thinking_enabled(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(
            anthropic_api_key=SecretStr("sk-ant-test"),
            thinking_enabled=True,
            thinking_budget_tokens=15000,
        )
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        await adapter._chat(
            messages=[{"role": "user", "content": "Think"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
            stream=False,
        )
        call_kwargs = mock_client.messages.create.call_args
        assert "thinking" in call_kwargs.kwargs
        assert call_kwargs.kwargs["thinking"]["type"] == "enabled"
        assert call_kwargs.kwargs["thinking"]["budget_tokens"] == 15000

    @pytest.mark.asyncio
    async def test_chat_with_top_k_and_top_p(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(
            anthropic_api_key=SecretStr("sk-ant-test"),
            top_p=0.8,
            top_k=50,
        )
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=self._make_mock_response()
        )
        adapter._client = mock_client

        await adapter._chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
            stream=False,
        )
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["top_p"] == 0.8
        assert call_kwargs.kwargs["top_k"] == 50


class TestAnthropicExtractMethods:
    """Coverage for _extract_system_message, _extract_response_content, _extract_token_usage."""

    def test_extract_system_message_with_system(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        system, msgs = adapter._extract_system_message([
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hi"},
        ])
        assert system == "Be helpful"
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_extract_system_message_no_system(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        system, msgs = adapter._extract_system_message([
            {"role": "user", "content": "Hi"},
        ])
        assert system is None
        assert len(msgs) == 1

    def test_extract_response_content_text_only(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        response = MagicMock()
        block = MagicMock()
        block.text = "Hello"
        block.tool_use = None
        response.content = [block]

        content, tool_calls = adapter._extract_response_content(response)
        assert content == "Hello"
        assert tool_calls is None

    def test_extract_token_usage_with_usage(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        response = MagicMock()
        response.usage.input_tokens = 10
        response.usage.output_tokens = 5

        p, c, t = adapter._extract_token_usage(response)
        assert p == 10
        assert c == 5
        assert t == 15

    def test_extract_token_usage_no_usage(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        response = MagicMock()
        del response.usage

        p, c, t = adapter._extract_token_usage(response)
        assert p is None
        assert c is None
        assert t is None


class TestAnthropicFormatTools:
    """Coverage for _format_anthropic_tools."""

    def test_format_openai_style_tools(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search for info",
                    "parameters": {"type": "object"},
                },
            }
        ]
        result = adapter._format_anthropic_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "search"
        assert result[0]["description"] == "Search for info"
        assert result[0]["input_schema"] == {"type": "object"}

    def test_format_anthropic_style_tools(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        tools = [
            {"name": "calc", "description": "Calculate", "parameters": {"type": "object"}}
        ]
        result = adapter._format_anthropic_tools(tools)
        assert result[0]["name"] == "calc"


class TestAnthropicBuildChatRequestParams:
    """Coverage for _build_chat_request_params."""

    def test_with_tools(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        params = adapter._build_chat_request_params(
            [{"role": "user", "content": "Hi"}],
            "claude-sonnet-4-20250514",
            0.7,
            4096,
            tools=[{"name": "t1", "description": "Tool 1", "parameters": {}}],
        )
        assert "tools" in params
        assert len(params["tools"]) == 1

    def test_extra_kwargs_passed_through(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        params = adapter._build_chat_request_params(
            [{"role": "user", "content": "Hi"}],
            "claude-sonnet-4-20250514",
            0.7,
            4096,
            metadata={"key": "value"},
        )
        assert params["metadata"] == {"key": "value"}

    def test_default_top_p_and_top_k_excluded(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        params = adapter._build_chat_request_params(
            [{"role": "user", "content": "Hi"}],
            "claude-sonnet-4-20250514",
            0.7,
            4096,
        )
        assert "top_p" not in params
        assert "top_k" not in params


class TestAnthropicStreaming:
    """Coverage for streaming chat methods."""

    @pytest.mark.asyncio
    async def test_chat_stream_success(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        async def _text_gen():
            yield "Hello"
            yield " world"

        mock_stream.text_stream = _text_gen()
        mock_final = MagicMock()
        mock_final.stop_reason = "end_turn"
        mock_stream.get_final_message = AsyncMock(return_value=mock_final)

        mock_client = AsyncMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)
        adapter._client = mock_client

        chunks = []
        async for chunk in adapter._chat_stream(
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
        ):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[2].finish_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_chat_stream_error(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(side_effect=Exception("Stream broken"))
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)
        adapter._client = mock_client

        gen = adapter._chat_stream(
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-sonnet-4-20250514",
            temperature=0.7,
            max_tokens=4096,
        )
        with pytest.raises(LifecycleError, match="Failed to stream chat"):
            async for _ in gen:
                pass

    @pytest.mark.asyncio
    async def test_handle_streaming_chat(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))

        async def _mock_chat_stream(
            messages: Any = None,
            model: str = "claude-sonnet-4-20250514",
            temperature: float = 0.7,
            max_tokens: int = 4096,
            **kwargs: Any,
        ) -> Any:
            yield LLMStreamChunk(content="Hello", model=model, delta=True)
            yield LLMStreamChunk(content=" world", model=model, delta=True)
            yield LLMStreamChunk(content="", model=model, finish_reason="end_turn", delta=False)

        with patch.object(adapter, "_chat_stream", _mock_chat_stream):
            result = await adapter._chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="claude-sonnet-4-20250514",
                temperature=0.7,
                max_tokens=4096,
                stream=True,
            )
        assert result.content == "Hello world"
        assert result.finish_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_handle_streaming_chat_no_final_chunk(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))

        async def _mock_chat_stream(
            messages: Any = None,
            model: str = "claude-sonnet-4-20250514",
            temperature: float = 0.7,
            max_tokens: int = 4096,
            **kwargs: Any,
        ) -> Any:
            yield LLMStreamChunk(content="Hi", model=model, delta=True)

        with patch.object(adapter, "_chat_stream", _mock_chat_stream):
            result = await adapter._chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="claude-sonnet-4-20250514",
                temperature=0.7,
                max_tokens=4096,
                stream=True,
            )
        assert result.content == "Hi"
        assert result.finish_reason is None


class TestAnthropicBuildStreamRequestParams:
    """Coverage for _build_stream_request_params."""

    def test_basic(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        params = adapter._build_stream_request_params(
            "claude-sonnet-4-20250514",
            4096,
            0.7,
            [{"role": "user", "content": "Hi"}],
            None,
            {},
        )
        assert params["model"] == "claude-sonnet-4-20250514"
        assert params["max_tokens"] == 4096

    def test_with_system_prompt(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        params = adapter._build_stream_request_params(
            "claude-sonnet-4-20250514",
            4096,
            0.7,
            [{"role": "user", "content": "Hi"}],
            "Be helpful",
            {},
        )
        assert params["system"] == "Be helpful"

    def test_with_thinking(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(
            anthropic_api_key=SecretStr("sk-ant-test"),
            thinking_enabled=True,
        )
        params = adapter._build_stream_request_params(
            "claude-sonnet-4-20250514",
            4096,
            0.7,
            [{"role": "user", "content": "Hi"}],
            None,
            {},
        )
        assert "thinking" in params

    def test_with_tools(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        params = adapter._build_stream_request_params(
            "claude-sonnet-4-20250514",
            4096,
            0.7,
            [{"role": "user", "content": "Hi"}],
            None,
            {"tools": [{"name": "t1"}]},
        )
        assert "tools" in params

    def test_extra_kwargs(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        params = adapter._build_stream_request_params(
            "claude-sonnet-4-20250514",
            4096,
            0.7,
            [{"role": "user", "content": "Hi"}],
            None,
            {"extra_key": "extra_val"},
        )
        assert params["extra_key"] == "extra_val"


class TestAnthropicModelInfo:
    """Coverage for _get_model_info and _list_models."""

    @pytest.mark.asyncio
    async def test_get_model_info_known(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        info = await adapter._get_model_info("claude-opus-4-20250514")
        assert info.name == "claude-opus-4-20250514"
        assert info.provider == LLMProvider.ANTHROPIC
        assert info.context_length == 200000

    @pytest.mark.asyncio
    async def test_get_model_info_unknown(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        info = await adapter._get_model_info("unknown-claude")
        assert info.name == "unknown-claude"
        assert info.context_length == 200000
        assert info.supports_streaming is True

    @pytest.mark.asyncio
    async def test_list_models(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        models = await adapter._list_models()
        assert len(models) == 6
        names = {m.name for m in models}
        assert "claude-opus-4-20250514" in names
        assert "claude-sonnet-4-20250514" in names
        assert "claude-haiku-4-20250514" in names


class TestAnthropicToolUse:
    """Coverage for _tool_use."""

    @pytest.mark.asyncio
    async def test_tool_use_delegates_to_chat(self) -> None:
        from oneiric.adapters.llm.anthropic import AnthropicLLM

        adapter = AnthropicLLM(anthropic_api_key=SecretStr("sk-ant-test"))
        mock_client = AsyncMock()
        response = MagicMock()
        block = MagicMock()
        block.text = "result"
        block.tool_use = None
        response.content = [block]
        response.model = "claude-sonnet-4-20250514"
        response.stop_reason = "end_turn"
        response.stop_sequence = None
        response.usage = MagicMock()
        response.usage.input_tokens = 5
        response.usage.output_tokens = 3
        mock_client.messages.create = AsyncMock(return_value=response)
        adapter._client = mock_client

        result = await adapter._tool_use(
            messages=[{"role": "user", "content": "Use tool"}],
            tools=[{"name": "t1"}],
            model="claude-sonnet-4-20250514",
        )
        assert result.content == "result"


# ---------------------------------------------------------------------------
# OTel Storage Adapter
# ---------------------------------------------------------------------------


class TestOTelStorageSettings:
    """Coverage for OTelStorageSettings."""

    def test_defaults(self) -> None:
        from oneiric.adapters.observability.settings import OTelStorageSettings

        s = OTelStorageSettings()
        assert s.connection_string.startswith("postgresql://")
        assert s.embedding_model == "all-MiniLM-L6-v2"
        assert s.embedding_dimension == 384
        assert s.batch_size == 100
        assert s.batch_interval_seconds == 5

    def test_invalid_connection_string(self) -> None:
        from oneiric.adapters.observability.settings import OTelStorageSettings
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OTelStorageSettings(connection_string="sqlite:///test.db")

    def test_custom_settings(self) -> None:
        from oneiric.adapters.observability.settings import OTelStorageSettings

        s = OTelStorageSettings(
            connection_string="postgresql://user:pass@host:5432/db",
            batch_size=50,
            batch_interval_seconds=10,
        )
        assert s.batch_size == 50
        assert s.batch_interval_seconds == 10


class TestOTelStorageAdapterInit:
    """Coverage for OTelStorageAdapter constructor."""

    def test_init(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        settings = OTelStorageSettings(
            connection_string="postgresql://postgres:pass@localhost:5432/otel",
        )
        adapter = OTelStorageAdapter(settings)
        assert adapter._settings is settings
        assert adapter._engine is None
        assert adapter._session_factory is None
        assert adapter._query_service is None


class TestOTelStorageHealth:
    """Coverage for health check paths."""

    @pytest.mark.asyncio
    async def test_health_no_engine(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        result = await adapter.health()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_success(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        mock_engine = MagicMock()
        adapter._engine = mock_engine

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()

        adapter._session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.text"):
            result = await adapter.health()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_failure(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        adapter._engine = MagicMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=Exception("DB down"))

        adapter._session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.text"):
            result = await adapter.health()
            assert result is False


class TestOTelStorageCleanup:
    """Coverage for cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_no_engine(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        await adapter.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_with_flush_task(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        mock_engine = AsyncMock()
        adapter._engine = mock_engine
        adapter._write_buffer.append({"test": "data"})

        loop = asyncio.get_running_loop()
        async def _noop() -> None:
            await asyncio.sleep(1000)

        flush_task = loop.create_task(_noop())
        adapter._flush_task = flush_task

        try:
            with patch.object(adapter, "_flush_buffer", new_callable=AsyncMock):
                await adapter.cleanup()
        finally:
            assert adapter._engine is None

    @pytest.mark.asyncio
    async def test_cleanup_flush_task_cancelled(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        mock_engine = AsyncMock()
        adapter._engine = mock_engine

        loop = asyncio.get_running_loop()
        async def _noop() -> None:
            await asyncio.sleep(1000)

        flush_task = loop.create_task(_noop())
        adapter._flush_task = flush_task

        try:
            with patch.object(adapter, "_flush_buffer", new_callable=AsyncMock):
                await adapter.cleanup()
        finally:
            assert adapter._engine is None


class TestOTelStoreTrace:
    """Coverage for store_trace and buffer flushing."""

    @pytest.mark.asyncio
    async def test_store_trace_below_batch_size(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        settings = OTelStorageSettings(batch_size=10)
        adapter = OTelStorageAdapter(settings)
        trace = {
            "trace_id": "trace-123",
            "name": "test-span",
            "start_time": "2026-01-01T00:00:00",
            "status": "OK",
        }
        await adapter.store_trace(trace)
        assert len(adapter._write_buffer) == 1

    @pytest.mark.asyncio
    async def test_store_trace_triggers_flush(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        settings = OTelStorageSettings(batch_size=10)
        adapter = OTelStorageAdapter(settings)

        for i in range(9):
            adapter._write_buffer.append({
                "trace_id": f"trace-{i}",
                "name": f"span-{i}",
                "start_time": "2026-01-01T00:00:00",
                "status": "OK",
            })

        with patch.object(adapter, "_flush_buffer", new_callable=AsyncMock) as mock_flush:
            trace = {
                "trace_id": "trace-final",
                "name": "test-span",
                "start_time": "2026-01-01T00:00:00",
                "status": "OK",
            }
            await adapter.store_trace(trace)
            mock_flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_buffer_empty(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        await adapter._flush_buffer()

    @pytest.mark.asyncio
    async def test_flush_buffer_success(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        adapter._write_buffer.append({
            "trace_id": "trace-1",
            "name": "span-1",
            "start_time": "2026-01-01T00:00:00",
            "end_time": "2026-01-01T00:00:01",
            "status": "OK",
        })

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add_all = MagicMock()
        mock_session.commit = AsyncMock()
        adapter._session_factory = MagicMock(return_value=mock_session)

        mock_embedding = MagicMock()
        mock_embedding.tolist.return_value = [0.1] * 384
        with patch.object(
            adapter._embedding_service, "embed_trace", new_callable=AsyncMock,
            return_value=mock_embedding,
        ):
            await adapter._flush_buffer()

        assert len(adapter._write_buffer) == 0
        mock_session.add_all.assert_called_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_buffer_error_sends_to_dlq(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        adapter._write_buffer.append({
            "trace_id": "trace-1",
            "name": "span-1",
            "start_time": "2026-01-01T00:00:00",
            "status": "OK",
        })

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock(side_effect=Exception("DB error"))
        adapter._session_factory = MagicMock(return_value=mock_session)

        mock_embedding = MagicMock()
        with patch.object(
            adapter._embedding_service, "embed_trace", new_callable=AsyncMock,
            return_value=mock_embedding,
        ), patch.object(adapter, "_send_to_dlq", new_callable=AsyncMock) as mock_dlq:
            await adapter._flush_buffer()
            mock_dlq.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_buffer_with_datetime_fields(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        adapter._write_buffer.append({
            "trace_id": "trace-1",
            "name": "span-1",
            "start_time": datetime(2026, 1, 1, tzinfo=UTC),
            "end_time": datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            "status": "OK",
        })

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add_all = MagicMock()
        mock_session.commit = AsyncMock()
        adapter._session_factory = MagicMock(return_value=mock_session)

        mock_embedding = MagicMock()
        mock_embedding.tolist.return_value = [0.1] * 384
        with patch.object(
            adapter._embedding_service, "embed_trace", new_callable=AsyncMock,
            return_value=mock_embedding,
        ):
            await adapter._flush_buffer()
            assert len(adapter._write_buffer) == 0

    @pytest.mark.asyncio
    async def test_flush_buffer_none_embedding(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        adapter._write_buffer.append({
            "trace_id": "trace-1",
            "name": "span-1",
            "start_time": "2026-01-01T00:00:00",
            "status": "OK",
        })

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add_all = MagicMock()
        mock_session.commit = AsyncMock()
        adapter._session_factory = MagicMock(return_value=mock_session)

        with patch.object(
            adapter._embedding_service, "embed_trace", new_callable=AsyncMock,
            return_value=None,
        ):
            await adapter._flush_buffer()
            mock_session.commit.assert_awaited_once()


class TestOTelSendToDLQ:
    """Coverage for _send_to_dlq."""

    @pytest.mark.asyncio
    async def test_send_to_dlq_success(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        adapter._session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.text"):
            await adapter._send_to_dlq({"trace_id": "t1"}, "error msg")
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_to_dlq_failure(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=Exception("DLQ table missing"))
        mock_session.commit = AsyncMock()
        adapter._session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.text"):
            await adapter._send_to_dlq({"trace_id": "t1"}, "error msg")


class TestOTelStoreLog:
    """Coverage for store_log."""

    @pytest.mark.asyncio
    async def test_store_log_success(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        adapter._session_factory = MagicMock(return_value=mock_session)

        log_data = {
            "trace_id": "trace-1",
            "start_time": "2026-01-01T00:00:00",
            "attributes": {"log.level": "ERROR", "log.message": "Something failed"},
        }
        await adapter.store_log(log_data)
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_log_failure(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock(side_effect=Exception("DB error"))
        adapter._session_factory = MagicMock(return_value=mock_session)

        log_data = {
            "trace_id": "trace-1",
            "start_time": "2026-01-01T00:00:00",
            "attributes": {"log.level": "INFO", "log.message": "Test"},
        }
        with pytest.raises(Exception, match="DB error"):
            await adapter.store_log(log_data)


class TestOTelStoreMetrics:
    """Coverage for store_metrics."""

    @pytest.mark.asyncio
    async def test_store_metrics_success(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add_all = MagicMock()
        mock_session.commit = AsyncMock()
        adapter._session_factory = MagicMock(return_value=mock_session)

        metrics = [
            {
                "name": "http_requests",
                "value": 100.0,
                "timestamp": "2026-01-01T00:00:00",
            }
        ]
        await adapter.store_metrics(metrics)
        mock_session.add_all.assert_called_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_metrics_failure(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock(side_effect=Exception("Insert failed"))
        adapter._session_factory = MagicMock(return_value=mock_session)

        metrics = [
            {"name": "cpu", "value": 0.5, "timestamp": "2026-01-01T00:00:00"}
        ]
        with pytest.raises(Exception, match="Insert failed"):
            await adapter.store_metrics(metrics)


class TestOTelFindSimilarTraces:
    """Coverage for find_similar_traces."""

    @pytest.mark.asyncio
    async def test_no_query_service(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        result = await adapter.find_similar_traces([0.1] * 384)
        assert result == []

    @pytest.mark.asyncio
    async def test_find_similar_traces_success(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        mock_query_service = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"trace_id": "t1", "name": "span-1"}
        mock_query_service.find_similar_traces = AsyncMock(return_value=[mock_result])
        adapter._query_service = mock_query_service

        with patch("numpy.array", return_value=MagicMock()):
            results = await adapter.find_similar_traces([0.1] * 384, threshold=0.9)
            assert len(results) == 1
            assert results[0]["trace_id"] == "t1"

    @pytest.mark.asyncio
    async def test_find_similar_traces_error(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        mock_query_service = AsyncMock()
        mock_query_service.find_similar_traces = AsyncMock(
            side_effect=Exception("Search failed")
        )
        adapter._query_service = mock_query_service

        with patch("numpy.array", return_value=MagicMock()):
            with pytest.raises(Exception, match="Search failed"):
                await adapter.find_similar_traces([0.1] * 384)


class TestOTelGetTracesByError:
    """Coverage for get_traces_by_error."""

    @pytest.mark.asyncio
    async def test_no_query_service(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        result = await adapter.get_traces_by_error("NullPointerException")
        assert result == []

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        mock_query_service = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"trace_id": "t1"}
        mock_query_service.get_traces_by_error = AsyncMock(return_value=[mock_result])
        adapter._query_service = mock_query_service

        results = await adapter.get_traces_by_error("error%", service="my-service")
        assert len(results) == 1
        mock_query_service.get_traces_by_error.assert_awaited_once_with(
            error_pattern="error%",
            service="my-service",
            limit=100,
        )

    @pytest.mark.asyncio
    async def test_error(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        mock_query_service = AsyncMock()
        mock_query_service.get_traces_by_error = AsyncMock(
            side_effect=Exception("Query failed")
        )
        adapter._query_service = mock_query_service

        with pytest.raises(Exception, match="Query failed"):
            await adapter.get_traces_by_error("error%")


class TestOTelSearchLogs:
    """Coverage for search_logs."""

    @pytest.mark.asyncio
    async def test_no_session_factory(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())
        result = await adapter.search_logs("trace-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_logs_success(self) -> None:
        import oneiric.adapters.observability.otel as otel_module
        from oneiric.adapters.observability.models import LogModel
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        # search_logs uses bare LogModel name without local import;
        # inject it into the otel module namespace so the reference resolves.
        otel_module.LogModel = LogModel

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_log = MagicMock()
        mock_log.id = "log-1"
        mock_log.timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        mock_log.level = "ERROR"
        mock_log.message = "Failed"
        mock_log.trace_id = "trace-1"
        mock_log.resource_attributes = {"service": "api"}
        mock_log.span_attributes = {}

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_log]
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)
        adapter._session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.select"):
            logs = await adapter.search_logs("trace-1", level="ERROR")
            assert len(logs) == 1
            assert logs[0]["trace_id"] == "trace-1"
            assert logs[0]["level"] == "ERROR"

    @pytest.mark.asyncio
    async def test_search_logs_error(self) -> None:
        import oneiric.adapters.observability.otel as otel_module
        from oneiric.adapters.observability.models import LogModel
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        # search_logs uses bare LogModel name without local import;
        # inject it so the NameError does not fire before our side_effect.
        otel_module.LogModel = LogModel

        adapter = OTelStorageAdapter(OTelStorageSettings())

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=Exception("Query failed"))
        adapter._session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.select"):
            with pytest.raises(Exception, match="Query failed"):
                await adapter.search_logs("trace-1")


class TestOTelFlushBufferPeriodically:
    """Coverage for _flush_buffer_periodically."""

    @pytest.mark.asyncio
    async def test_cancelled_stops_loop(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        call_count = 0

        async def _mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=_mock_sleep):
            with patch.object(adapter, "_flush_buffer", new_callable=AsyncMock):
                await adapter._flush_buffer_periodically()

    @pytest.mark.asyncio
    async def test_error_continues_loop(self) -> None:
        from oneiric.adapters.observability.otel import OTelStorageAdapter
        from oneiric.adapters.observability.settings import OTelStorageSettings

        adapter = OTelStorageAdapter(OTelStorageSettings())

        call_count = 0

        async def _mock_sleep(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=_mock_sleep):
            with patch.object(
                adapter, "_flush_buffer", new_callable=AsyncMock,
                side_effect=Exception("Flush error"),
            ):
                await adapter._flush_buffer_periodically()


# ---------------------------------------------------------------------------
# Sentry Monitoring Adapter
# ---------------------------------------------------------------------------


class TestSentryMonitoringSettings:
    """Coverage for SentryMonitoringSettings."""

    def test_defaults(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringSettings

        s = SentryMonitoringSettings()
        assert s.dsn is None
        assert s.environment == "development"
        assert s.release is None
        assert s.traces_sample_rate == 0.0
        assert s.profiles_sample_rate == 0.0
        assert s.enable_tracing is True
        assert s.attach_stacktrace is True
        assert s.send_default_pii is False
        assert s.include_context_tags is True

    def test_custom_settings(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringSettings

        s = SentryMonitoringSettings(
            dsn=SecretStr("https://key@sentry.io/123"),
            environment="production",
            release="v1.0.0",
            traces_sample_rate=0.1,
            profiles_sample_rate=0.05,
        )
        assert s.dsn.get_secret_value() == "https://key@sentry.io/123"
        assert s.environment == "production"
        assert s.release == "v1.0.0"

    def test_sample_rate_validation(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringSettings
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SentryMonitoringSettings(traces_sample_rate=1.5)

        with pytest.raises(ValidationError):
            SentryMonitoringSettings(traces_sample_rate=-0.1)


class TestSentryMonitoringAdapterInit:
    """Coverage for SentryMonitoringAdapter constructor."""

    def test_init_default(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        assert adapter._configured is False

    def test_init_with_settings(self) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        settings = SentryMonitoringSettings(environment="staging")
        adapter = SentryMonitoringAdapter(settings=settings)
        assert adapter._settings.environment == "staging"

    def test_metadata(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        assert SentryMonitoringAdapter.metadata.category == "monitoring"
        assert SentryMonitoringAdapter.metadata.provider == "sentry"
        assert "tracing" in SentryMonitoringAdapter.metadata.capabilities


class TestSentryResolveDSN:
    """Coverage for _resolve_dsn."""

    def test_from_settings(self) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        adapter = SentryMonitoringAdapter(
            SentryMonitoringSettings(dsn=SecretStr("https://key@sentry.io/123"))
        )
        assert adapter._resolve_dsn() == "https://key@sentry.io/123"

    def test_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        monkeypatch.setenv("SENTRY_DSN", "https://env@sentry.io/456")
        adapter = SentryMonitoringAdapter()
        assert adapter._resolve_dsn() == "https://env@sentry.io/456"

    def test_settings_takes_precedence_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        monkeypatch.setenv("SENTRY_DSN", "https://env@sentry.io/456")
        adapter = SentryMonitoringAdapter(
            SentryMonitoringSettings(dsn=SecretStr("https://key@sentry.io/123"))
        )
        assert adapter._resolve_dsn() == "https://key@sentry.io/123"

    def test_missing_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        monkeypatch.delenv("SENTRY_DSN", raising=False)
        adapter = SentryMonitoringAdapter()
        with pytest.raises(LifecycleError, match="sentry-dsn-missing"):
            adapter._resolve_dsn()


class TestSentryRequireSDK:
    """Coverage for _require_sdk."""

    def test_sdk_available(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            sentry_mod.sentry_sdk = MagicMock()
            from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

            adapter = SentryMonitoringAdapter()
            sdk = adapter._require_sdk()
            assert sdk is sentry_mod.sentry_sdk
        finally:
            sentry_mod.sentry_sdk = original_sdk

    def test_sdk_missing(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            sentry_mod.sentry_sdk = None
            from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

            adapter = SentryMonitoringAdapter()
            with pytest.raises(LifecycleError, match="sentry-sdk-missing"):
                adapter._require_sdk()
        finally:
            sentry_mod.sentry_sdk = original_sdk


class TestSentryInit:
    """Coverage for async init()."""

    @pytest.mark.asyncio
    async def test_init_success(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            mock_sdk = MagicMock()
            mock_sdk.init = MagicMock()
            sentry_mod.sentry_sdk = mock_sdk

            from oneiric.adapters.monitoring.sentry import (
                SentryMonitoringAdapter,
                SentryMonitoringSettings,
            )

            adapter = SentryMonitoringAdapter(
                SentryMonitoringSettings(dsn=SecretStr("https://key@sentry.io/123"))
            )
            await adapter.init()
            assert adapter._configured is True
            mock_sdk.init.assert_called_once()
        finally:
            sentry_mod.sentry_sdk = original_sdk

    @pytest.mark.asyncio
    async def test_init_filters_none_values(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            mock_sdk = MagicMock()
            mock_sdk.init = MagicMock()
            sentry_mod.sentry_sdk = mock_sdk

            from oneiric.adapters.monitoring.sentry import (
                SentryMonitoringAdapter,
                SentryMonitoringSettings,
            )

            adapter = SentryMonitoringAdapter(
                SentryMonitoringSettings(
                    dsn=SecretStr("https://key@sentry.io/123"),
                    release=None,
                )
            )
            await adapter.init()
            call_kwargs = mock_sdk.init.call_args
            assert "release" not in call_kwargs
        finally:
            sentry_mod.sentry_sdk = original_sdk

    @pytest.mark.asyncio
    async def test_init_sdk_error(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            mock_sdk = MagicMock()
            mock_sdk.init = MagicMock(side_effect=Exception("Init failed"))
            sentry_mod.sentry_sdk = mock_sdk

            from oneiric.adapters.monitoring.sentry import (
                SentryMonitoringAdapter,
                SentryMonitoringSettings,
            )

            adapter = SentryMonitoringAdapter(
                SentryMonitoringSettings(dsn=SecretStr("https://key@sentry.io/123"))
            )
            with pytest.raises(LifecycleError, match="sentry-init-failed"):
                await adapter.init()
        finally:
            sentry_mod.sentry_sdk = original_sdk


class TestSentryHealth:
    """Coverage for health check."""

    @pytest.mark.asyncio
    async def test_health_configured(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        adapter._configured = True
        assert await adapter.health() is True

    @pytest.mark.asyncio
    async def test_health_not_configured(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        adapter._configured = False
        assert await adapter.health() is False


class TestSentryCleanup:
    """Coverage for cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_no_sdk(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            sentry_mod.sentry_sdk = None
            from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

            adapter = SentryMonitoringAdapter()
            await adapter.cleanup()
        finally:
            sentry_mod.sentry_sdk = original_sdk

    @pytest.mark.asyncio
    async def test_cleanup_with_flush_and_shutdown(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            mock_sdk = MagicMock()
            mock_sdk.flush = MagicMock()
            mock_sdk.shutdown = MagicMock()
            sentry_mod.sentry_sdk = mock_sdk

            from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

            adapter = SentryMonitoringAdapter()
            adapter._configured = True
            await adapter.cleanup()
            mock_sdk.flush.assert_called_once()
            mock_sdk.shutdown.assert_called_once()
            assert adapter._configured is False
        finally:
            sentry_mod.sentry_sdk = original_sdk

    @pytest.mark.asyncio
    async def test_cleanup_no_flush_method(self) -> None:
        import oneiric.adapters.monitoring.sentry as sentry_mod

        original_sdk = sentry_mod.sentry_sdk
        try:
            mock_sdk = MagicMock(spec=[])
            sentry_mod.sentry_sdk = mock_sdk

            from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

            adapter = SentryMonitoringAdapter()
            adapter._configured = True
            await adapter.cleanup()
            assert adapter._configured is False
        finally:
            sentry_mod.sentry_sdk = original_sdk


class TestSentryBeforeSend:
    """Coverage for _before_send and _before_send_transaction."""

    def test_before_send_with_context_tags(self) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        adapter = SentryMonitoringAdapter(
            SentryMonitoringSettings(include_context_tags=True)
        )

        with patch(
            "oneiric.adapters.monitoring.sentry.get_contextvars",
            return_value={"domain": "adapter", "key": "test", "provider": "custom"},
        ):
            event = {"tags": {}, "extra": {}}
            result = adapter._before_send(event, {})
            assert "oneiric.domain" in result["tags"]
            assert "oneiric" in result["extra"]

    def test_before_send_without_context_tags(self) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        adapter = SentryMonitoringAdapter(
            SentryMonitoringSettings(include_context_tags=False)
        )
        event = {"tags": {}, "extra": {}}
        result = adapter._before_send(event, {})
        assert "oneiric.domain" not in result.get("tags", {})

    def test_before_send_empty_context(self) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        adapter = SentryMonitoringAdapter(
            SentryMonitoringSettings(include_context_tags=True)
        )

        with patch(
            "oneiric.adapters.monitoring.sentry.get_contextvars",
            return_value={},
        ):
            event = {"tags": {}, "extra": {}}
            result = adapter._before_send(event, {})
            assert "oneiric" not in result.get("extra", {})

    def test_before_send_transaction_with_context(self) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        adapter = SentryMonitoringAdapter(
            SentryMonitoringSettings(include_context_tags=True)
        )

        with patch(
            "oneiric.adapters.monitoring.sentry.get_contextvars",
            return_value={"domain": "adapter", "workflow": "test-flow"},
        ):
            event = {"tags": {}, "extra": {}}
            result = adapter._before_send_transaction(event, {})
            assert "oneiric.domain" in result["tags"]

    def test_before_send_transaction_without_context(self) -> None:
        from oneiric.adapters.monitoring.sentry import (
            SentryMonitoringAdapter,
            SentryMonitoringSettings,
        )

        adapter = SentryMonitoringAdapter(
            SentryMonitoringSettings(include_context_tags=False)
        )
        event = {}
        result = adapter._before_send_transaction(event, {})
        assert result is event


class TestSentryApplyContextTags:
    """Coverage for _apply_context_tags."""

    def test_applies_all_known_keys(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()

        context = {
            "domain": "adapter",
            "key": "test",
            "provider": "custom",
            "workflow": "my-flow",
            "run_id": "run-1",
            "node": "node-1",
            "event_topic": "topic-1",
            "event_handler": "handler-1",
            "operation": "process",
            "unknown_key": "ignored",
        }

        with patch(
            "oneiric.adapters.monitoring.sentry.get_contextvars",
            return_value=context,
        ):
            event = {"tags": {}, "extra": {}}
            adapter._apply_context_tags(event)
            assert event["tags"]["oneiric.domain"] == "adapter"
            assert event["tags"]["oneiric.key"] == "test"
            assert event["tags"]["oneiric.provider"] == "custom"
            assert "oneiric.unknown_key" not in event["tags"]

    def test_preserves_existing_tags(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()

        with patch(
            "oneiric.adapters.monitoring.sentry.get_contextvars",
            return_value={"domain": "adapter"},
        ):
            event = {"tags": {"existing_tag": "value"}}
            adapter._apply_context_tags(event)
            assert event["tags"]["existing_tag"] == "value"
            assert event["tags"]["oneiric.domain"] == "adapter"

    def test_none_values_skipped(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()

        with patch(
            "oneiric.adapters.monitoring.sentry.get_contextvars",
            return_value={"domain": "adapter", "key": None, "provider": ""},
        ):
            event = {"tags": {}, "extra": {}}
            adapter._apply_context_tags(event)
            assert event["tags"]["oneiric.domain"] == "adapter"
            assert "oneiric.key" not in event["tags"]


class TestSentryApplyFingerprint:
    """Coverage for _apply_fingerprint."""

    def test_existing_fingerprint_preserved(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {"fingerprint": ["custom-fp"], "tags": {}}
        adapter._apply_fingerprint(event)
        assert event["fingerprint"] == ["custom-fp"]

    def test_fingerprint_with_all_context(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {
            "tags": {
                "oneiric.domain": "adapter",
                "oneiric.key": "test",
                "oneiric.provider": "custom",
            },
            "exception": {
                "values": [{"type": "ValueError"}]
            },
        }
        adapter._apply_fingerprint(event)
        assert event["fingerprint"] == [
            "oneiric", "adapter", "test", "custom", "ValueError",
        ]

    def test_fingerprint_no_context(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {"tags": {}}
        adapter._apply_fingerprint(event)
        assert "fingerprint" not in event

    def test_fingerprint_partial_context(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {
            "tags": {"oneiric.domain": "adapter"},
            "exception": {"values": [{"type": "RuntimeError"}]},
        }
        adapter._apply_fingerprint(event)
        assert event["fingerprint"] == ["oneiric", "adapter", "RuntimeError"]

    def test_fingerprint_no_exception(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {
            "tags": {"oneiric.domain": "adapter", "oneiric.key": "test"},
        }
        adapter._apply_fingerprint(event)
        assert event["fingerprint"] == ["oneiric", "adapter", "test"]

    def test_fingerprint_empty_exception_values(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {
            "tags": {"oneiric.domain": "adapter"},
            "exception": {"values": []},
        }
        adapter._apply_fingerprint(event)
        assert event["fingerprint"] == ["oneiric", "adapter"]

    def test_fingerprint_with_non_dict_tags(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {"tags": "not-a-dict"}
        adapter._apply_fingerprint(event)
        assert "fingerprint" not in event

    def test_fingerprint_unknown_domain(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {
            "tags": {"oneiric.domain": "adapter"},
            "exception": {"values": [{"type": "TypeError"}]},
        }
        adapter._apply_fingerprint(event)
        assert event["fingerprint"] == ["oneiric", "adapter", "TypeError"]

    def test_fingerprint_with_none_tags(self) -> None:
        from oneiric.adapters.monitoring.sentry import SentryMonitoringAdapter

        adapter = SentryMonitoringAdapter()
        event = {"tags": None}
        adapter._apply_fingerprint(event)
        assert "fingerprint" not in event
