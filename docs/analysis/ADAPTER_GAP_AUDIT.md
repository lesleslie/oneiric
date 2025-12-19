# Adapter Gap Audit – December 2025

**Last Updated:** 2025-12-19

**Purpose:** Track the remaining ACB adapters/actions that still need to be ported to Oneiric so the “single cut-over” strategy stays on schedule. This audit should be refreshed whenever a new adapter lands or a dependency decision changes.

## Summary

| Domain | Provider(s) | Capability | Current Status | Owner | Notes |
|--------|-------------|------------|----------------|-------|-------|
| Vector | `pgvector` | Postgres-native embeddings | ✅ **Shipped** in `oneiric.adapters.vector.pgvector` (Dec 2025) | Data Platform | Asyncpg pool + pgvector extension, inline collection helpers, CLI/tests added. |
| NoSQL | `mongodb` | Document store | ✅ **Shipped** in `oneiric.adapters.nosql.mongodb` (Dec 2025) | Platform Core | Motor-based adapter with CRUD helpers, aggregation support, nosql extras, and unit tests/fakes. |
| NoSQL | `dynamodb` | Key-value / document | ✅ **Shipped** in `oneiric.adapters.nosql.dynamodb` (Dec 2025) | Platform Core | aioboto3-backed adapter with CRUD, scan, conditional writes, optional profile/endpoint support, and fake-driven tests. |
| NoSQL | `firestore` | Document store | ✅ **Shipped** in `oneiric.adapters.nosql.firestore` (Dec 2025) | Platform Core | Async Firestore adapter with set/get/query helpers, credentials/emulator support, manifests/tests updated. |
| Email | `sendgrid` | Outbound email | ✅ **Shipped** in `oneiric.adapters.messaging.sendgrid` (Dec 2025) | Messaging | HTTPX-based implementation with sandbox toggle + metadata. CLI/docs tracked in the messaging plan. |
| Email | `mailgun` | Outbound email | ✅ **Shipped** in `oneiric.adapters.messaging.mailgun` (Dec 2025) | Messaging | HTTPX adapter with sandbox/test-mode toggle, SecretsHook support, CLI + manifest samples. |
| SMS/Voice | `twilio` | Messaging | ✅ **Shipped** in `oneiric.adapters.messaging.twilio` (Dec 2025) | Messaging | REST adapter with dry-run + webhook signature validator; CLI/sample settings documented. |
| Notifications | `slack`, `teams`, `webhooks` | ChatOps | ✅ **Shipped** in `oneiric.adapters.messaging.{slack,teams,webhook}` (Dec 2025) | Platform Core | CLI demos + sample manifests updated; adapters support NotificationMessage + serverless profiles. |
| Scheduler | `cloudtasks`, `pubsub` | DAG triggers | ✅ **Shipped** in `oneiric.adapters.queue.cloudtasks` + `.pubsub` (Dec 2025) | Platform Core | Async-friendly queue adapters powering DAG/event triggers with manifest + CLI coverage. |
| Queue | `kafka`, `rabbitmq` | Streaming queues | ✅ **Shipped** in `oneiric.adapters.queue.kafka` + `.rabbitmq` (Dec 2025) | Platform Core | aiokafka + aio-pika adapters with publish/consume helpers, optional extras, unit tests, and manifest/config updates. |
| Queue | `pulsar` | Streaming queues | ❌ **Pending** | Runtime Team | Evaluate demand before porting. |
| DNS | `cloudflare` | Record management | ✅ **Shipped** in `oneiric.adapters.dns.cloudflare` (Dec 2025) | Platform Core | HTTPX-based adapter with create/update/delete/list helpers, SecretsHook support, tests + manifest snippets forthcoming. |
| DNS | `route53` | Record management | ✅ **Shipped** in `oneiric.adapters.dns.route53` (Dec 2025) | Platform Core | aioboto3-backed adapter with change set helpers and lifecycle coverage. |
| DNS | `gcdns` | Record management | ✅ **Shipped** in `oneiric.adapters.dns.gcdns` (Dec 2025) | Infra | Google Cloud DNS adapter with record CRUD and lifecycle hooks. |
| File transfer | `ftp`, `sftp`, `scp`, `http`, `https-upload` | Artifact sync | ✅ **Shipped** in `oneiric.adapters.file_transfer.{ftp,sftp,scp,http_artifact,http_upload}` (Dec 2025) | Infra | FTP (aioftp), SFTP/SCP (asyncssh), HTTP artifact downloads, and HTTPS upload adapters now ship with manifests/tests + CLI docs. |
| LLM | `gemini` | GenAI | ❌ **Pending** | AI Platform | Blocked on SDK + Python 3.14/httpx 1.x compatibility. |
| Messaging | `apns`, `fcm`, `webpush` | Push notifications | ✅ **Shipped** in `oneiric.adapters.messaging.{apns,fcm,webpush}` (Dec 2025) | Messaging | Mobile + web push adapters with optional SDK extras. |
| Feature flags | `launchdarkly` | Flag evaluation | ❌ **Pending** | Platform Core | Wave C optional; require demand signal. |
| Email fallback | `console` | Dev/test email | ⚠️ Legacy (ACB) | Docs Team | Decide whether to keep (useful for demos) or replace with structured logging recipe. |
| Storage extras | `filesystem.archive` | Package artifacts | ⚠️ On hold | Data Platform | Evaluate after serverless profile if archival storage still needed. |
| Identity | `cloudflare` | Token validation | ⚠️ On hold | Security | Auth0 already ported; Cloudflare only needed if FastBlocks requests it. |

## Actions

1. **Messaging bundle (SendGrid/Mailgun/Twilio):** share HTTP telemetry middleware, provide manifest snippets, and add CLI how-to in `docs/examples/LOCAL_CLI_DEMO.md`. See `docs/archive/implementation/MESSAGING_AND_SCHEDULER_ADAPTER_PLAN.md` for deliverables, owners, and test expectations.
1. **Scheduler bundle (Cloud Tasks + Pub/Sub):** add adapters plus queue fixtures so DAG orchestration (WS-B) can rely on them. Details in the plan above.
1. **Docs:** cross-link this audit from `docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md` §5 so the backlog stays visible.

## Priority Focus (Q1 2026)

| Workstream | Providers | Status | Owner | ETA/Notes |
|------------|-----------|--------|-------|-----------|
| **Graph DB / Feature stores** | Neo4j (✅), ArangoDB (✅), DuckDB PGQ (✅) | ✅ Complete | Data Platform | All graph adapters landed Dec 2025; PGQ adapter documents in `GRAPH_ADAPTERS.md`. |
| **DNS/File transfer** | Cloudflare DNS, Route53, GCDNS, FTP/SFTP/SCP/HTTPS | ✅ Complete | Security/Infra | DNS coverage now includes GCDNS; file transfer adapters shipped with optional guards. |
| **Wave C optional** | Gemini, Pulsar, Feature flags | ❌ Pending | Platform Core | Pending demand + SDK compatibility. |

Status and owners for each bucket should be updated here as soon as a concrete ETA or design note changes.

Update this file as soon as an adapter lands or gets deprioritized. It replaces scattered backlog notes in historical plans and should be referenced in weekly stand-ups.\*\*\*

## Update Checklist

- Verify adapter status entries against `oneiric/adapters/` and `docs/implementation/ADAPTER_PORT_SUMMARY.md`.
- Refresh Wave C backlog owners/ETAs (Gemini, Pulsar, feature flags).
- Re-run `uv run pytest -k "adapter"` if new adapters or optional deps land.
