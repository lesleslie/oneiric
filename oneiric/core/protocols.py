"""Protocol interfaces shared across core configuration helpers."""

from __future__ import annotations

from typing import Protocol


class SecretsProviderProtocol(Protocol):
    async def get_secret(self, secret_id: str) -> str | None: ...


class SecretsCacheProtocol(Protocol):
    async def invalidate_cache(self) -> None: ...
    async def clear_cache(self) -> None: ...
    async def refresh(self) -> None: ...
