# Remote Manifest Schema Reference

**Version:** 2.0 (Stage 4 Enhancement)
**Status:** Production Ready
**Backward Compatible:** Yes (all new fields are optional)

______________________________________________________________________

## Overview

The remote manifest schema defines how components (adapters, actions, services, tasks, events, workflows) are registered remotely. Version 2.0 adds comprehensive metadata support for production deployments while maintaining full backward compatibility with v1 manifests.

### Schema Versions

- **v1 (legacy):** Basic fields (domain, key, provider, factory, uri, sha256, stack_level, priority, version, metadata)
- **v2 (current):** Adds adapter-specific, action-specific, dependency, platform, and documentation fields

All v2 fields are optional - v1 manifests continue to work unchanged.

______________________________________________________________________

## Manifest Structure

```yaml
source: string                    # Manifest source identifier (required)
signature: string                 # Base64-encoded ED25519 signature (optional)
signature_algorithm: "ed25519"    # Signature algorithm (default: ed25519)
entries: [RemoteManifestEntry]    # List of component entries (required)
```

______________________________________________________________________

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
| `sha256` | `str` | Expected SHA256 digest (hex string) | `"abc123def456..."` (64 chars) |

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

______________________________________________________________________

## v2 Schema Enhancements (Stage 4)

### Adapter-Specific Fields

```yaml
capabilities:
  - name: kv                     # required capability identifier
    description: Key/value cache # optional human-friendly description
    event_types: []              # optional list of events emitted/handled
    payload_schema: {}           # JSON schema dict or $ref string
    schema_format: jsonschema    # identifies schema dialect
    security:                    # capability-specific posture
      classification: internal
      auth_required: true
      scopes: ["cache.read"]
      encryption: tls
      signature_required: false
      audience: ["platform"]
    metadata: {}                 # arbitrary extra metadata per capability
```

| Field | Type | Description | Example | Use Case |
|-------|------|-------------|---------|----------|
| `capabilities` | `list[CapabilityDescriptor or str]` | Capability descriptors (name + optional schema/security metadata). Strings remain supported for backward compatibility. | `[{"name": "kv", "event_types": ["cache.hit"], "payload_schema": {...}, "security": {...}}, "ttl"]` | Feature discovery, manifest linting |
| `owner` | `str` | Team/person responsible | `"Platform Core Team"` | Ownership tracking |
| `requires_secrets` | `bool` | Whether secrets are required | `true` | Security validation |
| `settings_model` | `str` | Import path to Pydantic settings model | `"oneiric.adapters.cache.redis:RedisSettings"` | Config validation |

### Action-Specific Fields

| Field | Type | Description | Example | Use Case |
|-------|------|-------------|---------|----------|
| `side_effect_free` | `bool` | Whether action has side effects | `false` | Safety analysis |
| `timeout_seconds` | `float` | Action execution timeout | `30.0` | Timeout enforcement |
| `retry_policy` | `dict` | Retry configuration | `{"attempts": 3, "base_delay": 0.5}` | Resilience |

#### Retry Policy Schema

```yaml
retry_policy:
  attempts: int          # Total attempts (>=1). Dispatcher stops after this many tries.
  base_delay: float      # Initial delay between attempts (seconds, >=0.0).
  max_delay: float       # Maximum backoff delay (seconds, >= base_delay).
  jitter: float          # Random jitter factor (0.0-1.0) applied to waits.
  retriable_status_codes: [int] # Optional HTTP codes for action adapters.
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

### Event & Workflow Fields (Stage 5 Prototype)

| Field | Type | Description | Example | Use Case |
|-------|------|-------------|---------|----------|
| `event_topics` | `list[str]` | Topics/events handled by this candidate | `["user.created", "user.updated"]` | Event dispatcher fan-out |
| `event_max_concurrency` | `int` | Hint for handler concurrency | `5` | Dispatcher throttling |
| `event_filters` | `list[Filter]` | Optional payload/header filters applied before invoking the handler | `[{"path": "payload.region", "equals": "us"}]` | Shard events by attributes |
| `event_priority` | `int` | Priority override used to sort handlers | `50` | Prefer regional handlers |
| `event_fanout_policy` | `str` | `broadcast` (default) or `exclusive` fan-out | `"exclusive"` | Ensure only one handler runs |
| `dag` | `dict` | Workflow DAG definition (nodes/tasks/dependencies) | `{"nodes": [{"id": "extract", "task": "extract-task"}]}` | WorkflowBridge DAG execution |

**Event Filter Schema**

```yaml
event_filters:
  - path: payload.region     # path to inspect (`payload.*`, `headers.*`, or `topic`)
    equals: "us"             # optional equality check
    any_of: ["us", "ca"]     # optional inclusion check (list or scalar)
    exists: true             # optional existence boolean (true/false)
```

Filters are ANDed together. The dispatcher rejects the handler when any filter fails, allowing fine-grained routing without duplicating topics.

#### DAG Schema (Prototype)

```yaml
dag:
  nodes:
    - id: extract-stage            # Unique node ID
      task: extract-task           # Task domain key to execute
      depends_on: []               # Optional dependencies
      payload: {key: value}        # Optional payload override passed to the task
  retry_policy:
    attempts: 3
    base_delay: 0.5
    max_delay: 2.0
  scheduler:
    category: queue.scheduler
    provider: cloudtasks

event_metadata:
  - topic: fastblocks.order.created
    handler: fastblocks.events.order-handler
    event_filters:
      - path: payload.region
        any_of: ["us", "ca"]
    event_priority: 50
    event_fanout_policy: exclusive
    retry_policy:
      attempts: 3
      base_delay: 0.5
      jitter: 0.2
```

______________________________________________________________________

## Complete Example

```yaml
source: oneiric-production-v2
signature: "base64-encoded-ed25519-signature"
signature_algorithm: ed25519

entries:
  # Full adapter example with capability descriptors + v2 fields
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
    capabilities:
      - name: kv
        description: Key/value cache
        event_types: ["cache.hit", "cache.miss"]
        payload_schema:
          type: object
          required: [key, value]
        schema_format: jsonschema
        security:
          classification: internal
          auth_required: true
          scopes: ["cache.read", "cache.write"]
      - name: ttl
      - name: tracking
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
      attempts: 3
      base_delay: 0.5
      max_delay: 10.0
      jitter: 0.1
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

  # Event handler example with topics/concurrency
  - domain: event
    key: user.webhook
    provider: http-handler
    factory: "example.events.webhook:WebhookHandler"
    event_topics: ["user.created", "user.updated"]
    event_max_concurrency: 10
    event_filters:
      - path: payload.account_region
        any_of: ["us", "ca"]
      - path: headers.trace_id
        exists: true
    event_priority: 75
    event_fanout_policy: exclusive
    retry_policy:
      attempts: 3
      base_delay: 0.2
      max_delay: 2.0
      jitter: 0.1
    metadata:
      description: "Dispatches user webhooks"

Event handlers inherit the same `retry_policy` structure as actions; Oneiric's dispatcher will retry the handler callback according to `attempts/base_delay/max_delay/jitter` and record the attempt count in CLI telemetry (`oneiric.cli event emit` output).

  # Workflow DAG example
  - domain: workflow
    key: signup-pipeline
    provider: dag-orchestrator
    factory: "example.workflows.signup:SignupWorkflow"
    metadata:
      description: "Signup pipeline DAG orchestrator"
      scheduler:
        queue_category: queue.scheduler
        provider: cloudtasks
    dag:
      nodes:
        - id: extract
          task: extract-task
          retry_policy:
            attempts: 3
            base_delay: 0.25
            max_delay: 2.0
            jitter: 0.1
        - id: notify
          task: notify-task
          depends_on: ["extract"]
```

Workflow nodes support the following keys:

- `id` / `task` – Required identifiers.
- `depends_on` – List of upstream node ids.
- `payload` – Per-node payload merged with workflow context (optional).
- `retry_policy` – Optional task-level retry policy identical to the action/event schema (`attempts`, `base_delay`, `max_delay`, `jitter`). The runtime uses it to retry individual nodes and record attempt counts/checkpoints.

Workflows can also provide `metadata.scheduler` to control which queue adapter handles DAG triggers. When `workflow enqueue` (or `WorkflowBridge.enqueue_workflow`) is invoked, the runtime resolves the queue category/provider using the following precedence: CLI override flags → `metadata.scheduler.queue_category` / `.provider` (or `.category`) → the bridge default (`queue` unless overridden in settings). This makes it easy to route specific workflows to Cloud Tasks (`queue.scheduler`), Pub/Sub, or another adapter without editing CLI invocations.

______________________________________________________________________

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

______________________________________________________________________

## Signature Verification

Remote manifests can be cryptographically signed using ED25519:

### Signing Process

1. **Generate canonical representation** (deterministic YAML serialization)
1. **Sign with ED25519 private key**
1. **Encode signature as base64**
1. **Add signature to manifest**

```bash
python scripts/sign_manifest.py \
  --manifest manifest.yaml \
  --private-key private_key.pem
```

### Verification Process

1. **Load manifest**
1. **Extract signature field**
1. **Regenerate canonical representation**
1. **Verify signature with ED25519 public key**

If signature is invalid or missing (when required), manifest loading fails.

______________________________________________________________________

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
  attempts: 3
  base_delay: 0.5
```

**Phase 4:** Add documentation

```yaml
# Add license and docs
license: "MIT"
documentation_url: "https://docs.oneiric.dev/..."
```

______________________________________________________________________

## Best Practices

### Adapter Metadata Design

1. **Capabilities should be specific:** Use `["kv", "ttl"]` not `["general"]`
1. **Owner should be a team name:** `"Platform Core Team"` not `"john@example.com"`
1. **Settings model must be importable:** Verify path before deployment
1. **Mark requires_secrets accurately:** Enables security auditing

### Action Metadata Design

1. **side_effect_free is critical:** Used for caching and retry decisions
1. **timeout_seconds should be realistic:** Based on p99 latency + buffer
1. **Retry policy should match failure modes:**
   - Idempotent operations: `attempts: 5`
   - Non-idempotent: `attempts: 1`
1. **retriable_status_codes should be conservative:** Only retry transient errors

### Dependency Constraints

1. **Use semantic versioning:** `"package>=1.0.0,<2.0.0"`
1. **Pin major versions only:** Allow minor/patch updates
1. **List direct dependencies only:** Not transitive dependencies
1. **conflicts_with is for breaking changes:** Document why in metadata

### Platform Constraints

1. **python_version should use >=:** `">=3.14"` not `"==3.14"`
1. **os_platform should list tested platforms:** Not theoretical support
1. **Avoid over-constraining:** Only add constraints when necessary

______________________________________________________________________

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

______________________________________________________________________

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

______________________________________________________________________

## Security Considerations

1. **Always verify signatures in production** - Set `public_key` in `RemoteManifest`
1. **Use HTTPS for uri fields** - Prevent MITM attacks
1. **Validate sha256 hashes** - Detect artifact tampering
1. **Review requires/conflicts_with** - Prevent dependency confusion attacks
1. **Audit requires_secrets=True** - Ensure proper secrets management

______________________________________________________________________

## Performance

- **Manifest parsing:** \<10ms for 100 entries
- **Signature verification:** \<5ms per manifest (ED25519)
- **Artifact fetching:** Depends on network (cached after first fetch)
- **Candidate registration:** \<1ms per entry

**Tip:** Use `refresh_interval` wisely - manifests are cached, refresh only when needed (default: 300s).

______________________________________________________________________

## See Also

- `docs/sample_remote_manifest_v2.yaml` - Complete examples
- `docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md` - Remote packaging + Cloud Run parity details
- `oneiric/remote/models.py` - Pydantic schema source
- `oneiric/remote/loader.py` - Loading implementation
- `oneiric/remote/security.py` - Signature verification
