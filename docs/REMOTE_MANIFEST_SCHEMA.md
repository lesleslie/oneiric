# Remote Manifest Schema Reference

**Version:** 2.0 (Stage 4 Enhancement)
**Status:** Production Ready
**Backward Compatible:** Yes (all new fields are optional)

---

## Overview

The remote manifest schema defines how components (adapters, actions, services, tasks, events, workflows) are registered remotely. Version 2.0 adds comprehensive metadata support for production deployments while maintaining full backward compatibility with v1 manifests.

### Schema Versions

- **v1 (legacy):** Basic fields (domain, key, provider, factory, uri, sha256, stack_level, priority, version, metadata)
- **v2 (current):** Adds adapter-specific, action-specific, dependency, platform, and documentation fields

All v2 fields are optional - v1 manifests continue to work unchanged.

---

## Manifest Structure

```yaml
source: string                    # Manifest source identifier (required)
signature: string                 # Base64-encoded ED25519 signature (optional)
signature_algorithm: "ed25519"    # Signature algorithm (default: ed25519)
entries: [RemoteManifestEntry]    # List of component entries (required)
```

---

## RemoteManifestEntry Schema

### Core Fields (Required)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `domain` | `str` | Component domain | `"adapter"`, `"action"`, `"service"`, `"task"`, `"event"`, `"workflow"` |
| `key` | `str` | Component key (unique within domain) | `"cache"`, `"http.fetch"`, `"payment-processor"` |
| `provider` | `str` | Provider name | `"redis"`, `"builtin-http-fetch"`, `"stripe"` |
| `factory` | `str` | Import path to factory callable | `"oneiric.adapters.cache.redis:RedisCacheAdapter"` |

### Artifact Fields (Optional)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `uri` | `str` | HTTP(S) URL or file path to artifact | `"https://cdn.example.com/redis-cache-v1.0.0.whl"` |
| `sha256` | `str` | Expected SHA256 digest (hex string) | `"abc123def456..."`  (64 chars) |

### Resolution Fields (Optional)

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `stack_level` | `int` | Stack precedence (higher wins) | `None` (uses registration order) |
| `priority` | `int` | Tie-breaker within same stack level | `None` |
| `version` | `str` | Semantic version | `"1.0.0"` |

### Generic Metadata (Optional)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `metadata` | `dict[str, Any]` | Free-form metadata | `{"description": "Redis cache", "health_check_timeout": 5.0}` |

---

## v2 Schema Enhancements (Stage 4)

### Adapter-Specific Fields

| Field | Type | Description | Example | Use Case |
|-------|------|-------------|---------|----------|
| `capabilities` | `list[str]` | Adapter capabilities | `["kv", "ttl", "tracking"]` | Feature discovery |
| `owner` | `str` | Team/person responsible | `"Platform Core Team"` | Ownership tracking |
| `requires_secrets` | `bool` | Whether secrets are required | `true` | Security validation |
| `settings_model` | `str` | Import path to Pydantic settings model | `"oneiric.adapters.cache.redis:RedisSettings"` | Config validation |

### Action-Specific Fields

| Field | Type | Description | Example | Use Case |
|-------|------|-------------|---------|----------|
| `side_effect_free` | `bool` | Whether action has side effects | `false` | Safety analysis |
| `timeout_seconds` | `float` | Action execution timeout | `30.0` | Timeout enforcement |
| `retry_policy` | `dict` | Retry configuration | `{"max_attempts": 3, "backoff_multiplier": 2.0}` | Resilience |

#### Retry Policy Schema

```yaml
retry_policy:
  max_attempts: int              # Maximum retry attempts (1-10)
  backoff_multiplier: float      # Exponential backoff multiplier (1.0-5.0)
  max_backoff: float            # Maximum backoff delay in seconds
  retriable_status_codes: [int] # HTTP status codes to retry (optional)
```

### Dependency Constraints

| Field | Type | Description | Example | Use Case |
|-------|------|-------------|---------|----------|
| `requires` | `list[str]` | Required packages (PEP 440 format) | `["redis>=5.0.0", "coredis>=4.0.0"]` | Dependency validation |
| `conflicts_with` | `list[str]` | Conflicting packages | `["old-redis<4.0"]` | Conflict detection |

### Platform Constraints

| Field | Type | Description | Example | Use Case |
|-------|------|-------------|---------|----------|
| `python_version` | `str` | Python version constraint (PEP 440) | `">=3.14"` | Python version check |
| `os_platform` | `list[str]` | Supported OS platforms | `["linux", "darwin", "windows"]` | Platform filtering |

**Supported OS Platforms:** `linux`, `darwin` (macOS), `windows`, `freebsd`, `openbsd`

### Documentation Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `license` | `str` | SPDX license identifier | `"MIT"`, `"Apache-2.0"`, `"Proprietary"` |
| `documentation_url` | `str` | HTTP(S) URL to documentation | `"https://docs.oneiric.dev/adapters/cache/redis"` |

---

## Complete Example

```yaml
source: oneiric-production-v2
signature: "base64-encoded-ed25519-signature"
signature_algorithm: ed25519

entries:
  # Full adapter example with all v2 fields
  - domain: adapter
    key: cache
    provider: redis
    factory: oneiric.adapters.cache.redis:RedisCacheAdapter

    # Artifact fields
    uri: https://cdn.example.com/releases/v1.0.0/redis-cache.whl
    sha256: abc123def456789abc123def456789abc123def456789abc123def456789abc1

    # Resolution fields
    stack_level: 50
    priority: 500
    version: "1.0.0"

    # Adapter-specific metadata (v2)
    capabilities: ["kv", "ttl", "tracking", "pub-sub"]
    owner: "Platform Core Team"
    requires_secrets: true
    settings_model: "oneiric.adapters.cache.redis:RedisSettings"

    # Dependencies (v2)
    requires:
      - "redis>=5.0.0"
      - "coredis>=4.0.0"

    # Platform constraints (v2)
    python_version: ">=3.14"
    os_platform: ["linux", "darwin"]

    # Documentation (v2)
    license: "MIT"
    documentation_url: "https://docs.oneiric.dev/adapters/cache/redis"

    # Generic metadata
    metadata:
      description: "Production Redis cache with client-side tracking"
      health_check_timeout: 5.0
      connection_pool_size: 10

  # Full action example with all v2 fields
  - domain: action
    key: http.fetch
    provider: builtin-http-fetch
    factory: oneiric.actions.http:HttpFetchAction
    stack_level: 10
    version: "1.0.0"

    # Action-specific metadata (v2)
    side_effect_free: false  # Makes HTTP requests
    timeout_seconds: 30.0
    retry_policy:
      max_attempts: 3
      backoff_multiplier: 2.0
      max_backoff: 60.0
      retriable_status_codes: [429, 500, 502, 503, 504]

    # Dependencies (v2)
    requires:
      - "httpx>=0.27.0"

    # Platform constraints (v2)
    python_version: ">=3.14"

    # Documentation (v2)
    license: "MIT"
    documentation_url: "https://docs.oneiric.dev/actions/http/fetch"

    # Generic metadata
    metadata:
      description: "HTTP fetch with retry and circuit breaker"
      supported_methods: ["GET", "POST", "PUT", "DELETE"]
```

---

## Metadata Propagation

All manifest entry fields are propagated to `Candidate` metadata during registration:

```python
from oneiric.remote.loader import sync_remote_manifest

# After sync, Candidate.metadata includes:
{
    # Core
    "remote_uri": "https://...",
    "artifact_path": "/path/to/cache/...",
    "version": "1.0.0",
    "source": "remote",

    # Adapter-specific (if present)
    "capabilities": ["kv", "ttl"],
    "owner": "Platform Core Team",
    "requires_secrets": True,
    "settings_model": "oneiric.adapters.cache.redis:RedisSettings",

    # Action-specific (if present)
    "side_effect_free": False,
    "timeout_seconds": 30.0,
    "retry_policy": {...},

    # Dependencies
    "requires": ["redis>=5.0.0"],
    "conflicts_with": [],

    # Platform
    "python_version": ">=3.14",
    "os_platform": ["linux", "darwin"],

    # Documentation
    "license": "MIT",
    "documentation_url": "https://...",

    # Generic metadata (merged)
    "description": "...",
    # ... other custom fields
}
```

Access via resolver explain API:

```bash
uv run python -m oneiric.cli explain cache --domain adapter
```

---

## Signature Verification

Remote manifests can be cryptographically signed using ED25519:

### Signing Process

1. **Generate canonical representation** (deterministic YAML serialization)
2. **Sign with ED25519 private key**
3. **Encode signature as base64**
4. **Add signature to manifest**

```bash
python scripts/sign_manifest.py \
  --manifest manifest.yaml \
  --private-key private_key.pem
```

### Verification Process

1. **Load manifest**
2. **Extract signature field**
3. **Regenerate canonical representation**
4. **Verify signature with ED25519 public key**

If signature is invalid or missing (when required), manifest loading fails.

---

## Migration Guide: v1 → v2

**Good News:** No migration required! All v2 fields are optional.

### Recommended Enhancement Path

**Phase 1:** Add adapter metadata
```yaml
# Before (v1)
- domain: adapter
  key: cache
  provider: redis
  factory: oneiric.adapters.cache.redis:RedisCacheAdapter

# After (v2)
- domain: adapter
  key: cache
  provider: redis
  factory: oneiric.adapters.cache.redis:RedisCacheAdapter
  capabilities: ["kv", "ttl"]
  owner: "Platform Core Team"
  requires_secrets: true
```

**Phase 2:** Add dependencies
```yaml
# Add Python and package requirements
requires:
  - "redis>=5.0.0"
python_version: ">=3.14"
```

**Phase 3:** Add action metadata
```yaml
# For actions, add timeout and retry policy
side_effect_free: false
timeout_seconds: 30.0
retry_policy:
  max_attempts: 3
  backoff_multiplier: 2.0
```

**Phase 4:** Add documentation
```yaml
# Add license and docs
license: "MIT"
documentation_url: "https://docs.oneiric.dev/..."
```

---

## Best Practices

### Adapter Metadata Design

1. **Capabilities should be specific:** Use `["kv", "ttl"]` not `["general"]`
2. **Owner should be a team name:** `"Platform Core Team"` not `"john@example.com"`
3. **Settings model must be importable:** Verify path before deployment
4. **Mark requires_secrets accurately:** Enables security auditing

### Action Metadata Design

1. **side_effect_free is critical:** Used for caching and retry decisions
2. **timeout_seconds should be realistic:** Based on p99 latency + buffer
3. **Retry policy should match failure modes:**
   - Idempotent operations: `max_attempts: 5`
   - Non-idempotent: `max_attempts: 1`
4. **retriable_status_codes should be conservative:** Only retry transient errors

### Dependency Constraints

1. **Use semantic versioning:** `"package>=1.0.0,<2.0.0"`
2. **Pin major versions only:** Allow minor/patch updates
3. **List direct dependencies only:** Not transitive dependencies
4. **conflicts_with is for breaking changes:** Document why in metadata

### Platform Constraints

1. **python_version should use >=:** `">=3.14"` not `"==3.14"`
2. **os_platform should list tested platforms:** Not theoretical support
3. **Avoid over-constraining:** Only add constraints when necessary

---

## Validation

Manifests are validated at load time using Pydantic:

```python
from oneiric.remote.models import RemoteManifest

# This will raise ValidationError if invalid
manifest = RemoteManifest(**yaml_data)
```

**Common Validation Errors:**

- Missing required fields (domain, key, provider, factory)
- Invalid version string (not semantic versioning)
- Invalid URL in uri field
- sha256 not 64 hex characters
- python_version not PEP 440 compliant
- os_platform contains unsupported value

---

## CLI Integration

View manifest metadata via CLI:

```bash
# List components with capabilities
uv run python -m oneiric.cli list --domain adapter

# Explain why a component was selected (shows all metadata)
uv run python -m oneiric.cli explain cache --domain adapter

# Show component status (includes remote metadata)
uv run python -m oneiric.cli status --domain adapter --key cache --json
```

---

## Security Considerations

1. **Always verify signatures in production** - Set `public_key` in `RemoteManifest`
2. **Use HTTPS for uri fields** - Prevent MITM attacks
3. **Validate sha256 hashes** - Detect artifact tampering
4. **Review requires/conflicts_with** - Prevent dependency confusion attacks
5. **Audit requires_secrets=True** - Ensure proper secrets management

---

## Performance

- **Manifest parsing:** <10ms for 100 entries
- **Signature verification:** <5ms per manifest (ED25519)
- **Artifact fetching:** Depends on network (cached after first fetch)
- **Candidate registration:** <1ms per entry

**Tip:** Use `refresh_interval` wisely - manifests are cached, refresh only when needed (default: 300s).

---

## See Also

- `docs/sample_remote_manifest_v2.yaml` - Complete examples
- `docs/STAGE4_REMOTE_PACKAGING_PLAN.md` - Implementation details
- `oneiric/remote/models.py` - Pydantic schema source
- `oneiric/remote/loader.py` - Loading implementation
- `oneiric/remote/security.py` - Signature verification
