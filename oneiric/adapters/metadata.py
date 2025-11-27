"""Adapter metadata + discovery helpers."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from oneiric.core.logging import get_logger
from oneiric.core.resolution import Candidate, CandidateSource, Resolver

FactoryType = Callable[..., Any] | str

logger = get_logger("adapter.metadata")


class AdapterMetadata(BaseModel):
    """Declarative metadata that can be turned into resolver candidates."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    category: str
    provider: str
    factory: FactoryType
    version: Optional[str] = None
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    stack_level: Optional[int] = None
    priority: Optional[int] = None
    source: CandidateSource = CandidateSource.LOCAL_PKG
    health: Optional[Callable[[], bool]] = None
    owner: Optional[str] = None
    requires_secrets: bool = False
    settings_model: str | type[BaseModel] | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    def to_candidate(self) -> Candidate:
        settings_model_path: Optional[str]
        if isinstance(self.settings_model, str):
            settings_model_path = self.settings_model
        elif self.settings_model:
            settings_model_path = f"{self.settings_model.__module__}.{self.settings_model.__name__}"
        else:
            settings_model_path = None
        metadata = {
            "version": self.version,
            "description": self.description,
            "capabilities": self.capabilities,
            "owner": self.owner,
            "requires_secrets": self.requires_secrets,
            "settings_model": settings_model_path,
            **self.extras,
        }
        metadata = {key: value for key, value in metadata.items() if value not in (None, [], {})}
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
    priority: Optional[int] = None,
) -> None:
    """Helper that registers metadata-driven adapters via register_pkg inference."""

    candidates = [metadata.to_candidate() for metadata in adapters]
    resolver.register_from_pkg(package_name, package_path, candidates, priority=priority)
    logger.info(
        "adapter-metadata-registered",
        package=package_name,
        count=len(candidates),
    )
