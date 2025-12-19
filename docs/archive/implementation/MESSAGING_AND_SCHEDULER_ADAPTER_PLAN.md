# Messaging & Scheduler Adapter Delivery Plan

> **Archive Notice (2025-12-19):** Wave 2 delivery complete; retained for historical traceability. See `docs/analysis/ADAPTER_GAP_AUDIT.md` for current backlog status.

**Last Updated:** 2025-12-07
**Owners:** Messaging Squad (SendGrid/Mailgun/Twilio), Platform Core (Cloud Tasks/Pub/Sub), Docs Team (manifests/examples)

This plan breaks down the remaining adapter backlog from `docs/analysis/ADAPTER_GAP_AUDIT.md` and maps each provider to design constraints, dependencies, and test/documentation requirements. It kick-starts the Wave 2 remediation work so the orchestrator parity effort (events, DAGs, supervisors) has the queue and notification bridges it needs.

______________________________________________________________________

## 1. Objectives

1. **Serverless-ready messaging** – Ship SendGrid, Mailgun, and Twilio adapters with SecretsHook integration, rate limiting controls, and dry-run test doubles so they work inside the `serverless` profile.
1. **Scheduler/DAG triggers** – Ship Cloud Tasks and Pub/Sub adapters as queue providers for DAG start events, complete with manifest snippets and CLI demos.
1. **Notification hooks** – Provide Slack/Teams/webhook adapters that let workflows emit ChatOps events without introducing heavy SDKs into the base artifact.
1. **Documentation & samples** – Update examples/manifests/runbooks with Cloud Run specific guidance for the new adapters so Crackerjack/FastBlocks teams can rehearse migrations.

______________________________________________________________________

## 2. Deliverables & Tasks

| Workstream | Deliverables | Tests / Evidence | Notes |
|------------|--------------|------------------|-------|
| **SendGrid Adapter** | `oneiric.adapters.messaging.sendgrid.SendGridAdapter`, metadata registration, SecretsHook usage, dry-run flag | ✅ Unit tests + CLI demo landed (`tests/adapters/test_messaging_sendgrid.py`, `docs/examples/LOCAL_CLI_DEMO.md`) | Guard dependency behind `oneiric[messaging-sendgrid]` extra |
| **Mailgun Adapter** | Similar structure to SendGrid with region-aware endpoints and rate limit options | ✅ HTTPX unit tests + manifest/demo samples | Share base helper in `oneiric/adapters/messaging/common.py`; documented in demo + sample manifests |
| **Twilio Adapter** | SMS/voice adapter using Twilio REST API with secrets + templating, optional `dry_run` | ✅ Signature validation + send tests, CLI demo hooks | Provide manifest snippet for verification callbacks (docs updated) |
| **Cloud Tasks Adapter** | Adapter under `oneiric.adapters.queue.cloudtasks` to enqueue DAG triggers | ✅ Async-friendly unit tests with fake client; CLI/manifest snippets tracked | Provide sample IAM/principal instructions in docs |
| **Pub/Sub Adapter** | Adapter for topic publishing/subscription to start DAGs | ✅ Unit tests exercising publish/pull/ack; manifests reference new provider | Align message envelopes with `msgspec` serialization |
| **Notification Hooks (Slack/Teams/Webhook)** | ✅ Slack/Teams/webhook adapters landed (`oneiric.adapters.messaging.slack`, `.teams`, `.webhook`) with metadata + manifest entries | Tests live in `tests/adapters/test_notifications_adapters.py`, CLI/demo + sample manifests updated with NotificationMessage guidance | Dependencies stay optional (httpx core; Graph-specific extras deferred until requested) |

______________________________________________________________________

## 3. Design Notes & Dependencies

1. **Extras / Packaging**
   - ✅ `messaging-sendgrid`, `messaging-mailgun`, `messaging-twilio`, and `scheduler-gcp` extras now live in `pyproject.toml` (guards for optional installs).
   - Lazy import heavy SDKs; prefer REST APIs via `httpx` to minimize cold-start overhead.
1. **Secrets & Config**
   - All adapters must support the serverless secrets precedence: Secret Manager adapters → env fallback for local dev.
   - Provide Pydantic settings models and manifest snippets showing `settings_model` references.
1. **Rate Limiting & Retries**
   - Reuse `oneiric.core.resiliency` (tenacity profiles, circuit breakers) for API interactions.
   - Expose metadata toggles like `backoff_multiplier`, `max_attempts`, `max_messages_per_second` for Twilio.
1. **Testing Strategy**
   - Unit tests with `pytest-httpx` or stub clients.
   - Optional emulator-based tests (Cloud Tasks, Pub/Sub) guarded with markers.
   - CLI demos recorded in `docs/examples/LOCAL_CLI_DEMO.md` to show serverless profile compatibility.
1. **Documentation**
   - Update `docs/examples/LOCAL_CLI_DEMO.md`, `docs/sample_remote_manifest_v2.yaml`, and `docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md` with references once adapters land.
1. **Timeline**
   - Week 1: SendGrid + Mailgun in review, shared messaging `common.py` landed.
   - Week 2: Twilio + dry-run coverage, Slack/Teams webhook adapters.
   - Week 3: Cloud Tasks + Pub/Sub queue adapters + manifest samples.
   - Week 4: Docs polish, CLI transcripts, parity validation for DAG orchestration.

### Notification Adapter Blueprint (Slack/Teams/Webhooks)

1. **Slack adapter** – POST to `chat.postMessage` with bearer token pulled from Secrets adapter, optional `team` metadata for manifest selection, templating via `str.format` + JSON payload overrides.
1. **Microsoft Teams adapter** – Support both incoming webhook URL (default) and Graph API via client secret (gated behind `oneiric[notifications-teams]` extra). Provide manifest note describing Azure AD app + secret rotation.
1. **Generic webhook** – Minimal adapter that accepts arbitrary HTTP method/headers/body template so repos can target PagerDuty, Discord, etc., without bloating the base artifact.
1. **Testing + docs** – Add `tests/adapters/test_notifications_slack.py` (httpx mock), CLI snippet showing `workflow.notify` hitting Slack/Teams, and manifest samples linking orchestration DAG callbacks to notification adapters. Update serverless profile docs to mention how these adapters behave with secrets precedence.

______________________________________________________________________

## 4. Open Questions

1. Should notification adapters live under `oneiric.adapters.messaging` or a dedicated `notifications/` package? (Default: messaging, revisit if they grow heavy.)
1. Do we need a generic templating layer (e.g., Jinja2) for payload rendering, or can we keep to formatted strings? (Recommendation: start with dataclass → dict conversion + `str.format`).
1. How aggressively should we support retries / DLQs for Cloud Tasks/Pub/Sub from day one? (Proposal: expose manifest toggles, keep defaults minimal.)

______________________________________________________________________

## 5. Links

- `docs/analysis/ADAPTER_GAP_AUDIT.md` – Canonical backlog list (status column should reference this plan).
- `docs/implementation/ADAPTER_REMEDIATION_PLAN.md` – Overall remediation strategy (link this plan from the relevant tracks).
- `docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md` – Serverless execution schedule.
- `docs/examples/LOCAL_CLI_DEMO.md` – Add CLI samples once adapters land.
