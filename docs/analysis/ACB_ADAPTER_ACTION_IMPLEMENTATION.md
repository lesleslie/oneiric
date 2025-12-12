# ACB Adapter & Action Migration Implementation Plan

Purpose: migrate all ACB adapters and action utilities into Oneiric’s unified resolver/lifecycle stack without maintaining any legacy compatibility layers.

## Ground Rules

- **Single home**: adapters, actions, and their settings live in this repository so resolver logic, lifecycle tests, and manifests stay in lockstep.
- **Structlog-first logging**: `core.logging` (structlog + Logly transport) remains the default; extra sinks can be bolted on through structlog processors rather than a legacy logging adapter layer.
- **No legacy contracts**: provider APIs can be reshaped to match Oneiric domains and lifecycle hooks; ACB-only method names don’t need to be preserved.
- **Typed settings & secrets**: each provider/action exposes a Pydantic model backed by `oneiric.core.config` plus `SecretsHook`.
- **Observability parity**: every migrated component emits lifecycle + resolver logs/OTel metrics before it is marked complete.

## Stage Overview

| Stage | Focus | Exit Criteria | Status |
| --- | --- | --- | --- |
| S0 | Inventory & scoping | Catalog adapters/actions, owners, deps, and desired Oneiric domains. | ☑ |
| S1 | Framework alignment | Metadata schema finalized, lifecycle wrapper template validated, logging/observability hooks wired. | ☑ |
| S2 | Adapter migration waves | All adapter categories registered via `adapters.bridge`, configs merged, tests in place. | ☑ |
| S3 | Action migration waves | Action libraries (tasks/events/workflows) ported to domain bridges with resolver-backed selection. | 🔄 |
| S4 | Remote/package delivery | Remote manifest entries and packaging paths cover newly migrated modules. | ☐ |
| S5 | Hardening & sign-off | Integration tests, CLI flows, docs updated; ACB repo marked deprecated for covered features. | ☐ |

(Mark status with ☑ once complete; use 🔄 for in progress.)

## Stage Breakdown & Checklists

### Stage 0 – Inventory & Priorities (Status: ☑)

- [x] Build adapter inventory scaffold (table below) with initial categories, providers, owners, dependencies, and wave assignments.
- [x] Build action inventory scaffold with first tranche of utilities/workflows/tasks and expected target domains.
- [x] Assign migration wave to every priority component (Wave A/B/C); continue tagging new entries as they’re discovered.
- [x] Document blockers (third-party SDK rewrites, missing tests) with owners.

#### Adapter Inventory (initial slice)

| Domain | Category | Providers (ACB) | Owner | Dependencies | Secrets | Target Wave | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| adapter | cache | `redis`, `memory` | Platform Core | `redis-py`, structlog instrumentation | optional (redis password) | Wave A | Redis needs health + cleanup shims; memory can live in demo bundle. |
| adapter | queue/pubsub | `redis_streams`, `nats` | Messaging | `redis-py`, `nats-py`, exponential backoff helpers | optional (nats token) | Wave A | Queue swap hooks must honor pause/drain signals. |
| adapter | http/service | `httpx`, `aiohttp` | Platform Core | `httpx`, retry/backoff mixins, `aiohttp` | no | Wave A | Will back most service/domain bridges; reuse shared telemetry middleware. |
| adapter | storage/blob | `s3`, `gcs`, `azure`, `local` | Data Platform | `boto3`, `google-cloud-storage`, `azure-storage-blob` | YES (per cloud) | Wave B | Secrets supplied via `SecretsHook`; needs provider-specific health. |
| adapter | database/sql | `postgres`, `mysql`, `sqlite` | Data Platform | `asyncpg`, `aiomysql`, `sqlite3` | optional (db creds) | Wave B | Standardize pool lifecycle + migrations. |
| adapter | identity/auth | `auth0`, `cloudflare`, `custom` | Security | `httpx`, jwk cache | YES (API tokens) | Wave B | Align capabilities metadata for scopes. |
| adapter | logging/export | `logly`, `logfire` | Observability | structlog, vendor SDKs | optional | Wave C | Only needed if structlog processors insufficient; treat as optional. |
| adapter | metrics/tracing | `otel`, `prometheus` | Observability | `opentelemetry-sdk`, `prometheus_client` | no | Wave C | Provide Hook for pushing lifecycle metrics externally. |
| adapter | feature flags | `launchdarkly`, `memory` | Edge | vendor SDKs | YES (sdk key) | Wave C | Evaluate if actions domain better fit; keep on hold. |
| adapter | ai/llm | `anthropic`, `openai`, `ollama` | AI/ML | vendor SDKs, `httpx` | YES (api tokens) | Wave C | Need capability tags (`chat`, `embedding`, `rerank`) before resolver tie-in. |
| adapter | email/smtp | `mailgun`, `sendgrid`, `console` | Messaging | vendor SDKs | YES (api keys) | Wave B | Align with secrets hook + backoff/resend policy. |
| adapter | notification/push | `apns`, `fcm`, `webpush` | Messaging | `aioapns`, `pywebpush`, `firebase_admin` | YES | Wave C | Dependent on queue adapter availability; keep behind feature flag. |

#### Action Inventory (initial slice)

| Domain Target | Action Kit | Key Functions | Owner | Dependencies | Target Wave | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| tasks/events | Compression/Encoding | `compress.brotli`, `encode.json`, `hash.blake3` | Platform Core | `brotli`, stdlib, `blake3` | Wave A | Stateless; easiest win to validate resolver-backed action registry. |
| workflows | Automation Utilities | `workflow.notify`, `workflow.retry`, `workflow.audit` | Orchestration | structlog, otel | Wave A | `workflow.audit`, `workflow.notify`, and `workflow.retry` landed in Oneiric. |
| services/tasks | HTTP Convenience | `actions.http.fetch`, `actions.http.retrying_post` | Platform Core | `httpx` | Wave B | Shares deps with adapters; ensure no double config. |
| services | Validation/Security | `actions.security.signature`, `actions.validation.schema` | Security | `cryptography`, `pydantic` | Wave B | Coordinate with secrets hook for key lookup. |
| events | Observability/Debug | `actions.debug.console`, `actions.monitor.emit_metric` | Observability | structlog, otel | Wave C | Evaluate overlap with CLI/structlog default features. |
| tasks/services | Data Processing | `actions.data.transform`, `actions.data.enrich` | Data Platform | `msgspec`, `pydantic` | Wave B | Requires schema registry alignment with resolver metadata. |

#### Known Blockers / Risks (initial)

- **Queue adapters**: require parity test fixtures (redis-streams + nats). Owners: Messaging team. Action: port existing async integration tests to `tests/adapters/test_queue.py`.
- **Storage providers**: S3/GCS/Azure rely on vendor SDK versions pinned in ACB; need compatibility matrix for Python 3.14 + uv. Owners: Data Platform.
- **AI adapters**: vendor SDK licensing and rate limiting may complicate automated tests; track using mocked endpoints first.
- **Notification adapters**: APNS/FCM need device tokens to exercise health checks; plan to stub/contract-test before integration tests.

### Stage 1 – Framework Alignment (Status: ☑)

- [x] Draft provider metadata schema updates (capabilities, version, stack_level, source) – to be codified in `oneiric/adapters/metadata.py`.
- [x] Outline lifecycle wrapper template structure: async `init/health/cleanup/pause/resume`, structlog context bind, shared retry helpers.
- [x] Publish concrete wrapper template (code snippet) via `docs/ADAPTER_LIFECYCLE_TEMPLATE.md`.
- [x] Document structlog processor chain + optional Logly sink integration requirements (see `docs/OBSERVABILITY_GUIDE.md` for details).
- [x] Define action runner contracts per domain (`tasks`, `events`, `workflows`) with lifecycle expectations and health semantics (see notes below).
- [x] Update CLI diagnostics/observability docs (`docs/OBSERVABILITY_GUIDE.md`) to reflect migration inspection commands.

#### Framework Notes

- **Metadata Schema Draft**: `AdapterMetadata` gains `capabilities: list[str]`, `stack_level: int`, `source: Literal["package","entry_point","remote","manual"]`, `owner: str`, `requires_secrets: bool`. Candidates will embed metadata (for CLI/resolver explain output) plus `settings_model` ref for config hydration.
- **Lifecycle Template Skeleton**:
  ```python
  class RedisCacheAdapter(LifecycleAdapter):
      metadata = AdapterMetadata(
          category="cache",
          provider="redis",
          factory="oneiric.adapters.redis.cache:RedisCacheAdapter",
          capabilities=["kv", "ttl"],
          stack_level=50,
          priority=500,
          source=CandidateSource.LOCAL_PKG,
          owner="Platform Core",
          requires_secrets=True,
          settings_model=RedisSettings,
      )

      def __init__(self, settings: RedisSettings, logger: BoundLogger) -> None:
          self._settings = settings
          self._logger = logger.bind(domain="adapter", key="cache", provider="redis")
          self._client: redis.Redis | None = None

      async def init(self) -> None:
          self._client = await create_pool(...)
          self._logger.info("adapter-init", endpoint=self._settings.url)

      async def health(self) -> bool: ...

      async def cleanup(self) -> None:
          if self._client:
              await self._client.close()
  ```
- **Structlog Processors**: standard chain = `[structlog.processors.add_log_level, add_timestamp, structlog.processors.StackInfoRenderer(), structlog.processors.dict_tracebacks, JSONRenderer()]` plus optional Logly exporter; document referencing `docs/OBSERVABILITY_GUIDE.md`.
- **Action Runner Contract Draft**:
  - Action metadata includes `domains: list[str]`, `capabilities: list[str]`, `side_effect_free: bool`, `requires_secrets: bool`.
  - Resolver exposes `resolve_action(domain, key, capability=None)` returning a callable plus lifecycle guard.
  - Tasks/Events/Workflows bridges wrap resolved actions via `ActionHandle` protocol with `prepare()`, `execute(payload)`, `cleanup()` to enable pause/drain compliance.
  - Health semantics: each action kit exports `async def health()`; non-side-effect actions can no-op, while outbound kits (HTTP/email) must perform a lightweight probe with timeout/backoff.

### Stage 2 – Adapter Migration Waves (Status: 🔄)

#### Wave A – Core runtime dependencies (Status: 🔄)

- [ ] Cache adapters (redis/memory)
  - [x] Generate provider metadata + settings registration for the memory cache adapter (see `oneiric/adapters/cache/memory.py`).
  - [x] Implement lifecycle wrappers + structlog context hooks for the memory cache adapter (Redis alignment complete via shared template).
  - [x] Add cache adapter tests (`tests/adapters/test_memory_cache.py`) incl. TTL/capacity coverage; extend to resolver/lifecycle swap tests when Redis lands.
  - [x] Port Redis cache adapter with typed settings, hot-swap lifecycle hooks, metadata registration, client-side caching (coredis TrackingCache) toggles, README docs, and dedicated tests using Fakeredis + patched factories.
- [ ] Queue/pub-sub adapters (redis streams, nats, etc.)
  - [x] Define candidate metadata + settings for Redis Streams (`oneiric/adapters/queue/redis_streams.py`) and NATS (`oneiric/adapters/queue/nats.py`).
  - [x] Implement lifecycle wrappers with pause/drain readiness (init/health/cleanup plus enqueue/publish/read helpers) backed by coredis + nats-py.
  - [x] Add queue unit tests (`tests/adapters/test_redis_streams_queue.py`, `tests/adapters/test_nats_queue.py`) using deterministic in-memory stubs while we line up full redis/nats fixtures for integration coverage.
- [ ] HTTP/service clients
  - [x] Draft httpx adapter + metadata/settings (`oneiric/adapters/http/httpx.py`) plus an aiohttp companion.
  - [x] Register httpx + aiohttp implementations via `register_builtin_adapters`.
  - [x] Add adapter tests (`tests/adapters/test_http_adapter.py`, `tests/adapters/test_aiohttp_adapter.py`) so HTTP selections can pick between the async stacks.

#### Wave B – Data & identity

- [x] Storage/blob adapters
- [x] Local filesystem adapter (`oneiric.adapters.storage.local`) with tests + documentation.
- [x] S3 adapter backed by `aioboto3` including lifecycle hooks, pagination, and delete/list helpers.
- [x] GCS adapter (`oneiric.adapters.storage.gcs`) powered by `google-cloud-storage`; now the preferred cloud storage target.
- [x] Azure Blob adapter (`oneiric.adapters.storage.azure`) powered by `azure-storage-blob` with connection-string or account-url wiring plus resolver metadata/tests so Azure tenants can migrate alongside the GCP-first defaults.
- [x] Database/session adapters
  - [x] Postgres (`asyncpg` pools) with lifecycle-aware init/health/cleanup + stubbed tests.
  - [x] MySQL (`aiomysql`) pools with execute/fetch helpers.
  - [x] SQLite (`aiosqlite`) for local/dev parity.
- [x] Auth/identity providers
  - [x] Auth0 JWT adapter with JWKS caching + structlog context.
- [x] Secret adapters (Infisical/KMS/etc.) — fast-track
  - [x] Baseline env-var secrets adapter (`oneiric/adapters/secrets/env.py`) registered + unit tests.
  - [x] Add SecretsHook/adapter bridge integration tests (`tests/adapters/test_env_secrets.py`) and README docs for env configuration.
  - [x] Add file-backed secrets adapter (`oneiric/adapters/secrets/file.py`) for local dev plus tests/docs.
  - [x] Introduce external provider (Infisical HTTP adapter with caching) with metadata/settings + CLI guidance.
  - [x] Add Google Secret Manager adapter for cloud-native secrets (primary when GCS is selected).
  - [x] Add AWS Secrets Manager adapter (async aioboto3-backed) with caching/tests/docs to close out the multi-cloud requirements.

#### Wave C – Observability & edge utilities (Status: ☑)

- [x] Logging/export adapters (Logfire, Sentry) — prioritized for observability parity
  - [x] Add metadata/settings + lifecycle wrapper for Logfire (`oneiric/adapters/monitoring/logfire.py`) with unit tests.
  - [x] Provide Sentry adapter + lifecycle instrumentation and update docs/tests.
  - [x] Update README with configuration snippets for monitoring adapters.
- [x] Metrics/tracing bridges — delivered via the OTLP adapter (`oneiric/adapters/monitoring/otlp.py`) so traces/metrics reach any collector with resolver-managed lifecycle + tests/docs.
- [x] Misc/edge integrations (feature flags, payment, etc.) — deferred to Stage 3+ after review; tracked separately now that observability parity is complete.

### Vector & Data Science Snapshot (December 2025)

| Adapter | Module | Tests / Docs | Notes |
|---------|--------|--------------|-------|
| Vector (pgvector) | `oneiric.adapters.vector.pgvector.PgvectorAdapter` | `tests/adapters/test_pgvector_adapter.py`, README quick start, `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` | Asyncpg pool factory + pgvector registration helper; ships create/upsert/search/list/delete/count APIs and manifest/CLI coverage. |
| Database (DuckDB) | `oneiric.adapters.database.duckdb.DuckDBDatabaseAdapter` | `tests/adapters/test_duckdb_adapter.py`, `docs/analysis/DUCKDB_ADAPTER.md` | Default in-process analytics adapter with lifecycle hooks, extension loading, and structured logging. |
| Graph (DuckDB PGQ) | `oneiric.adapters.graph.duckdb_pgq.DuckDBPGQAdapter` | `tests/adapters/graph/test_duckdb_pgq_adapter.py`, `docs/analysis/GRAPH_ADAPTERS.md` | Provides ingest/query helpers for PGQ tables; referenced in sample manifests and CLI demos. |
| DNS (Route53) | `oneiric.adapters.dns.route53.Route53DNSAdapter` | `tests/adapters/test_route53_dns_adapter.py` | aioboto3-backed adapter for record CRUD, aligning with the DNS/File Transfer blueprint. |
| File transfer (FTP) | `oneiric.adapters.file_transfer.ftp.FTPFileTransferAdapter` | `tests/adapters/test_ftp_file_transfer_adapter.py`, `docs/examples/LOCAL_CLI_DEMO.md` §10 | aioftp-powered adapter offering upload/download/delete/list helpers with SecretsHook-ready settings. |
| File transfer (SFTP) | `oneiric.adapters.file_transfer.sftp.SFTPFileTransferAdapter` | `tests/adapters/test_sftp_file_transfer_adapter.py` | asyncssh-backed adapter mirroring the FTP API for secure transfers. |
| File transfer (SCP) | `oneiric.adapters.file_transfer.scp.SCPFileTransferAdapter` | `tests/adapters/test_scp_file_transfer_adapter.py`, `docs/sample_remote_manifest.yaml` | asyncssh SCP helper for SSH-based uploads/downloads plus manifest + telemetry docs. |
| File transfer (HTTP download) | `oneiric.adapters.file_transfer.http_artifact.HTTPArtifactAdapter` | `tests/adapters/test_http_artifact_adapter.py` | httpx-based adapter for artifact downloads with optional SHA256 validation. |
| File transfer (HTTPS upload) | `oneiric.adapters.file_transfer.http_upload.HTTPSUploadAdapter` | `tests/adapters/test_https_upload_adapter.py`, `docs/examples/LOCAL_CLI_DEMO.md` §10 | httpx AsyncClient upload helper with auth headers + CLI/demo coverage. |

Remaining Phase 3 backlog (DNS, FileTransfer, optional Wave C messaging adapters) stays tracked in `docs/analysis/ADAPTER_GAP_AUDIT.md`. Update both files whenever new adapters land or downstream repos request additional providers.

For each checkbox above, completion requires:

1. Provider metadata & settings model (`settings.py` per provider or inline).
1. Lifecycle-compliant wrapper with structlog instrumentation.
1. Candidate registration through `adapters.bridge.register`.
1. Unit/lifecycle tests + resolver precedence tests.
1. Documentation snippet (manifest example or README section).

### Stage 3 – Action Migration Waves (Status: ☑)

- [x] Stage 3 kickoff artifacts
  - [x] Publish `docs/STAGE3_ACTION_MIGRATION.md` outlining action-kit waves, owners, and acceptance criteria.
  - [x] Wire resolver metadata scaffolding + CLI support (`ActionMetadata`, `ActionBridge`, `action` domain in the CLI) so kits can register and operators can inspect them like adapters.
  - [x] Deliver the first Wave A kit (`compression.encode`) with builtin metadata, lifecycle-friendly action implementation, CLI exposure, and tests; use it as the migration template for the remaining kits.
- [x] Workflow orchestrators (long-running + versioned) – covered by the `workflow.orchestrate` action kit that compiles versioned definitions into deterministic batches + resolver metadata so the runtime/orchestrator layers can resume runs safely.
- [x] Task runners / cron equivalents – delivered via `task.schedule`, supplying cron/interval planners, queue metadata, and resolver coverage that replaces the ACB scheduler helpers.
- [x] Event dispatchers / hooks – delivered via `event.dispatch`, which emits structured envelopes plus concurrent webhook invocations (with dry-run + timeout controls) so hook routing no longer depends on ACB events.
- [x] Automation utilities (ACB “actions” kits) – delivered via `automation.trigger`, a declarative rule engine that preserves the verb-first naming convention while automating downstream action choices.
- [x] Workflow audit kit (`workflow.audit`) migrated with metadata, resolver wiring, CLI docs, and tests (Wave A)
- [x] Workflow notify kit (`workflow.notify`) migrated with metadata, resolver wiring, CLI docs, and tests (Wave A)
- [x] Workflow retry helper (`workflow.retry`) migrated with resolver metadata + CLI/tests (Wave A)
- [x] Hash kit (`compression.hash`) migrated with stateless hashing helpers, resolver metadata, docs, and tests (Wave A)
- [x] Serialization kit (`serialization.encode`) migrated with JSON/YAML/pickle helpers, resolver metadata, docs/tests, and CLI coverage (Wave A)
- [x] HTTP fetch kit (`http.fetch`) migrated with httpx-backed lifecycle, typed settings, docs/tests, and manifest samples (Wave B)
- [x] Security signature kit (`security.signature`) migrated with HMAC helpers, SecretsHook alignment, docs/tests, and resolver registration (Wave B)
- [x] Secure token/password kit (`security.secure`) migrated with token generation + password hashing/verification helpers (Wave B)
- [x] Data transform kit (`data.transform`) migrated with declarative selector/rename/default logic, docs/tests, and CLI examples (Wave B)
- [x] Data sanitize kit (`data.sanitize`) migrated with mask/drop/allowlist logic, docs/tests, and resolver metadata (Wave B)
- [x] Validation schema kit (`validation.schema`) migrated with field-type enforcement, docs/tests, and resolver metadata (Wave B)
- [x] Debug console kit (`debug.console`) migrated with structlog/echo helpers, scrubbed payloads, docs/tests, and resolver registration (Wave C)
- [ ] Console/debug helpers worth porting (optional; only if additive)

Each action migration step delivers:

1. Resolver-friendly registration via respective domain bridge.
1. Structured logging alignment (structlog context fields).
1. Health/pause/drain hooks implemented.
1. CLI coverage (list/show/trigger) updated.

### Stage 4 – Remote & Packaging (Status: ☑ COMPLETE - See docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md)

- [x] Remote manifest schema extended with migrated adapters/actions metadata (Task 1: ✅ COMPLETE)
  - [x] Update `RemoteManifestEntry` with capabilities, owner, requires_secrets, settings_model fields
  - [x] Add action-specific fields: side_effect_free, timeout_seconds, retry_policy
  - [x] Add dependency/platform constraints: requires, conflicts_with, python_version, os_platform
  - [x] Propagate new metadata to Candidate registration
  - [x] Create enhanced sample manifest v2 with full adapter/action examples
  - [x] Create comprehensive schema documentation (REMOTE_MANIFEST_SCHEMA.md)
- [x] Signed packages stored/uploaded; cache paths validated (Tasks 2-3: ✅ COMPLETE)
  - [x] Implement manifest generation script (scripts/generate_manifest.py)
  - [x] Implement manifest signing script (scripts/sign_manifest.py)
  - [x] Implement artifact upload script (scripts/upload_artifacts.py for S3/GCS)
  - [x] Create CI/CD pipeline (.github/workflows/release.yml)
  - [x] Add comprehensive path traversal prevention tests
  - [x] Add cache boundary enforcement tests
  - [x] Add cache isolation tests
- [x] Watcher tests ensure new modules load over remote sync (Task 4: ✅ COMPLETE)
  - [x] Test remote manifest hot-reload triggers adapter swaps
  - [x] Test remote action registration and resolution
  - [x] Test multi-domain manifest registration
  - [x] Test manifest metadata propagation (all v2 fields)
  - [x] Test cache invalidation on digest mismatch
  - [x] Test signature verification failure handling
  - [x] Test concurrent remote sync safety

**Detailed Plan:** See `docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md` for the complete implementation guide (10 working days / 2 weeks)

### Stage 5 – Hardening & Completion

- [ ] Full CLI demo (`uv run python main.py` and targeted CLI commands) with migrated components.
- [ ] `uv run pytest` with coverage gates met for new providers/actions.
- [ ] Docs updated (README + relevant plans) noting ACB deprecation for migrated areas.
- [ ] Final audit confirming no remaining direct dependencies on ACB runtimes.

## Decision Log

- **Adapters stay in Oneiric**: co-locating adapters avoids split release cycles and keeps resolver/lifecycle behavior deterministic; separate repos would multiply CI + packaging overhead without clear benefits.
- **Integrate ACB → Oneiric (not vice versa)**: Oneiric is the future runtime; migrating features in keeps ACB stable while teams adopt the new platform gradually. No compatibility shims are required.
- **Logging stays simple**: structlog + `core.logging` already provides structured fields, JSON output, and Logly/Loki forwarding. Additional destinations can be expressed as structlog processors instead of a DI-driven logging adapter layer.
- **Reuse ACB debug/console utilities selectively**: port them only if they enhance Oneiric’s CLI experience; otherwise rely on structlog and typer-based diagnostics.

## Why No Dependency Injection Container?

Oneiric relies on deterministic resolver registries and lifecycle managers instead of a general-purpose DI container. Advantages:

- **Deterministic selection**: candidates declare domain, key, provider, priority, and stack level; the resolver can explain why a provider was selected, which is harder with opaque DI wiring.
- **Hot swap support**: lifecycle orchestration (init → health → bind → cleanup) can swap providers at runtime; DI containers typically assume static wiring.
- **Better observability**: registrations, selections, and swaps emit structured events with full metadata; DI usually hides instantiation details.
- **Reduced coupling**: modules register themselves with metadata rather than importing container bindings everywhere; this isolates adapter code from framework plumbing.
- **Async-first lifecycle**: resolver + lifecycle manage async init/health/cleanup which many DI frameworks treat as afterthoughts.

This approach keeps the runtime predictable under dynamic configuration/remote manifests while avoiding the complexity and implicit behavior common in DI frameworks.
