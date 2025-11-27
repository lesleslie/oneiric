"""Action metadata + registry helpers."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from oneiric.core.logging import get_logger
from oneiric.core.resolution import Candidate, CandidateSource, Resolver

FactoryType = Callable[..., Any] | str

logger = get_logger("action.metadata")


class ActionMetadata(BaseModel):
    """Declarative metadata describing a resolver-managed action kit."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: str = Field(description="Action kit identifier (e.g., compression.encode)")
    provider: str = Field(description="Provider/implementation identifier.")
    factory: FactoryType
    description: Optional[str] = None
    domains: List[str] = Field(default_factory=list, description="Resolver domains this action targets.")
    capabilities: List[str] = Field(default_factory=list)
    stack_level: Optional[int] = None
    priority: Optional[int] = None
    source: CandidateSource = CandidateSource.LOCAL_PKG
    owner: Optional[str] = None
    requires_secrets: bool = False
    side_effect_free: bool = False
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
            "description": self.description,
            "domains": self.domains,
            "capabilities": self.capabilities,
            "owner": self.owner,
            "requires_secrets": self.requires_secrets,
            "side_effect_free": self.side_effect_free,
            "settings_model": settings_model_path,
            **self.extras,
        }
        metadata = {key: value for key, value in metadata.items() if value not in (None, [], {})}
        return Candidate(
            domain="action",
            key=self.key,
            provider=self.provider,
            priority=self.priority,
            stack_level=self.stack_level,
            factory=self.factory,
            metadata=metadata,
            source=self.source,
        )


def register_action_metadata(
    resolver: Resolver,
    package_name: str,
    package_path: str,
    actions: Sequence[ActionMetadata],
    priority: Optional[int] = None,
) -> None:
    """Register metadata-defined action kits with the resolver."""

    candidates = [metadata.to_candidate() for metadata in actions]
    resolver.register_from_pkg(package_name, package_path, candidates, priority=priority)
    logger.info(
        "action-metadata-registered",
        package=package_name,
        count=len(candidates),
    )
