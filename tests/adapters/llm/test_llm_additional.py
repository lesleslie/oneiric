"""Additional branch-focused tests for oneiric.adapters.llm."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from oneiric.adapters.llm._security import sanitize_error
from oneiric.adapters.llm.config import LLMSettings, ProviderConfig


class TestLLMSecuritySanitizer:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            (
                "failed with sk-abcdefghijklmnopqrstuvwxyz1234",
                "failed with <redacted>",
            ),
            (
                "token=eyJhbGciOiJIUzI1NiJ9.abc123def456ghi789",
                "token=<redacted>",
            ),
            (
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
                "Authorization: <redacted>",
            ),
            (
                'payload="1234567890abcdef1234567890abcdef"',
                "payload=<redacted>",
            ),
        ],
    )
    def test_sanitize_error_redacts_secret_patterns(
        self, message: str, expected: str
    ) -> None:
        assert sanitize_error(message) == expected


class TestProviderConfigLegacyTimeout:
    def test_timeout_seconds_syncs_from_legacy_timeout(self) -> None:
        config = ProviderConfig(timeout=45)
        assert config.timeout_seconds == 45


class TestLLMSettingsFallbackChainWarnings:
    def test_missing_fallback_chain_entry_is_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = LLMSettings(
            providers={
                "available": {
                    "name": "available",
                    "enabled": True,
                    "base_url": "",
                    "api_key": "",
                    "require_auth": False,
                },
            },
            fallback_chain=["missing", "available"],
        )

        enabled = settings.get_enabled_providers()

        assert [provider.name for provider in enabled] == ["available"]
        assert "missing in fallback_chain not found in config" in caplog.text


def _mock_openai_module() -> MagicMock:
    module = MagicMock()
    module.AsyncOpenAI = MagicMock(return_value=MagicMock())
    return module


class TestOpenAICompatibleProviderNoAuth:
    def test_constructor_uses_no_auth_headers_when_auth_disabled(self) -> None:
        from oneiric.adapters.llm.provider import OpenAICompatibleProvider

        config = ProviderConfig(
            name="llama_server",
            base_url="http://localhost:8081/v1",
            require_auth=False,
        )
        mock_openai = _mock_openai_module()

        with patch.dict(sys.modules, {"openai": mock_openai}):
            provider = OpenAICompatibleProvider(config)

        assert provider.name == "llama_server"
        mock_openai.AsyncOpenAI.assert_called_once_with(
            api_key="no-auth",
            base_url="http://localhost:8081/v1",
            default_headers={"Authorization": ""},
            max_retries=0,
            timeout=30,
        )
