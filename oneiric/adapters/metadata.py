"""Adapter metadata + discovery helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from oneiric.core.logging import get_logger
from oneiric.core.metadata import (
    build_metadata,
    register_metadata,
    settings_model_path,
)
from oneiric.core.resolution import Candidate, CandidateSource, Resolver

logger = get_logger("adapter.metadata")

FactoryType = Callable[..., Any] | str


class AdapterMetadata(BaseModel):
    """Declarative metadata that can be turned into resolver candidates."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    category: str
    provider: str
    factory: FactoryType
    version: str | None = None
    description: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    stack_level: int | None = None
    priority: int | None = None
    source: CandidateSource = CandidateSource.LOCAL_PKG
    health: Callable[[], bool] | None = None
    owner: str | None = None
    requires_secrets: bool = False
    settings_model: str | type[BaseModel] | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    def to_candidate(self) -> Candidate:
        metadata = build_metadata(
            {
                "version": self.version,
                "description": self.description,
                "capabilities": self.capabilities,
                "owner": self.owner,
                "requires_secrets": self.requires_secrets,
                "settings_model": settings_model_path(self.settings_model),
            },
            self.extras,
        )
        return Candidate(
            domain="adapter",
            key=self.category,
            provider=self.provider,
            priority=self.priority,
            stack_level=self.stack_level,
            factory=self.factory,
            metadata=metadata,
            source=self.source,
            health=self.health,
        )


def register_adapter_metadata(
    resolver: Resolver,
    package_name: str,
    package_path: str,
    adapters: Sequence[AdapterMetadata],
    priority: int | None = None,
) -> None:
    """Helper that registers metadata-driven adapters via register_pkg inference."""

    register_metadata(
        resolver,
        package_name,
        package_path,
        adapters,
        priority=priority,
        logger=logger,
        log_key="adapter-metadata-registered",
    )
