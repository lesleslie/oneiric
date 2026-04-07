"""macOS Keychain (keyring) secrets adapter for oneiric.

Resolves secrets from the system keychain via the ``keyring`` library.
Gracefully degrades on platforms where keyring is unavailable or has
no backend — ``get_secret`` simply returns ``None`` and the resolution
chain falls through to the next adapter.

Key naming convention:
    service_name = ``KeyringSecretSettings.service_name`` (default: ``"oneiric"``)
    secret_id    = ``KeyringSecretSettings.key_prefix + raw_id``
                   (default prefix: ``""``, so raw IDs are used as-is)

Usage from an MCP server:
    Store once:  ``keyring set oneiric opera-cloud-mcp-client-id``
    Resolve:     ``await adapter.get_secret("opera-cloud-mcp-client-id")``
"""

from __future__ import annotations

import importlib.util

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

KEYRING_AVAILABLE = importlib.util.find_spec("keyring") is not None


class KeyringSecretSettings(BaseModel):
    """Configuration for the keyring secrets adapter."""

    service_name: str = Field(
        default="oneiric",
        description="Service name passed to keyring.get_password / set_password.",
    )
    key_prefix: str = Field(
        default="",
        description="Optional prefix prepended to every secret_id before keyring lookup.",
    )


class KeyringSecretAdapter:
    """Retrieve secrets from the system keychain (macOS Keychain, etc.)."""

    metadata = AdapterMetadata(
        category="secrets",
        provider="keyring",
        factory="oneiric.adapters.secrets.keyring:KeyringSecretAdapter",
        capabilities=["read"],
        stack_level=15,
        priority=200,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        settings_model=KeyringSecretSettings,
    )

    def __init__(self, settings: KeyringSecretSettings | None = None) -> None:
        self._settings = settings or KeyringSecretSettings()
        self._logger = get_logger("adapter.secrets.keyring").bind(
            domain="adapter",
            key="secrets",
            provider="keyring",
        )
        self._available = KEYRING_AVAILABLE

    async def init(self) -> None:
        if self._available:
            self._logger.info(
                "adapter-init",
                adapter="keyring-secrets",
                service=self._settings.service_name,
            )
        else:
            self._logger.info(
                "adapter-init-skip",
                adapter="keyring-secrets",
                reason="keyring package not available",
            )

    async def health(self) -> bool:
        return self._available

    async def cleanup(self) -> None:
        self._logger.info("adapter-cleanup-complete", adapter="keyring-secrets")

    async def get_secret(self, secret_id: str) -> str | None:
        if not self._available:
            return None

        key = f"{self._settings.key_prefix}{secret_id}"
        try:
            import keyring
            from keyring.errors import KeyringError

            value = keyring.get_password(self._settings.service_name, key)
        except KeyringError:
            self._logger.warning(
                "keyring-access-error",
                service=self._settings.service_name,
                key=key,
                exc_info=True,
            )
            return None
        except Exception:
            self._logger.debug(
                "keyring-lookup-failed",
                service=self._settings.service_name,
                key=key,
                exc_info=True,
            )
            return None

        if value is not None:
            self._logger.debug(
                "secret-resolved-from-keyring",
                key=key,
            )
        return value
