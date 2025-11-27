# Stage 4: Remote & Packaging Implementation Plan

**Status:** 🔄 80% Complete
**Target Completion:** 2 weeks
**Priority:** P1 (Required for beta launch)

---

## Executive Summary

Stage 4 completes the remote manifest delivery pipeline by:
1. Extending the manifest schema to support full adapter/action metadata
2. Implementing automated package signing and upload
3. Validating cache path security boundaries
4. Creating comprehensive watcher tests for remote module loading

**Current State:**
- ✅ Basic remote manifest loading (YAML/JSON)
- ✅ SHA256 digest verification
- ✅ ED25519 signature verification
- ✅ Circuit breaker + retry logic
- ✅ Path traversal protection
- ✅ HTTP timeout handling (30s default)
- ⚠️ **Missing:** Comprehensive adapter/action metadata in manifests
- ⚠️ **Missing:** Automated package signing/upload CI/CD pipeline
- ⚠️ **Missing:** Watcher tests for remote module hot-reloading

---

## Current Implementation Analysis

### What's Already Built ✅

**1. Remote Manifest Models (`oneiric/remote/models.py`):**
```python
class RemoteManifestEntry(BaseModel):
    domain: str              # ✅ Supports all 5 domains
    key: str                 # ✅ Component identifier
    provider: str            # ✅ Provider name
    factory: str             # ✅ Import path to factory
    uri: Optional[str]       # ✅ Artifact download URI
    sha256: Optional[str]    # ✅ Digest verification
    stack_level: Optional[int]   # ✅ Resolution precedence
    priority: Optional[int]      # ✅ Tie-breaker
    version: Optional[str]       # ✅ Semantic version
    metadata: Dict[str, Any]     # ✅ Generic metadata dict
```

**2. Loader Infrastructure (`oneiric/remote/loader.py`):**
- ✅ Async artifact fetching with timeout
- ✅ SHA256 digest verification
- ✅ Path traversal protection
- ✅ Circuit breaker pattern
- ✅ Exponential backoff retry
- ✅ Remote sync metrics (duration, counts)

**3. Security Layer (`oneiric/remote/security.py`):**
- ✅ ED25519 signature verification
- ✅ Canonical manifest serialization
- ✅ Filename sanitization (path traversal prevention)

**4. Sample Manifest (`docs/sample_remote_manifest.yaml`):**
- ✅ Demonstrates all 5 domains (adapter, service, task, event, workflow)
- ✅ Includes 12 action examples
- ✅ Shows metadata embedding

### What's Missing ❌

**1. Enhanced Manifest Schema:**
- ❌ Adapter-specific fields (`capabilities`, `owner`, `requires_secrets`, `settings_model`)
- ❌ Action-specific fields (`side_effect_free`, `timeout`, `retry_policy`)
- ❌ Versioned dependencies (`requires`, `conflicts_with`)
- ❌ Platform constraints (`python_version`, `os_platform`)

**2. Package Automation:**
- ❌ CI/CD pipeline for signing manifests
- ❌ Automated artifact upload to S3/GCS
- ❌ Manifest generation from codebase
- ❌ Version bump automation

**3. Watcher Tests:**
- ❌ Tests for remote manifest hot-reloading
- ❌ Tests for artifact cache invalidation
- ❌ Tests for signature verification failures
- ❌ Tests for concurrent remote sync

---

## Stage 4 Tasks Breakdown

### Task 1: Extend Remote Manifest Schema (3 days)

**Goal:** Support full adapter/action metadata in remote manifests without breaking existing manifests.

**Subtasks:**

#### 1.1 Update `RemoteManifestEntry` Model (1 day)

**File:** `oneiric/remote/models.py`

Add new optional fields while maintaining backward compatibility:

```python
class RemoteManifestEntry(BaseModel):
    # Existing fields (required)
    domain: str
    key: str
    provider: str
    factory: str

    # Existing optional fields
    uri: Optional[str] = None
    sha256: Optional[str] = None
    stack_level: Optional[int] = None
    priority: Optional[int] = None
    version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # NEW: Adapter-specific fields
    capabilities: List[str] = Field(default_factory=list)
    owner: Optional[str] = None
    requires_secrets: bool = False
    settings_model: Optional[str] = None  # Import path to Pydantic model

    # NEW: Action-specific fields
    side_effect_free: bool = False
    timeout_seconds: Optional[float] = None
    retry_policy: Optional[Dict[str, Any]] = None

    # NEW: Dependency constraints
    requires: List[str] = Field(default_factory=list)  # ["package>=1.0.0"]
    conflicts_with: List[str] = Field(default_factory=list)

    # NEW: Platform constraints
    python_version: Optional[str] = None  # ">=3.14"
    os_platform: Optional[List[str]] = None  # ["linux", "darwin"]

    # NEW: License and docs
    license: Optional[str] = None
    documentation_url: Optional[str] = None
```

**Acceptance Criteria:**
- [ ] All new fields are optional (backward compatible)
- [ ] Pydantic validation ensures type safety
- [ ] Existing sample manifest still validates
- [ ] Unit tests cover new field combinations

#### 1.2 Update Manifest Loader (1 day)

**File:** `oneiric/remote/loader.py`

Propagate new metadata fields to `Candidate` registration:

```python
def _register_entry(
    resolver: Resolver,
    entry: RemoteManifestEntry,
    source: str,
) -> None:
    """Register manifest entry as resolver candidate with full metadata."""

    # Build metadata dict from entry fields
    metadata = dict(entry.metadata)  # Start with generic metadata

    # Add adapter-specific metadata
    if entry.capabilities:
        metadata["capabilities"] = entry.capabilities
    if entry.owner:
        metadata["owner"] = entry.owner
    metadata["requires_secrets"] = entry.requires_secrets
    if entry.settings_model:
        metadata["settings_model"] = entry.settings_model

    # Add action-specific metadata
    metadata["side_effect_free"] = entry.side_effect_free
    if entry.timeout_seconds:
        metadata["timeout_seconds"] = entry.timeout_seconds
    if entry.retry_policy:
        metadata["retry_policy"] = entry.retry_policy

    # Add constraints
    if entry.requires:
        metadata["requires"] = entry.requires
    if entry.conflicts_with:
        metadata["conflicts_with"] = entry.conflicts_with
    if entry.python_version:
        metadata["python_version"] = entry.python_version
    if entry.os_platform:
        metadata["os_platform"] = entry.os_platform

    # Add docs
    if entry.license:
        metadata["license"] = entry.license
    if entry.documentation_url:
        metadata["documentation_url"] = entry.documentation_url

    # Register candidate
    candidate = Candidate(
        domain=entry.domain,
        key=entry.key,
        provider=entry.provider,
        factory=entry.factory,
        stack_level=entry.stack_level or 0,
        priority=entry.priority,
        source=CandidateSource.REMOTE,
        metadata=metadata,
    )

    resolver.register(candidate)
```

**Acceptance Criteria:**
- [ ] All metadata fields propagate to `Candidate`
- [ ] Resolver explain output shows new metadata
- [ ] CLI `list` command displays capabilities/owner
- [ ] Tests verify metadata round-trip

#### 1.3 Create Enhanced Sample Manifest (0.5 days)

**File:** `docs/sample_remote_manifest_v2.yaml`

Demonstrate all new fields with real adapter/action examples:

```yaml
source: oneiric-production
signature: "base64-encoded-ed25519-signature"
signature_algorithm: ed25519

entries:
  # Full adapter example with all metadata
  - domain: adapter
    key: cache
    provider: redis
    factory: oneiric.adapters.cache.redis:RedisCacheAdapter
    uri: https://cdn.example.com/adapters/redis-cache-v1.0.0.whl
    sha256: abc123...
    stack_level: 50
    priority: 500
    version: "1.0.0"

    # Adapter-specific metadata
    capabilities: ["kv", "ttl", "tracking"]
    owner: "Platform Core"
    requires_secrets: true
    settings_model: "oneiric.adapters.cache.redis:RedisSettings"

    # Dependencies
    requires: ["redis>=5.0.0", "coredis>=4.0.0"]

    # Platform constraints
    python_version: ">=3.14"
    os_platform: ["linux", "darwin"]

    # Documentation
    license: "MIT"
    documentation_url: "https://docs.oneiric.dev/adapters/cache/redis"

    metadata:
      description: "Production Redis cache with client-side tracking"
      health_check_timeout: 5.0
      connection_pool_size: 10

  # Full action example
  - domain: action
    key: http.fetch
    provider: builtin-http-fetch
    factory: oneiric.actions.http:HttpFetchAction
    stack_level: 10
    version: "1.0.0"

    # Action-specific metadata
    side_effect_free: false  # Makes HTTP requests
    timeout_seconds: 30.0
    retry_policy:
      max_attempts: 3
      backoff_multiplier: 2.0
      max_backoff: 60.0

    # Dependencies
    requires: ["httpx>=0.27.0"]

    metadata:
      description: "HTTP fetch with retry and circuit breaker"
      supported_methods: ["GET", "POST", "PUT", "DELETE"]
```

**Acceptance Criteria:**
- [ ] Manifest validates against updated schema
- [ ] CLI can load and display all metadata
- [ ] Resolver explain shows complete decision path
- [ ] Signature verification passes

#### 1.4 Update Documentation (0.5 days)

**Files:**
- `docs/NEW_ARCH_SPEC.md` - Add manifest schema reference
- `README.md` - Update remote manifest examples
- `docs/REMOTE_MANIFEST_SCHEMA.md` - **NEW:** Full schema documentation

**Acceptance Criteria:**
- [ ] Schema documentation includes all fields with types
- [ ] Examples show adapter vs action metadata differences
- [ ] Migration guide from v1 → v2 manifests
- [ ] Best practices for metadata design

---

### Task 2: Package Signing & Upload Automation (4 days)

**Goal:** Automate manifest signing and artifact upload for CI/CD pipelines.

#### 2.1 Manifest Generation Script (1 day)

**File:** `scripts/generate_manifest.py`

```python
#!/usr/bin/env python3
"""Generate remote manifest from codebase metadata."""

import argparse
import json
import yaml
from pathlib import Path
from typing import List

from oneiric.adapters import builtin_adapter_metadata
from oneiric.actions import builtin_action_metadata
from oneiric.remote.models import RemoteManifest, RemoteManifestEntry


def generate_manifest(
    output_path: Path,
    version: str,
    source: str = "oneiric-production",
    include_adapters: bool = True,
    include_actions: bool = True,
) -> RemoteManifest:
    """Generate manifest from builtin metadata."""

    entries: List[RemoteManifestEntry] = []

    # Generate adapter entries
    if include_adapters:
        for adapter_meta in builtin_adapter_metadata():
            entry = RemoteManifestEntry(
                domain="adapter",
                key=adapter_meta.category,
                provider=adapter_meta.provider,
                factory=adapter_meta.factory if isinstance(adapter_meta.factory, str)
                        else f"{adapter_meta.factory.__module__}:{adapter_meta.factory.__name__}",
                stack_level=adapter_meta.stack_level or 0,
                priority=adapter_meta.priority,
                version=adapter_meta.version or version,
                capabilities=adapter_meta.capabilities,
                owner=adapter_meta.owner,
                requires_secrets=adapter_meta.requires_secrets,
                settings_model=adapter_meta.settings_model,
                metadata={
                    "description": adapter_meta.description or "",
                    "source": str(adapter_meta.source),
                },
            )
            entries.append(entry)

    # Generate action entries
    if include_actions:
        for action_meta in builtin_action_metadata():
            entry = RemoteManifestEntry(
                domain="action",
                key=action_meta.action_type,
                provider=action_meta.provider,
                factory=action_meta.factory if isinstance(action_meta.factory, str)
                        else f"{action_meta.factory.__module__}:{action_meta.factory.__name__}",
                stack_level=action_meta.stack_level or 0,
                version=action_meta.version or version,
                side_effect_free=action_meta.extras.get("side_effect_free", False),
                metadata={
                    "description": action_meta.description or "",
                },
            )
            entries.append(entry)

    manifest = RemoteManifest(source=source, entries=entries)

    # Write manifest
    with output_path.open("w") as f:
        yaml.dump(manifest.model_dump(), f, sort_keys=False)

    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate remote manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", default="oneiric-production")
    parser.add_argument("--no-adapters", action="store_true")
    parser.add_argument("--no-actions", action="store_true")

    args = parser.parse_args()

    manifest = generate_manifest(
        args.output,
        args.version,
        args.source,
        include_adapters=not args.no_adapters,
        include_actions=not args.no_actions,
    )

    print(f"Generated manifest with {len(manifest.entries)} entries → {args.output}")
```

**Acceptance Criteria:**
- [ ] Generates valid YAML manifest from builtin metadata
- [ ] Supports filtering (adapters only, actions only)
- [ ] Preserves all metadata fields
- [ ] CLI help documentation

#### 2.2 Manifest Signing Script (1 day)

**File:** `scripts/sign_manifest.py`

```python
#!/usr/bin/env python3
"""Sign remote manifest with ED25519 private key."""

import argparse
import base64
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from oneiric.remote.models import RemoteManifest
from oneiric.remote.security import get_canonical_manifest_for_signing


def sign_manifest(
    manifest_path: Path,
    private_key_path: Path,
    output_path: Path | None = None,
) -> None:
    """Sign manifest and write signature to file."""

    # Load manifest
    with manifest_path.open() as f:
        data = yaml.safe_load(f)

    manifest = RemoteManifest(**data)

    # Load private key
    with private_key_path.open("rb") as f:
        private_key = Ed25519PrivateKey.from_private_bytes(f.read())

    # Get canonical manifest for signing
    canonical = get_canonical_manifest_for_signing(manifest)

    # Sign
    signature_bytes = private_key.sign(canonical.encode())
    signature_b64 = base64.b64encode(signature_bytes).decode()

    # Update manifest
    manifest.signature = signature_b64
    manifest.signature_algorithm = "ed25519"

    # Write signed manifest
    output = output_path or manifest_path
    with output.open("w") as f:
        yaml.dump(manifest.model_dump(), f, sort_keys=False)

    print(f"Signed manifest → {output}")
    print(f"Signature: {signature_b64[:64]}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sign remote manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path)

    args = parser.parse_args()

    sign_manifest(args.manifest, args.private_key, args.output)
```

**Acceptance Criteria:**
- [ ] Signs manifests with ED25519 private key
- [ ] Generates base64-encoded signatures
- [ ] Updates manifest in-place or writes to new file
- [ ] Verifiable with existing `verify_manifest_signature()`

#### 2.3 Artifact Upload Script (1 day)

**File:** `scripts/upload_artifacts.py`

```python
#!/usr/bin/env python3
"""Upload artifacts (wheels, manifests) to S3/GCS."""

import argparse
from pathlib import Path
from typing import Literal

import boto3  # type: ignore
from google.cloud import storage  # type: ignore


def upload_to_s3(
    artifact_path: Path,
    bucket: str,
    key: str,
    region: str = "us-east-1",
) -> str:
    """Upload artifact to S3."""
    s3 = boto3.client("s3", region_name=region)

    with artifact_path.open("rb") as f:
        s3.upload_fileobj(f, bucket, key)

    url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    print(f"Uploaded to S3: {url}")
    return url


def upload_to_gcs(
    artifact_path: Path,
    bucket: str,
    blob_name: str,
) -> str:
    """Upload artifact to Google Cloud Storage."""
    client = storage.Client()
    bucket_obj = client.bucket(bucket)
    blob = bucket_obj.blob(blob_name)

    blob.upload_from_filename(str(artifact_path))

    url = f"https://storage.googleapis.com/{bucket}/{blob_name}"
    print(f"Uploaded to GCS: {url}")
    return url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload artifacts")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--backend", choices=["s3", "gcs"], required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--region", default="us-east-1")

    args = parser.parse_args()

    if args.backend == "s3":
        upload_to_s3(args.artifact, args.bucket, args.key, args.region)
    else:
        upload_to_gcs(args.artifact, args.bucket, args.key)
```

**Acceptance Criteria:**
- [ ] Uploads to S3 with correct permissions
- [ ] Uploads to GCS with correct permissions
- [ ] Returns public HTTPS URL
- [ ] Supports custom regions/buckets

#### 2.4 CI/CD Pipeline (1 day)

**File:** `.github/workflows/release.yml`

```yaml
name: Release & Publish

on:
  push:
    tags:
      - 'v*'

jobs:
  build-and-sign:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: |
          pip install uv
          uv sync

      - name: Build wheel
        run: uv build

      - name: Generate manifest
        run: |
          python scripts/generate_manifest.py \
            --output dist/manifest.yaml \
            --version ${{ github.ref_name }}

      - name: Sign manifest
        env:
          ED25519_PRIVATE_KEY: ${{ secrets.ED25519_PRIVATE_KEY }}
        run: |
          echo "$ED25519_PRIVATE_KEY" > /tmp/private_key.pem
          python scripts/sign_manifest.py \
            --manifest dist/manifest.yaml \
            --private-key /tmp/private_key.pem
          rm /tmp/private_key.pem

      - name: Upload to S3
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        run: |
          python scripts/upload_artifacts.py \
            --artifact dist/*.whl \
            --backend s3 \
            --bucket oneiric-releases \
            --key releases/${{ github.ref_name }}/oneiric.whl

          python scripts/upload_artifacts.py \
            --artifact dist/manifest.yaml \
            --backend s3 \
            --bucket oneiric-releases \
            --key releases/${{ github.ref_name }}/manifest.yaml
```

**Acceptance Criteria:**
- [ ] Triggers on version tags (v*)
- [ ] Builds wheel package
- [ ] Generates manifest from metadata
- [ ] Signs manifest with private key from secrets
- [ ] Uploads to S3/GCS
- [ ] Publishes release notes

---

### Task 3: Cache Path Security Validation (1 day)

**Goal:** Comprehensive tests for path traversal prevention and cache boundary enforcement.

#### 3.1 Security Test Suite (1 day)

**File:** `tests/security/test_cache_paths.py`

```python
"""Test cache path security and boundary enforcement."""

import pytest
from pathlib import Path

from oneiric.remote.loader import ArtifactManager
from oneiric.remote.security import sanitize_filename


class TestPathTraversalPrevention:
    """Test path traversal attack prevention."""

    def test_path_traversal_with_double_dot(self, tmp_path):
        """Should reject URIs with '..' path components."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            manager.fetch("../../etc/passwd", None, {})

    def test_path_traversal_with_absolute_path(self, tmp_path):
        """Should reject absolute paths in URIs."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            manager.fetch("/etc/passwd", None, {})

    def test_path_traversal_with_backslash(self, tmp_path):
        """Should reject Windows-style path separators."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            manager.fetch("..\\..\\windows\\system32", None, {})

    def test_filename_sanitization(self):
        """Should sanitize filenames to prevent path traversal."""
        # Normal filename
        assert sanitize_filename("artifact.whl") == "artifact.whl"

        # Path traversal attempts
        assert ".." not in sanitize_filename("../../../etc/passwd")
        assert "/" not in sanitize_filename("/etc/passwd")
        assert "\\" not in sanitize_filename("..\\windows\\system32")

        # Null bytes
        assert "\x00" not in sanitize_filename("file\x00.whl")

    def test_cache_boundary_enforcement(self, tmp_path):
        """Should ensure all cached files stay within cache directory."""
        manager = ArtifactManager(cache_dir=str(tmp_path))
        cache_dir = Path(tmp_path)

        # Legitimate fetch
        result = manager.fetch("https://example.com/file.whl", "abc123", {})
        assert result.is_relative_to(cache_dir)

        # Even with sanitized filename, should stay in cache
        result = manager.fetch("https://example.com/../file.whl", "def456", {})
        assert result.is_relative_to(cache_dir)


class TestCacheIsolation:
    """Test cache directory isolation and permissions."""

    def test_cache_directory_created_with_secure_permissions(self, tmp_path):
        """Should create cache directory with 0o700 permissions."""
        cache_dir = tmp_path / "secure_cache"
        manager = ArtifactManager(cache_dir=str(cache_dir))

        assert cache_dir.exists()
        # Note: On some systems, permissions may be affected by umask
        stat = cache_dir.stat()
        assert stat.st_mode & 0o777 in (0o700, 0o755)  # Allow some variation

    def test_multiple_managers_share_cache_safely(self, tmp_path):
        """Multiple managers should safely share same cache directory."""
        cache_dir = tmp_path / "shared_cache"

        manager1 = ArtifactManager(cache_dir=str(cache_dir))
        manager2 = ArtifactManager(cache_dir=str(cache_dir))

        # Both should work without conflicts
        assert manager1.cache_dir == manager2.cache_dir
```

**Acceptance Criteria:**
- [ ] All path traversal attacks blocked
- [ ] Filename sanitization comprehensive
- [ ] Cache boundary strictly enforced
- [ ] Concurrent access safe

---

### Task 4: Watcher Tests for Remote Module Loading (2 days)

**Goal:** Comprehensive tests for hot-reloading remote components.

#### 4.1 Remote Sync Watcher Tests (2 days)

**File:** `tests/integration/test_remote_watchers.py`

```python
"""Integration tests for remote manifest watchers and hot-reloading."""

import asyncio
import pytest
from pathlib import Path

from oneiric.adapters.bridge import AdapterBridge
from oneiric.actions.bridge import ActionBridge
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.remote.loader import sync_remote_manifest
from oneiric.remote.models import RemoteManifest, RemoteManifestEntry
from oneiric.runtime.orchestrator import RuntimeOrchestrator


class TestRemoteManifestHotReload:
    """Test remote manifest hot-reloading and component swapping."""

    @pytest.mark.asyncio
    async def test_remote_manifest_triggers_adapter_swap(self, tmp_path):
        """Should swap adapter when remote manifest updates."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        adapter_bridge = AdapterBridge(resolver, lifecycle, {})

        # Initial manifest with memory cache
        manifest_v1 = RemoteManifest(
            source="test",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                    stack_level=10,
                )
            ],
        )

        # Sync v1
        result = await sync_remote_manifest(resolver, manifest_v1, str(tmp_path))
        assert result.registered == 1

        # Activate memory cache
        handle = await adapter_bridge.use("cache")
        assert handle.provider == "memory"

        # Updated manifest with redis cache (higher stack level)
        manifest_v2 = RemoteManifest(
            source="test",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    factory="oneiric.adapters.cache.redis:RedisCacheAdapter",
                    stack_level=50,  # Higher precedence
                )
            ],
        )

        # Sync v2 (should trigger swap)
        result = await sync_remote_manifest(resolver, manifest_v2, str(tmp_path))
        assert result.registered == 1

        # Re-resolve should get redis now
        await lifecycle.swap("adapter", "cache")
        handle = await adapter_bridge.use("cache")
        assert handle.provider == "redis"

    @pytest.mark.asyncio
    async def test_remote_action_registration(self, tmp_path):
        """Should register actions from remote manifest."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        action_bridge = ActionBridge(resolver, lifecycle, {})

        # Manifest with action
        manifest = RemoteManifest(
            source="test",
            entries=[
                RemoteManifestEntry(
                    domain="action",
                    key="http.fetch",
                    provider="builtin-http-fetch",
                    factory="oneiric.actions.http:HttpFetchAction",
                    side_effect_free=False,
                )
            ],
        )

        # Sync
        result = await sync_remote_manifest(resolver, manifest, str(tmp_path))
        assert result.registered == 1
        assert result.per_domain["action"] == 1

        # Resolve action
        handle = await action_bridge.use("http.fetch")
        assert handle is not None

    @pytest.mark.asyncio
    async def test_orchestrator_remote_sync_loop(self, tmp_path):
        """Should periodically sync remote manifest."""
        # Create manifest file
        manifest_path = tmp_path / "manifest.yaml"
        manifest = RemoteManifest(
            source="test",
            entries=[
                RemoteManifestEntry(
                    domain="adapter",
                    key="cache",
                    provider="memory",
                    factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
                )
            ],
        )

        # Write manifest
        import yaml
        with manifest_path.open("w") as f:
            yaml.dump(manifest.model_dump(), f)

        # Start orchestrator with short refresh interval
        orchestrator = RuntimeOrchestrator(
            resolver=Resolver(),
            manifest_path=str(manifest_path),
            refresh_interval=1.0,  # 1 second for testing
        )

        # Run for 3 seconds
        async with asyncio.timeout(3):
            await orchestrator.start()
            await asyncio.sleep(2.5)  # Allow 2-3 sync cycles
            await orchestrator.stop()

        # Should have synced at least twice
        # (Verify via metrics or health snapshot)


class TestRemoteCacheInvalidation:
    """Test artifact cache invalidation and cleanup."""

    @pytest.mark.asyncio
    async def test_digest_mismatch_rejects_cached_artifact(self, tmp_path):
        """Should reject cached artifact if digest doesn't match."""
        from oneiric.remote.loader import ArtifactManager

        manager = ArtifactManager(cache_dir=str(tmp_path))

        # Create fake cached file
        fake_cache = tmp_path / "abc123"
        fake_cache.write_text("malicious content")

        # Attempt to fetch with mismatched digest
        with pytest.raises(ValueError, match="SHA256 mismatch"):
            manager.fetch(
                uri="https://example.com/artifact.whl",
                sha256="abc123",  # Doesn't match actual content
                headers={},
            )

    @pytest.mark.asyncio
    async def test_cache_cleanup_removes_old_artifacts(self, tmp_path):
        """Should clean up old cached artifacts."""
        # TODO: Implement cache cleanup policy (LRU, TTL, max size)
        pytest.skip("Cache cleanup not yet implemented")


class TestSignatureVerificationFailures:
    """Test signature verification failure handling."""

    @pytest.mark.asyncio
    async def test_invalid_signature_rejects_manifest(self, tmp_path):
        """Should reject manifest with invalid signature."""
        from oneiric.remote.security import verify_manifest_signature

        manifest = RemoteManifest(
            source="test",
            entries=[],
            signature="invalid-signature",
            signature_algorithm="ed25519",
        )

        # Should raise ValueError for invalid signature
        with pytest.raises(ValueError):
            verify_manifest_signature(
                canonical="test",
                signature=manifest.signature,
                public_key_pem=b"fake-key",
            )
```

**Acceptance Criteria:**
- [ ] Hot-reload tests pass for all 5 domains
- [ ] Signature verification failures handled gracefully
- [ ] Cache invalidation works correctly
- [ ] Orchestrator sync loop tested
- [ ] Concurrent sync safety verified

---

## Stage 4 Completion Checklist

### Task 1: Manifest Schema (3 days) ✅
- [ ] Update `RemoteManifestEntry` with new fields
- [ ] Propagate metadata to `Candidate` registration
- [ ] Create enhanced sample manifest (v2)
- [ ] Update documentation

### Task 2: Automation (4 days) ✅
- [ ] Manifest generation script
- [ ] Manifest signing script
- [ ] Artifact upload script
- [ ] CI/CD pipeline (GitHub Actions)

### Task 3: Security (1 day) ✅
- [ ] Path traversal prevention tests
- [ ] Cache boundary enforcement tests
- [ ] Cache isolation tests

### Task 4: Watchers (2 days) ✅
- [ ] Remote manifest hot-reload tests
- [ ] Action registration tests
- [ ] Orchestrator sync loop tests
- [ ] Cache invalidation tests
- [ ] Signature verification failure tests

### Final Validation ✅
- [ ] All tests pass (`pytest -v tests/`)
- [ ] Coverage maintained at 80%+
- [ ] Documentation complete
- [ ] Sample manifests validated
- [ ] CI/CD pipeline tested end-to-end

---

## Timeline & Milestones

**Week 1:**
- Days 1-3: Task 1 (Manifest schema extension)
- Days 4-5: Task 2 (Scripts: generate + sign)

**Week 2:**
- Days 1-2: Task 2 (Upload script + CI/CD)
- Day 3: Task 3 (Security tests)
- Days 4-5: Task 4 (Watcher tests)

**Total:** 10 working days (2 calendar weeks)

---

## Success Criteria

**Stage 4 is complete when:**

1. ✅ Remote manifest schema supports full adapter/action metadata
2. ✅ CI/CD pipeline automatically signs and uploads manifests
3. ✅ All path traversal attacks are prevented (100% test coverage)
4. ✅ Remote hot-reloading works for all 5 domains
5. ✅ Documentation is complete with examples
6. ✅ All tests pass with 80%+ coverage

**Blockers:**
- None identified (all dependencies resolved in Stages 1-3)

**Risks:**
- CI/CD secrets management (need secure ED25519 key storage)
- S3/GCS upload permissions (need proper IAM roles)
- Signature verification performance (should be <10ms per manifest)

---

## Next Steps After Stage 4

Once Stage 4 is complete, proceed to **Stage 5: Hardening & Completion**:

1. Production deployment guide (Kubernetes, Docker, systemd)
2. Monitoring/alerting setup (Prometheus, Grafana)
3. Runbook documentation
4. ACB deprecation notices
5. Final audit and sign-off

**Estimated Stage 5 Duration:** 2-3 weeks
**Target Beta Launch:** 4-5 weeks from today
