from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from oneiric.adapters.llm.llm_interface import (
    LLMBase,
    LLMBaseSettings,
    LLMCapability,
    LLMMessage,
    LLMModelInfo,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
    MessageRole,
)

# ---------------------------------------------------------------------------
# Minimal concrete stub for testing LLMBase
# ---------------------------------------------------------------------------


class _StubLLM(LLMBase):
    def __init__(self, settings: LLMBaseSettings | None = None) -> None:
        super().__init__(settings or LLMBaseSettings())

    async def init(self) -> None:
        self._client = object()

    async def health(self) -> bool:
        return True

    async def cleanup(self) -> None:
        self._client = None

    async def _ensure_client(self) -> Any:
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
        return LLMResponse(content="ok", model=model, provider="stub")

    async def _chat_stream(
        self,
        messages: list[LLMMessage | dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk]:
        yield LLMStreamChunk(content="chunk", model=model)

    async def _get_model_info(self, model: str) -> LLMModelInfo:
        return LLMModelInfo(
            name=model,
            provider=LLMProvider.LOCAL,
            capabilities=[LLMCapability.TEXT_GENERATION],
            context_length=4096,
            max_output_tokens=1024,
        )

    async def _list_models(self) -> list[LLMModelInfo]:
        return [await self._get_model_info("stub-model")]


# ---------------------------------------------------------------------------
# Tests — LLMBase concrete methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llmbase_settings_and_client_properties() -> None:
    """settings and client properties return internal state (lines 142, 146)."""
    llm = _StubLLM()
    assert llm.settings is llm._settings
    assert llm.client is None  # before init
    await llm.init()
    assert llm.client is not None


@pytest.mark.asyncio
async def test_chat_delegates_to_chat_impl() -> None:
    """chat() resolves defaults and delegates to _chat (line 166)."""
    llm = _StubLLM()
    messages = [LLMMessage(role=MessageRole.USER, content="hello")]
    result = await llm.chat(messages)
    assert result.content == "ok"
    assert result.model == llm._settings.model


@pytest.mark.asyncio
async def test_chat_stream_yields_chunks() -> None:
    """chat_stream() yields LLMStreamChunk objects (lines 185-194)."""
    llm = _StubLLM()
    messages = [LLMMessage(role=MessageRole.USER, content="hello")]
    chunks = [chunk async for chunk in llm.chat_stream(messages)]
    assert len(chunks) == 1
    assert chunks[0].content == "chunk"


@pytest.mark.asyncio
async def test_complete_delegates_to_complete_impl() -> None:
    """complete() resolves defaults and delegates to _complete (line 204)."""
    llm = _StubLLM()
    result = await llm.complete("tell me something")
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_complete_stream_yields_chunks() -> None:
    """complete_stream() wraps _complete_stream and yields chunks (lines 222-231)."""
    llm = _StubLLM()
    chunks = [chunk async for chunk in llm.complete_stream("hello")]
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_function_call_raises_not_implemented() -> None:
    """function_call() raises NotImplementedError via _function_call (lines 240, 351)."""
    llm = _StubLLM()
    with pytest.raises(NotImplementedError):
        await llm.function_call([], [{"name": "f"}])


@pytest.mark.asyncio
async def test_tool_use_raises_not_implemented() -> None:
    """tool_use() raises NotImplementedError via _tool_use (lines 254, 361)."""
    llm = _StubLLM()
    with pytest.raises(NotImplementedError):
        await llm.tool_use([], [{"type": "function"}])


@pytest.mark.asyncio
async def test_get_model_info_delegates() -> None:
    """get_model_info() delegates to _get_model_info (line 265)."""
    llm = _StubLLM()
    info = await llm.get_model_info()
    assert info.provider == LLMProvider.LOCAL


@pytest.mark.asyncio
async def test_list_models() -> None:
    """list_models() delegates to _list_models (line 268)."""
    llm = _StubLLM()
    models = await llm.list_models()
    assert len(models) == 1


@pytest.mark.asyncio
async def test_count_tokens_default_implementation() -> None:
    """count_tokens() uses default 4-chars-per-token heuristic (lines 275, 371)."""
    llm = _StubLLM()
    count = await llm.count_tokens("hello world")
    assert count == len("hello world") // 4


@pytest.mark.asyncio
async def test_complete_via_complete_impl(monkeypatch: pytest.MonkeyPatch) -> None:
    """_complete builds a USER message and calls _chat (lines 312-315)."""
    called_with: list[Any] = []

    async def spy_chat(
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        **kwargs: Any,
    ) -> LLMResponse:
        called_with.extend(messages)
        return LLMResponse(content="x", model=model, provider="stub")

    llm = _StubLLM()
    monkeypatch.setattr(llm, "_chat", spy_chat)
    await llm._complete("hi", "model", 0.5, 100)
    assert len(called_with) == 1
    assert isinstance(called_with[0], LLMMessage)
    assert called_with[0].role == MessageRole.USER


@pytest.mark.asyncio
async def test_complete_stream_via_complete_stream_impl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_complete_stream wraps _chat_stream (lines 332-342)."""
    llm = _StubLLM()
    chunks = [c async for c in llm._complete_stream("hi", "model", 0.5, 100)]
    assert len(chunks) == 1
    assert chunks[0].content == "chunk"


def test_normalize_messages_with_mixed_types() -> None:
    """_normalize_messages handles LLMMessage and raw dict (lines 377, 383-393)."""
    llm = _StubLLM()
    messages: list[LLMMessage | dict[str, Any]] = [
        LLMMessage(role=MessageRole.USER, content="hello"),
        {"role": "system", "content": "sys"},
    ]
    normalized = llm._normalize_messages(messages)
    assert normalized[0]["role"] == "user"
    assert normalized[1]["role"] == "system"


def test_normalize_single_message_with_optional_fields() -> None:
    """_normalize_single_message includes name, function_call, tool_calls when set (lines 387-392)."""
    llm = _StubLLM()
    msg = LLMMessage(
        role=MessageRole.ASSISTANT,
        content="ok",
        name="bot",
        function_call={"name": "f", "arguments": "{}"},
        tool_calls=[{"id": "t1", "type": "function", "function": {}}],
    )
    result = llm._normalize_single_message(msg)
    assert result["name"] == "bot"
    assert result["function_call"] == {"name": "f", "arguments": "{}"}
    assert len(result["tool_calls"]) == 1


def test_normalize_single_message_with_string_role() -> None:
    """_normalize_single_message handles string role (not MessageRole enum)."""
    llm = _StubLLM()
    msg = LLMMessage(role="custom", content="hi")
    result = llm._normalize_single_message(msg)
    assert result["role"] == "custom"


def test_calculate_cost_returns_none_when_no_pricing() -> None:
    """_calculate_cost returns None when model has no pricing (lines 401-405)."""
    llm = _StubLLM()
    info = LLMModelInfo(
        name="m",
        provider=LLMProvider.LOCAL,
        capabilities=[],
        context_length=4096,
        max_output_tokens=1024,
        cost_per_1k_input_tokens=None,
        cost_per_1k_output_tokens=None,
    )
    assert llm._calculate_cost(100, 50, info) is None


def test_calculate_cost_with_pricing() -> None:
    """_calculate_cost computes cost when pricing is available (lines 407-410)."""
    llm = _StubLLM()
    info = LLMModelInfo(
        name="m",
        provider=LLMProvider.OPENAI,
        capabilities=[],
        context_length=4096,
        max_output_tokens=1024,
        cost_per_1k_input_tokens=0.01,
        cost_per_1k_output_tokens=0.03,
    )
    cost = llm._calculate_cost(1000, 1000, info)
    assert cost is not None
    assert abs(cost - 0.04) < 1e-9
