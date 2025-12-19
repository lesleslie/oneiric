"""Remote manifest data models."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CapabilitySecurityProfile(BaseModel):
    """Security posture metadata for a capability entry."""

    classification: str | None = None
    auth_required: bool = True
    scopes: list[str] = Field(default_factory=list)
    encryption: str | None = None
    signature_required: bool = False
    audience: list[str] = Field(default_factory=list)
    notes: str | None = None


class CapabilityDescriptor(BaseModel):
    """Capability descriptor with optional event/schema metadata."""

    name: str
    description: str | None = None
    event_types: list[str] = Field(default_factory=list)
    payload_schema: dict[str, Any] | str | None = None
    schema_format: str | None = None
    security: CapabilitySecurityProfile | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteManifestEntry(BaseModel):
    """Remote manifest entry with full adapter/action metadata support.

    All new fields are optional for backward compatibility with v1 manifests.
    """

    # Core fields (required)
    domain: str
    key: str
    provider: str
    factory: str

    # Artifact fields (optional)
    uri: str | None = None
    sha256: str | None = None

    # Resolution fields (optional)
    stack_level: int | None = None
    priority: int | None = None
    version: str | None = None

    # Generic metadata (backward compatible)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Adapter-specific fields (optional - Stage 4 enhancement)
    capabilities: list[CapabilityDescriptor] = Field(default_factory=list)
    owner: str | None = None
    requires_secrets: bool = False
    settings_model: str | None = None  # Import path to Pydantic model

    # Action-specific fields (optional - Stage 4 enhancement)
    side_effect_free: bool = False
    timeout_seconds: float | None = None
    retry_policy: dict[str, Any] | None = None

    # Dependency constraints (optional - Stage 4 enhancement)
    requires: list[str] = Field(default_factory=list)  # ["package>=1.0.0"]
    conflicts_with: list[str] = Field(default_factory=list)

    # Platform constraints (optional - Stage 4 enhancement)
    python_version: str | None = None  # ">=3.14"
    os_platform: list[str] | None = None  # ["linux", "darwin", "windows"]

    # Documentation fields (optional - Stage 4 enhancement)
    license: str | None = None
    documentation_url: str | None = None

    # Event routing helpers (Stage 5 prototype)
    event_topics: list[str] | None = None
    event_max_concurrency: int | None = None
    event_filters: list[dict[str, Any]] | None = None
    event_priority: int | None = None
    event_fanout_policy: str | None = None

    # Workflow DAG metadata (Stage 5 prototype)
    dag: dict[str, Any] | None = None

    @field_validator("capabilities", mode="before")
    @classmethod
    def _normalize_capabilities(
        cls, value: Iterable[CapabilityDescriptor | str | dict[str, Any]] | None
    ) -> list[CapabilityDescriptor]:
        """Allow legacy string lists + dict shorthand for capabilities."""

        if value is None:
            return []

        normalized: list[CapabilityDescriptor] = []
        for item in value:
            if isinstance(item, CapabilityDescriptor):
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append(CapabilityDescriptor(name=item))
            elif isinstance(item, dict):
                if "name" not in item or not item["name"]:
                    raise ValueError("capability entry missing 'name'")
                normalized.append(CapabilityDescriptor(**item))
            else:
                raise TypeError(
                    "capabilities must be CapabilityDescriptor, dict, or str"
                )
        return normalized

    @property
    def capability_names(self) -> list[str]:
        return [cap.name for cap in self.capabilities]

    def capability_payloads(self) -> list[dict[str, Any]]:
        """Structured capability descriptors (suitable for metadata export)."""

        payloads: list[dict[str, Any]] = []
        for descriptor in self.capabilities:
            payload = descriptor.model_dump(exclude_none=True)
            if not payload.get("description"):
                payload.pop("description", None)
            if not payload.get("event_types"):
                payload.pop("event_types", None)
            if not payload.get("payload_schema"):
                payload.pop("payload_schema", None)
            if not payload.get("schema_format"):
                payload.pop("schema_format", None)
            if descriptor.security:
                payload["security"] = descriptor.security.model_dump(
                    exclude_none=True, exclude_unset=True
                )
            else:
                payload.pop("security", None)
            if not payload.get("metadata"):
                payload.pop("metadata", None)
            payloads.append(payload)
        return payloads


class ManifestSignature(BaseModel):
    """Signature entry for multi-signature manifests."""

    signature: str
    algorithm: str = "ed25519"
    key_id: str | None = None


class RemoteManifest(BaseModel):
    source: str = "remote"
    entries: list[RemoteManifestEntry] = Field(default_factory=list)
    signature: str | None = None  # Base64-encoded signature
    signature_algorithm: str = "ed25519"  # Only ed25519 supported initially
    signatures: list[ManifestSignature] = Field(default_factory=list)
    signed_at: str | None = None
    expires_at: str | None = None
