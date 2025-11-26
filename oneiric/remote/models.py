"""Remote manifest data models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RemoteManifestEntry(BaseModel):
    domain: str
    key: str
    provider: str
    factory: str
    uri: Optional[str] = None
    sha256: Optional[str] = None
    stack_level: Optional[int] = None
    priority: Optional[int] = None
    version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RemoteManifest(BaseModel):
    source: str = "remote"
    entries: List[RemoteManifestEntry] = Field(default_factory=list)
    signature: Optional[str] = None  # Base64-encoded signature
    signature_algorithm: str = "ed25519"  # Only ed25519 supported initially
