from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, Field

from oneiric.core.logging import get_logger


class NoSQLDocument(BaseModel):

    id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class NoSQLQuery(BaseModel):

    filters: dict[str, Any] = Field(default_factory=dict)
    projection: list[str] | None = None
    limit: int | None = None
    sort: list[tuple[str, int]] | None = None


class NoSQLBaseSettings(BaseModel):

    connect_timeout: float = 30.0
    operation_timeout: float = 30.0
    health_timeout: float = 5.0


class NoSQLAdapterBase(ABC):

    def __init__(self, settings: NoSQLBaseSettings) -> None:
        self._settings = settings
        self._logger = get_logger("adapter.nosql.base")

    @property
    def settings(self) -> NoSQLBaseSettings:
        return self._settings

    @abstractmethod
    async def init(self) -> None:
        pass

    @abstractmethod
    async def health(self) -> bool:
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        pass

    @asynccontextmanager
    async def span(self, event: str, **extra: Any) -> AsyncIterator[None]:
        self._logger.debug("%s-start", event, **extra)
        try:
            yield
            self._logger.debug("%s-complete", event, **extra)
        except Exception:
            self._logger.error("%s-error", event, **extra)
            raise
