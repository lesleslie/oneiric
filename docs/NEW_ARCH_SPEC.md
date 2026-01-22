# New Architecture Specification (Oneiric, Python 3.13 Baseline)

Goal: build Oneiric with unified resolution, lifecycle, observability, and plugin
support, reusing existing ACB adapters and actions where useful. Domains (adapters,
services, tasks, events, workflows) plug into the same resolver and lifecycle.

## Top-Level Packages

```mermaid
graph TB
    subgraph "Core Layer"
        Runtime["core/runtime<br/>Context, DI, TaskGroup"]
        Resolution["core/resolution<br/>Candidate model, Resolver"]
        Lifecycle["core/lifecycle<br/>Health, Swap, Rollback"]
        Observability["core/observability<br/>OTel, Metrics, Logging"]
        Plugins["core/plugins<br/>Discovery, Loader"]
    end

    subgraph "Domain Layer"
        AdapterBridge["adapters/bridge.py"]
        ServiceBridge["services/bridge.py"]
        TaskBridge["tasks/bridge.py"]
        EventBridge["events/bridge.py"]
        WorkflowBridge["workflows/bridge.py"]
    end

    Resolution -->|"resolves candidates"| AdapterBridge
    Resolution -->|"resolves candidates"| ServiceBridge
    Resolution -->|"resolves candidates"| TaskBridge
    Resolution -->|"resolves candidates"| EventBridge
    Resolution -->|"resolves candidates"| WorkflowBridge

    Lifecycle -->|"manages"| AdapterBridge
    Lifecycle -->|"manages"| ServiceBridge
    Lifecycle -->|"manages"| TaskBridge
    Lifecycle -->|"manages"| EventBridge
    Lifecycle -->|"manages"| WorkflowBridge

    Observability -->|"instruments"| Resolution
    Observability -->|"instruments"| Lifecycle
    Observability -->|"instruments"| AdapterBridge
    Observability -->|"instruments"| ServiceBridge
    Observability -->|"instruments"| TaskBridge
    Observability -->|"instruments"| EventBridge
    Observability -->|"instruments"| WorkflowBridge

    Plugins -->|"discovers"| Resolution
    Runtime -->|"orchestrates"| Lifecycle

    style Resolution fill:#e1f5ff
    style Lifecycle fill:#fff4e1
    style Observability fill:#f0e1ff
    style Plugins fill:#ffe1f0
```

**Package Overview:**

- **`core/runtime`**: Context, DI bindings, TaskGroup/nursery helpers, cancellation-safe
  utilities.
- **`core/resolution`**: Candidate model, resolver, registries (active/shadowed), explain
  API, hot-swap entry points.
- **`core/lifecycle`**: init/health/cleanup/pause-resume contracts, rollback helpers,
  swap orchestration.
- **`core/observability`**: OpenTelemetry tracer/metrics/logging helpers; structured
  fields (domain, key, provider, source, priority, stack_level).
- **`core/plugins`**: discovery sources (local package, entry points, remote manifest),
  plugin loader utilities.
- **Domain bridges**: `adapters/bridge.py`, `services/bridge.py`, `tasks/bridge.py`,
  `events/bridge.py`, `workflows/bridge.py` — each maps domain concepts to resolver
  keys and lifecycle hooks.

## Candidate Model (shared)

```mermaid
graph LR
    subgraph "Candidate Structure"
        Candidate["Candidate"]
        Domain["domain"]
        Key["key"]
        Provider["provider"]
        Priority["priority"]
        StackLevel["stack_level<br/>(z-index)"]
        Factory["factory/import"]
        Metadata["metadata<br/>(capabilities, version, source)"]
        HealthHook["health hook"]
        LifecycleHooks["lifecycle hooks"]
    end

    Candidate -->|"contains"| Domain
    Candidate -->|"contains"| Key
    Candidate -->|"contains"| Provider
    Candidate -->|"contains"| Priority
    Candidate -->|"contains"| StackLevel
    Candidate -->|"contains"| Factory
    Candidate -->|"contains"| Metadata
    Candidate -->|"contains"| HealthHook
    Candidate -->|"contains"| LifecycleHooks

    style Candidate fill:#e1f5ff
    style Priority fill:#fff4e1
    style StackLevel fill:#f0e1ff
```

**Candidate Fields:**

- **domain**: Component domain (adapter, service, task, event, workflow)
- **key**: Unique identifier within domain
- **provider**: Implementation name
- **priority**: Explicit priority value
- **stack_level**: Z-index style layering (default: 0)
- **factory/import**: Component instantiation method
- **metadata**: Capabilities, version, source information
- **health hook**: Health check callback
- **lifecycle hooks**: init, cleanup, pause/resume callbacks

### Resolution Precedence (4-tier)

```mermaid
graph TD
    Start["Resolver.resolve(domain, key)"]
    Tier1["Tier 1: Explicit Config Override<br/>(settings/*.yaml selections)"]
    Tier2["Tier 2: Package-Inferred Priority<br/>(ONEIRIC_STACK_ORDER env var)"]
    Tier3["Tier 3: Stack Level<br/>(candidate.metadata.stack_level)"]
    Tier4["Tier 4: Registration Order<br/>(last registered wins)"]

    Found{Candidate<br/>Found?}
    Result["Return Candidate"]

    Start --> Tier1
    Tier1 -->|"match found"| Found
    Tier1 -->|"no match"| Tier2
    Tier2 -->|"match found"| Found
    Tier2 -->|"no match"| Tier3
    Tier3 -->|"match found"| Found
    Tier3 -->|"no match"| Tier4
    Tier4 -->|"most recent"| Found
    Found -->|"yes"| Result
    Found -->|"no"| Result

    style Tier1 fill:#ffcccc
    style Tier2 fill:#ffe1cc
    style Tier3 fill:#fff4cc
    style Tier4 fill:#ccffcc
    style Result fill:#e1f5ff
```

**Precedence Rules** (highest to lowest):

1. **Explicit config override** - User selections in `settings/*.yaml` (e.g., `adapters.yml`)
1. **Package-inferred priority** - From `ONEIRIC_STACK_ORDER` env var or path heuristics
1. **Stack level** - Candidate metadata `stack_level` (z-index style)
1. **Registration order** - Last registered wins (tie-breaker)

## Domain Mapping

```mermaid
graph TB
    subgraph "Adapter Domain"
        AdapterKey["key = category<br/>(cache, queue, storage)"]
        AdapterProvider["provider = adapter name<br/>(redis, sqs, s3)"]
        AdapterMeta["metadata = capabilities, version"]
        AdapterLC["lifecycle = connections, clients"]
    end

    subgraph "Service Domain"
        ServiceKey["key = service_id"]
        ServiceProvider["provider = implementation"]
        ServiceLC["lifecycle + health"]
    end

    subgraph "Task Domain"
        TaskKey["key = task_type"]
        TaskProvider["provider = handler"]
        TaskHooks["pause/resume/drain hooks"]
        TaskResolve["resolver selects active"]
    end

    subgraph "Event Domain"
        EventKey["key = event name/type"]
        EventProvider["provider = handler"]
        EventDefault["highest-wins default"]
        EventPipeline["optional multi-handler<br/>pipeline ordered by priority"]
    end

    subgraph "Workflow Domain"
        WorkflowKey["key = workflow_id<br/>(+ optional version)"]
        WorkflowProvider["provider = definition/engine"]
        WorkflowFlag["activation flag"]
        WorkflowSwap["graceful swap<br/>(migrate in-flight)"]
    end

    Resolver["Resolver"]

    Resolver -->|"resolves"| AdapterKey
    Resolver -->|"resolves"| ServiceKey
    Resolver -->|"resolves"| TaskKey
    Resolver -->|"resolves"| EventKey
    Resolver -->|"resolves"| WorkflowKey

    style AdapterKey fill:#e1f5ff
    style ServiceKey fill:#ffe1f0
    style TaskKey fill:#f0e1ff
    style EventKey fill:#fff4e1
    style WorkflowKey fill:#e1ffe1
    style Resolver fill:#cccccc
```

**Domain Characteristics:**

- **Adapters**: key = category; provider = adapter name; metadata includes capabilities
  and version; lifecycle for outbound resources (connections, clients).
- **Services**: key = service_id; provider = implementation; lifecycle + health.
- **Tasks**: key = task_type; provider = handler; pause/resume/drain hooks; resolver
  selects active handler.
- **Events**: key = event name/type; provider = handler; allow highest-wins by default;
  optional multi-handler pipeline ordered by priority/stack_level.
- **Workflows**: key = workflow_id (+ optional version); provider = definition/engine;
  activation flag; graceful swap (migrate/drain in-flight where possible).

## Lifecycle & Swap

### Standard Lifecycle Contract

```mermaid
stateDiagram-v2
    [*] --> Uninitialized: Registration
    Uninitialized --> Initialized: init()
    Initialized --> Healthy: health() ✓
    Initialized --> Failed: health() ✗
    Healthy --> Running: (run)
    Running --> Paused: pause()
    Paused --> Running: resume()
    Running --> CleaningUp: cleanup()
    Failed --> CleaningUp: cleanup()
    CleaningUp --> [*]: Destroyed

    note right of Healthy
        Component ready for use
        All health checks passing
    end note

    note right of Failed
        Health check failed
        May trigger rollback
    end note
```

### Hot-Swap Flow with Rollback

```mermaid
sequenceDiagram
    participant Watcher as Config/Manifest Watcher
    participant Resolver as Resolver
    participant Lifecycle as Lifecycle Manager
    participant Factory as Component Factory
    participant Health as Health Check
    participant Old as Old Instance
    participant New as New Instance

    Watcher->>Resolver: Config change detected
    Resolver->>Resolver: Resolve target candidate

    Resolver->>Factory: Instantiate new instance
    Factory->>New: Create new component

    New->>Health: Health check
    alt Health check passes
        Health-->>Lifecycle: ✓ Healthy
        Lifecycle->>New: pre_swap_hook()
        New-->>Lifecycle: Hook complete

        Lifecycle->>New: Bind to domain/key
        New-->>Lifecycle: Bound successfully

        Lifecycle->>Old: cleanup_old()
        Old-->>Lifecycle: Cleaned up

        Lifecycle->>New: post_swap_hook()
        New-->>Lifecycle: Swap complete

        Lifecycle-->>Watcher: ✓ Swap succeeded
    else Health check fails
        Health-->>Lifecycle: ✗ Unhealthy
        Lifecycle->>New: Destroy new instance
        Lifecycle-->>Watcher: ✗ Swap failed (kept old)
    end

    Note over Lifecycle: Rollback preserves old instance<br/>unless force=True
```

**Lifecycle Summary:**

- **Standard contract**: init() → health() → (run) → cleanup(); optional pause/resume.
- **Swap flow**: resolve target → instantiate → health check → pre_swap hook → bind →
  cleanup old → post_swap hook; rollback on failure unless force.
- **Config/manifest watcher triggers swap** when mappings change.

## Discovery Sources

```mermaid
graph TB
    subgraph "Discovery Mechanisms"
        Local["Local Package Discovery<br/>register_pkg()"]
        EntryPoint["Entry Points Discovery<br/>enumerate_entry_points()"]
        Remote["Remote Manifest Discovery<br/>fetch_and_verify_manifest()"]
    end

    subgraph "Local Package Flow"
        LP1["Capture caller path"]
        LP2["Map to priority<br/>(STACK_ORDER or heuristics)"]
        LP3["Emit candidates<br/>with source metadata"]
    end

    subgraph "Entry Points Flow"
        EP1["Enumerate entry points<br/>for each domain group"]
        EP2["Load plugin modules"]
        EP3["Register candidates<br/>with provider metadata"]
    end

    subgraph "Remote Manifest Flow"
        RM1["Fetch signed manifest<br/>(uri + sha256 + signature)"]
        RM2["Verify signature<br/>with trusted public keys"]
        RM3["Download wheel/zip<br/>to cache directory"]
        RM4["Install or prepend to sys.path"]
        RM5["Register candidates<br/>with source metadata"]
    end

    Resolver["Resolver Registry"]

    Local --> LP1 --> LP2 --> LP3 --> Resolver
    EntryPoint --> EP1 --> EP2 --> EP3 --> Resolver
    Remote --> RM1 --> RM2 --> RM3 --> RM4 --> RM5 --> Resolver

    style Local fill:#e1f5ff
    style EntryPoint fill:#fff4e1
    style Remote fill:#ffe1f0
    style Resolver fill:#cccccc
```

**Discovery Sources:**

- **Local package**: `register_pkg` captures caller path, maps to priority, emits candidates.
- **Entry points** (or pluggy-style): enumerate entry points for each domain group.
- **Remote manifest**: signed manifest with uri + sha/signature; download wheel/zip to
  cache; install or sys.path prepend; register candidates with source metadata.

## Observability

- Trace spans for discovery/registration/resolve/swap; metrics for swap attempts/
  successes/failures; structured logs include domain/key/provider/source/priority.
- Health/readiness endpoints/polls backed by lifecycle health hooks.

## Configuration

- Typed settings; `settings/*.yaml` (or TOML) for explicit overrides (domain/key →
  provider). Remote manifest location configurable. Stack order configurable via env
  (e.g., `STACK_ORDER=sites,splashstand,fastblocks,oneiric`).

## CLI/Diagnostics

- Commands: list (active/shadowed), why/explain, swap, health, show sources.
- Per-domain tables include priority, stack_level, source, timestamp, decision reason.

## Compatibility Note

- No legacy constraints. Keep existing adapter behavior by wrapping implementations
  with lifecycle/resolver shims; actions utilities remain, with DI/context bindings.

## Integration Guidance (fastblocks, crackerjack, splashstand, session-mgmt-mcp)

- Feasibility: high. Existing adapter modules can be registered as candidates; their
  categories map directly. Services/tasks/events/workflows integrate by defining
  keys and registering providers; override semantics are handled by resolver.

### Migration Steps

```mermaid
graph LR
    Step1["Step 1: Add Stack Priority Map<br/>STACK_ORDER env or config<br/>(sites → splashstand → fastblocks → oneiric)"]
    Step2["Step 2: Register Packages<br/>Use register_pkg()<br/>(no old globals)"]
    Step3["Step 3: Wrap Adapters<br/>Add lifecycle shims<br/>Declare stack_level/provider metadata"]
    Step4["Step 4: Bind Domains<br/>Use bridges for services/tasks/events/workflows<br/>Remove legacy registration"]
    Step5["Step 5: Enable Observability<br/>OTel + logging helpers<br/>Add health hooks"]
    Step6["Step 6: Optional Remote Manifest<br/>Set up remote component delivery"]

    Step1 --> Step2 --> Step3 --> Step4 --> Step5 --> Step6

    style Step1 fill:#e1f5ff
    style Step2 fill:#fff4e1
    style Step3 fill:#f0e1ff
    style Step4 fill:#ffe1f0
    style Step5 fill:#e1ffe1
    style Step6 fill:#ffffe1
```

### Benefits After Migration

```mermaid
mindmap
  root((Oneiric<br/>Benefits))
    Deterministic_Overrides["Deterministic Overrides<br/>Across the stack"]
    Hot_Swap["Hot Swap<br/>Safer rollout<br/>Config-driven changes"]
    Unified_Observability["Unified Observability<br/>OTel tracing<br/>Structured logging<br/>Health reporting"]
    Plugin_Delivery["Plugin/Remote Delivery<br/>Share components<br/>No copy/paste<br/>Ad-hoc components"]
```

**Migration Steps:**

1. Add stack priority map per app (`STACK_ORDER` env or config; e.g., sites →
   splashstand → fastblocks → oneiric).
1. Register packages via new `register_pkg` (no old globals).
1. Wrap adapters with lifecycle shims; declare stack_level/provider metadata.
1. Bind services/tasks/events/workflows through their bridges; remove legacy
   registration paths.
1. Enable OTel/logging helpers; add minimal health hooks.
1. Optionally set up remote manifest for shared/ad-hoc components.

**Strengthening Apps:**

- Deterministic overrides across the stack (sites → splashstand → fastblocks → oneiric).
- Hot swap for safer rollout and config-driven changes.
- Unified observability and health/reporting.
- Plugin/remote delivery to share components across repos without copy/paste.

## Optional Early Adds

- Capability tags and negotiation in resolver (select by capability + priority).
- Middleware/pipeline adapters to compose behavior.
- Retry/backoff + circuit breaker mixins for outbound adapters.
- Workflow versioning + migration helpers; durable execution hook for long-running
  workflows/tasks.
- Rate limiting/backpressure utilities shared across domains.
