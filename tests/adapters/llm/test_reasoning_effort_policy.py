"""Tests for the per-model thinking-depth policy.

The policy is a per-provider map keyed by the *resolved* model id. Its
vocabulary is ``{adaptive, low, medium, high, xhigh, max}``; ``adaptive``
means "send no effort field". There is deliberately no "off" member:
thinking is never disabled.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from oneiric.adapters.llm.config import ProviderConfig
from oneiric.adapters.llm.provider import OpenAICompatibleProvider

TASK: dict[str, Any] = {
    "model": "MiniMax-M3.1-Flash",
    "messages": [{"role": "user", "content": "hi"}],
}


def _mock_openai() -> tuple[MagicMock, MagicMock]:
    module = MagicMock()
    client = MagicMock()
    response = MagicMock()
    response.choices[0].message.content = "ok"
    response.usage = None
    client.chat.completions.create = AsyncMock(return_value=response)
    module.AsyncOpenAI = MagicMock(return_value=client)
    return module, client


def _make_provider(
    config: ProviderConfig,
) -> tuple[OpenAICompatibleProvider, MagicMock]:
    module, client = _mock_openai()
    with patch.dict(sys.modules, {"openai": module}):
        provider = OpenAICompatibleProvider(config)
    return provider, client


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


def test_valid_effort_levels_are_accepted() -> None:
    config = ProviderConfig(
        reasoning_effort={
            "MiniMax-M3": "adaptive",
            "MiniMax-M3.1-Flash": "low",
            "a": "medium",
            "b": "high",
            "c": "xhigh",
            "d": "max",
        }
    )
    assert config.reasoning_effort["MiniMax-M3.1-Flash"] == "low"


def test_none_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ProviderConfig(reasoning_effort={"MiniMax-M3.1-Flash": "none"})
    message = str(excinfo.value)
    assert "none" in message
    assert "disabled" in message


def test_disabled_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ProviderConfig(reasoning_effort={"MiniMax-M3": "disabled"})
    message = str(excinfo.value)
    assert "disabled" in message


def test_unknown_effort_level_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ProviderConfig(reasoning_effort={"MiniMax-M3": "turbo"})
    message = str(excinfo.value)
    assert "turbo" in message
    assert "adaptive" in message


def test_an_empty_map_is_valid() -> None:
    """An empty map means "no policy for this provider", not a misconfiguration."""
    assert ProviderConfig().reasoning_effort == {}


# ---------------------------------------------------------------------------
# Provider passthrough
# ---------------------------------------------------------------------------


async def test_mapped_level_is_sent_upstream() -> None:
    provider, client = _make_provider(
        ProviderConfig(
            name="minimax",
            base_url="https://127.0.0.1/v1",
            reasoning_effort={"MiniMax-M3.1-Flash": "low"},
        )
    )

    await provider.execute(TASK)

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["reasoning_effort"] == "low"


async def test_adaptive_sends_no_effort_field() -> None:
    """``adaptive`` means "the model chooses its own depth" -- send nothing."""
    provider, client = _make_provider(
        ProviderConfig(
            name="minimax",
            base_url="https://127.0.0.1/v1",
            reasoning_effort={"MiniMax-M3.1-Flash": "adaptive"},
        )
    )

    await provider.execute(TASK)

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs


async def test_a_model_absent_from_the_map_sends_no_effort_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, client = _make_provider(
        ProviderConfig(
            name="minimax",
            base_url="https://127.0.0.1/v1",
            reasoning_effort={"MiniMax-M3": "adaptive"},
        )
    )

    with caplog.at_level("WARNING"):
        await provider.execute(TASK)

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs
    assert "MiniMax-M3.1-Flash" in caplog.text
    assert "no reasoning_effort entry" in caplog.text


async def test_an_empty_map_is_not_logged_as_a_configuration_miss(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, client = _make_provider(
        ProviderConfig(name="llama_server", base_url="https://127.0.0.1/v1")
    )

    with caplog.at_level("WARNING"):
        await provider.execute(TASK)

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs
    assert "no reasoning_effort entry" not in caplog.text


async def test_the_lookup_key_is_the_resolved_model() -> None:
    """``task_routing`` picks the model; the map says how deep it thinks."""
    provider, client = _make_provider(
        ProviderConfig(
            name="minimax",
            base_url="https://127.0.0.1/v1",
            task_routing={"quick": "MiniMax-M3.1-Flash"},
            reasoning_effort={"MiniMax-M3.1-Flash": "low", "MiniMax-M3": "adaptive"},
        )
    )

    await provider.execute({**TASK, "model": "MiniMax-M3", "task_type": "quick"})

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "MiniMax-M3.1-Flash"
    assert kwargs["reasoning_effort"] == "low"


# ---------------------------------------------------------------------------
# The echoed key
# ---------------------------------------------------------------------------


async def test_the_result_echoes_the_delivered_level() -> None:
    provider, _ = _make_provider(
        ProviderConfig(
            name="minimax",
            base_url="https://127.0.0.1/v1",
            reasoning_effort={"MiniMax-M3.1-Flash": "low"},
        )
    )

    result = await provider.execute(TASK)

    assert result["reasoning_effort"] == "low"


async def test_the_result_echoes_the_adaptive_sentinel() -> None:
    provider, _ = _make_provider(
        ProviderConfig(
            name="minimax",
            base_url="https://127.0.0.1/v1",
            reasoning_effort={"MiniMax-M3.1-Flash": "adaptive"},
        )
    )

    result = await provider.execute(TASK)

    assert result["reasoning_effort"] == "adaptive"


async def test_the_result_omits_the_key_when_no_policy_applies() -> None:
    provider, _ = _make_provider(
        ProviderConfig(name="llama_server", base_url="https://127.0.0.1/v1")
    )

    result = await provider.execute(TASK)

    assert "reasoning_effort" not in result
