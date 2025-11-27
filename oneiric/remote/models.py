"""Remote manifest data models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    uri: Optional[str] = None
    sha256: Optional[str] = None

    # Resolution fields (optional)
    stack_level: Optional[int] = None
    priority: Optional[int] = None
    version: Optional[str] = None

    # Generic metadata (backward compatible)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Adapter-specific fields (optional - Stage 4 enhancement)
    capabilities: List[str] = Field(default_factory=list)
    owner: Optional[str] = None
    requires_secrets: bool = False
    settings_model: Optional[str] = None  # Import path to Pydantic model

    # Action-specific fields (optional - Stage 4 enhancement)
    side_effect_free: bool = False
    timeout_seconds: Optional[float] = None
    retry_policy: Optional[Dict[str, Any]] = None

    # Dependency constraints (optional - Stage 4 enhancement)
    requires: List[str] = Field(default_factory=list)  # ["package>=1.0.0"]
    conflicts_with: List[str] = Field(default_factory=list)

    # Platform constraints (optional - Stage 4 enhancement)
    python_version: Optional[str] = None  # ">=3.14"
    os_platform: Optional[List[str]] = None  # ["linux", "darwin", "windows"]

    # Documentation fields (optional - Stage 4 enhancement)
    license: Optional[str] = None
    documentation_url: Optional[str] = None


class RemoteManifest(BaseModel):
    source: str = "remote"
    entries: List[RemoteManifestEntry] = Field(default_factory=list)
    signature: Optional[str] = None  # Base64-encoded signature
    signature_algorithm: str = "ed25519"  # Only ed25519 supported initially
