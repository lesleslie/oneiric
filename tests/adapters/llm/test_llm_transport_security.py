"""Security tests for the moved LLM transport layer.

The LLM subsystem arrived in oneiric from ``mcp_common.llm``. These tests
pin the transport-layer guarantees oneiric's own adapter contract expects
of it:

* secrets never survive redaction -- including the *signature* of a
  three-segment JWT, which the original two-segment pattern let through;
* a raised error's rendered traceback carries no secret, not just its
  message;
* a per-request header cannot displace the credential headers;
* a provider's ``base_url`` cannot point the credential at a cloud
  metadata service or a private network.
"""

from __future__ import annotations

import sys
import traceback
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from oneiric.adapters.llm._security import sanitize_error
from oneiric.adapters.llm.config import ProviderConfig
from oneiric.adapters.llm.provider import OpenAICompatibleProvider

JWT = (
    "eyJhbGciOiJIUzI1NiJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ"
    ".dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
)
API_KEY = "sk-ant-api03-realkey1234567890abcdef"


def _mock_openai(client: Any | None = None) -> MagicMock:
    module = MagicMock()
    module.AsyncOpenAI = MagicMock(return_value=client or MagicMock())
    return module


def _make_provider(
    config: ProviderConfig, client: Any | None = None
) -> OpenAICompatibleProvider:
    with patch.dict(sys.modules, {"openai": _mock_openai(client)}):
        return OpenAICompatibleProvider(config)


# ---------------------------------------------------------------------------
# Redaction completeness
# ---------------------------------------------------------------------------


def test_a_three_segment_jwt_is_fully_redacted() -> None:
    """The signature is the secret part; the old pattern left it behind."""
    sanitized = sanitize_error(f"auth failed: {JWT}")
    assert JWT not in sanitized
    assert "dBjftJeZ4CVP" not in sanitized
    assert "<redacted>" in sanitized


def test_a_quoted_base64_secret_is_redacted() -> None:
    secret = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MDEyMzQ1Ng=="
    sanitized = sanitize_error(f'payload="{secret}"')
    assert secret not in sanitized


def test_an_assignment_form_credential_is_redacted() -> None:
    for label in ("api_key", "api-key", "token", "secret", "x-bf-vk"):
        sanitized = sanitize_error(f"{label}=abcdef0123456789abcdef0123456789")
        assert "abcdef0123456789abcdef0123456789" not in sanitized


def test_a_bearer_token_is_redacted() -> None:
    sanitized = sanitize_error("Authorization: Bearer abcdef0123456789abcdef")
    assert "abcdef0123456789abcdef" not in sanitized


# ---------------------------------------------------------------------------
# The raised error must not carry the secret in its chain
# ---------------------------------------------------------------------------


async def test_the_rendered_traceback_carries_no_secret() -> None:
    """``raise ... from e`` puts the raw cause in the traceback."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError(f"auth failed: {API_KEY}")
    )
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"),
        client=client,
    )

    with pytest.raises(Exception) as excinfo:
        await provider.execute({"model": "m", "messages": []})

    rendered = "".join(
        traceback.format_exception(
            type(excinfo.value), excinfo.value, excinfo.value.__traceback__
        )
    )
    assert API_KEY not in rendered
    assert "sk-ant-api03-realkey" not in rendered


async def test_the_chained_cause_is_sanitized() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError(f"auth failed: {API_KEY}")
    )
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"),
        client=client,
    )

    with pytest.raises(Exception) as excinfo:
        await provider.execute({"model": "m", "messages": []})

    cause = excinfo.value.__cause__
    assert cause is not None
    assert API_KEY not in str(cause)


async def test_a_cause_that_renders_itself_is_not_chained() -> None:
    """An exception with a custom ``__str__`` cannot be sanitized in place."""

    class _SelfRendering(RuntimeError):
        def __str__(self) -> str:
            return self.args[0]

    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=_SelfRendering(f"auth failed: {API_KEY}")
    )
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"),
        client=client,
    )

    with pytest.raises(Exception) as excinfo:
        await provider.execute({"model": "m", "messages": []})

    rendered = "".join(
        traceback.format_exception(
            type(excinfo.value), excinfo.value, excinfo.value.__traceback__
        )
    )
    assert API_KEY not in rendered


# ---------------------------------------------------------------------------
# Per-request headers cannot displace the credential headers
# ---------------------------------------------------------------------------


async def test_a_per_request_authorization_header_is_dropped() -> None:
    """The SDK merges custom headers *last*, so they win over auth."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_response())
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"),
        client=client,
    )

    await provider.execute(
        {
            "model": "m",
            "messages": [],
            "extra_headers": {"Authorization": "Bearer attacker-token"},
        }
    )

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "Authorization" not in (kwargs.get("extra_headers") or {})


async def test_a_per_request_gateway_key_header_is_dropped() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_response())
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"),
        client=client,
    )

    await provider.execute(
        {
            "model": "m",
            "messages": [],
            "extra_headers": {"x-bf-vk": "sk-bf-attacker"},
        }
    )

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "x-bf-vk" not in (kwargs.get("extra_headers") or {})


async def test_the_cache_headers_still_pass_through() -> None:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_response())
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"),
        client=client,
    )

    await provider.execute(
        {
            "model": "m",
            "messages": [],
            "extra_headers": {"x-bf-cache-key": "tenant-7"},
        }
    )

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["extra_headers"]["x-bf-cache-key"] == "tenant-7"


def test_a_credential_header_in_default_headers_is_not_handed_to_the_sdk() -> None:
    """``default_headers`` also win over the SDK's auth header."""
    module = _mock_openai()
    with patch.dict(sys.modules, {"openai": module}):
        OpenAICompatibleProvider(
            ProviderConfig(
                name="minimax",
                base_url="https://127.0.0.1/v1",
                api_key="sk-real-key",
                default_headers={"Authorization": "Bearer displaced"},
            )
        )

    _, kwargs = module.AsyncOpenAI.call_args
    assert "Authorization" not in kwargs["default_headers"]


# ---------------------------------------------------------------------------
# base_url validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        "http://169.254.169.254/v1",  # AWS/Azure IMDS
        "http://metadata.google.internal/v1",
        "http://100.100.100.200/v1",  # Alibaba Cloud metadata
        "http://10.0.0.5/v1",  # RFC1918
        "http://192.168.1.5/v1",  # RFC1918
        "http://172.16.0.5/v1",  # RFC1918
        "http://api.minimax.io/v1",  # plain http to a non-loopback host
    ],
)
def test_a_dangerous_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(name="minimax", base_url=base_url)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1/v1",
        "http://127.0.0.1:8471/v1",
        "http://localhost:8081",
    ],
)
def test_a_supported_base_url_is_accepted(base_url: str) -> None:
    config = ProviderConfig(name="minimax", base_url=base_url)
    assert config.base_url == base_url


def test_an_empty_base_url_is_allowed() -> None:
    """An unconfigured provider has no URL to judge."""
    assert ProviderConfig().base_url == ""


# ---------------------------------------------------------------------------
# The base_url must not leak userinfo into the log
# ---------------------------------------------------------------------------


def test_the_logged_base_url_carries_no_userinfo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with (
        patch.dict(sys.modules, {"openai": _mock_openai()}),
        caplog.at_level(logging.INFO),
    ):
        OpenAICompatibleProvider(
            ProviderConfig(
                name="minimax",
                base_url="https://user:hunter2@api.minimax.io/v1",
            )
        )

    assert "hunter2" not in caplog.text


# ---------------------------------------------------------------------------
# The settings model must not print credentials
# ---------------------------------------------------------------------------


def test_default_headers_are_not_printed_in_the_model_repr() -> None:
    config = ProviderConfig(
        name="minimax",
        base_url="https://127.0.0.1/v1",
        default_headers={"x-bf-vk": "sk-bf-supersecretvalue"},
    )
    assert "sk-bf-supersecretvalue" not in repr(config)


def _response() -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = "ok"
    response.usage = None
    return response
