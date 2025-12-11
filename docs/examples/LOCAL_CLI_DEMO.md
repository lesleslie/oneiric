# Local CLI Demo

This runnable example shows how to combine the CLI, remote manifest loader, and the new logging/resiliency knobs.

## 1. Copy the sample settings

```bash
cp docs/examples/demo_settings.toml ~/.oneiric.toml
```

Update the file if you want to change cache directories or logging sinks. The sample configuration enables structured logs (stdout + rotating file), remote retries, and circuit breaker protection, and it points at `docs/sample_remote_manifest.yaml` so you can run everything offline.
It also enables `[plugins] auto_load = true` so any installed entry-point plugins (`oneiric.adapters`, etc.) are registered before the demo metadata.

## 2. Run the orchestrator with the sample settings

```bash
ONEIRIC_CONFIG=~/.oneiric.toml \
uv run python -m oneiric.cli orchestrate --refresh-interval 60 --demo
```

This command boots the runtime orchestrator, registers demo providers, and refreshes the bundled manifest every minute. Watch the log output for `remote-sync-complete` and `remote-refresh-circuit-open` events to verify retry/circuit-breaker behavior.

## 3. Inspect runtime health and activity

In a second shell, run the CLI against the same config to view health snapshots and activity state:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli status --domain adapter
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli health --probe --json
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli activity --json
```

Persisted telemetry lives under the cache directory configured in the sample file; open `.oneiric_cache/demo.log` to review the JSON log stream with trace context.

Tip: to simulate the serverless profile and the Service Supervisor loop that enforces pause/drain state in Cloud Run, start the orchestrator with `uv run python -m oneiric.cli orchestrate --profile serverless --no-remote --health-path /tmp/runtime_health.json` and then re-run the `health --probe`/`activity --json` commands above. The CLI output will reflect the same `runtime_health.json` snapshot and supervisor decisions that Cloud Run uses for readiness checks, and you’ll see the new `Profile:` + `Secrets:` status blocks showing which toggles and secret providers are active.

## 4. SendGrid messaging adapter smoke test

The demo settings now select the SendGrid adapter (`[adapters.selections] messaging = "sendgrid"`).
Populate the provider settings before running this step:

```toml
[adapters.provider_settings.sendgrid]
api_key = "replace-me"              # Or load from Secret Manager
from_email = "noreply@example.com"
from_name = "Oneiric Demo"
sandbox_mode = true                  # Keeps calls in SendGrid's sandbox
```

1. Export your API key (the sandbox mode means no real email leaves SendGrid, but real keys are still required):

   ```bash
   export SENDGRID_API_KEY="sg.your-key-here"
   ```

   Update `docs/examples/demo_settings.toml` (or your own config) with the same key or a Secret Manager reference.

1. Verify the adapter is registered:

   ```bash
   ONEIRIC_CONFIG=~/.oneiric.toml \
   uv run python -m oneiric.cli list --domain adapter --shadowed | grep messaging
   ```

1. Send a sandboxed test message using the adapter bridge:

   ```bash
   ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
   import asyncio

   from oneiric.adapters import AdapterBridge, register_builtin_adapters
   from oneiric.adapters.messaging.common import EmailRecipient, OutboundEmailMessage
   from oneiric.core.config import load_settings
   from oneiric.core.lifecycle import LifecycleManager
   from oneiric.core.resolution import Resolver


   async def main() -> None:
       settings = load_settings()
       resolver = Resolver()
       register_builtin_adapters(resolver)
       lifecycle = LifecycleManager(resolver)
       bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
       handle = await bridge.use("messaging")
       result = await handle.instance.send_email(
           OutboundEmailMessage(
               to=[EmailRecipient(email="you@example.com", name="Demo Recipient")],
               subject="Oneiric SendGrid sandbox ping",
               text_body="Sent from the Oneiric demo runner with sandbox_mode=true",
           )
       )
       print(result.model_dump())


   asyncio.run(main())
   PY
   ```

You should see a JSON payload containing the SendGrid `X-Message-Id`. Disable `sandbox_mode` when you are ready to send real traffic.

## 5. Mailgun adapter quick start

The demo settings include a Mailgun block (`[adapters.provider_settings.mailgun]`). Point it at your sandbox domain and flip the adapter selection when you want to test Mailgun instead of SendGrid:

```toml
[adapters.selections]
messaging = "mailgun"
```

Then run the same CLI snippet from step 4. The adapter will use test mode unless you override `sandbox_override` per message. The structured log stream will include `mailgun-send` entries showing the Mailgun message ID returned by the API.

## 6. Twilio SMS adapter dry-run

Twilio configuration is also pre-populated in `demo_settings.toml`. Keep `dry_run = true` while rehearsing locally:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.adapters.messaging.common import OutboundSMSMessage, SMSRecipient
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("messaging")
    result = await handle.instance.send_sms(
        OutboundSMSMessage(
            to=SMSRecipient(phone_number="+15557654321"),
            body="Oneiric Twilio dry-run",
        )
    )
    print(result.model_dump())


asyncio.run(main())
PY
```

Switch `dry_run` off when deploying to Cloud Run and provide the production `account_sid`/`auth_token` via Secret Manager. The adapter exposes `TwilioSignatureValidator` for webhook validation; wire it into your FastAPI/Starlette endpoints when registering callback URLs.

## 7. MongoDB NoSQL adapter (local dev)

Install the optional extra (`pip install 'oneiric[nosql-mongo]'`) and run a local MongoDB instance (Docker: `docker run -p 27017:27017 mongo:7`). The demo settings now select the Mongo adapter (`nosql = "mongodb"`) and point at `mongodb://localhost:27017`.

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio
from datetime import datetime

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.adapters.nosql.common import NoSQLQuery
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("nosql")
    doc_id = await handle.instance.insert_one(
        {
            "env": settings.app.environment,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "demo",
        }
    )
    print("inserted-id:", doc_id)
    documents = await handle.instance.find(
        NoSQLQuery(filters={"status": "demo"}, limit=5, sort=[("timestamp", -1)])
    )
    for doc in documents:
        print(doc.model_dump())


asyncio.run(main())
PY
```

You should see the inserted ID along with the most recent documents returned from MongoDB. Update the provider settings in `demo_settings.toml` (or via Secret Manager) when targeting Atlas/Cloud Run deployments.

### DynamoDB variant (LocalStack/AWS)

To rehearse DynamoDB instead, switch the selection and reuse the adapter bridge snippet:

```toml
[adapters.selections]
nosql = "dynamodb"
```

The sample settings already include a LocalStack-friendly block under `[adapters.provider_settings.dynamodb]`. Start LocalStack (`localstack start`) and run the same CLI snippet—the adapter will talk to `endpoint_url = "http://localhost:4566"` with the provided test credentials. For AWS deployments, remove the endpoint override, set `profile_name` or populate credentials via Secret Manager, and update your manifest entry to point at the DynamoDB provider.

## 8. Neo4j graph adapter (knowledge graph workflows)

Install the optional extra and start a local Neo4j container:

```bash
pip install 'oneiric[graph-neo4j]'
docker run --rm -p 7687:7687 -e NEO4J_AUTH=neo4j/test neo4j:5
```

`docs/examples/demo_settings.toml` now selects the Neo4j adapter (`graph = "neo4j"`) and includes a provider block matching the container credentials. The bridge helper mirrors the usage documented in `docs/analysis/GRAPH_ADAPTERS.md`:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("graph")

    node = await handle.instance.create_node(["Demo"], {"name": "cli"})
    print("node:", node)

    rels = await handle.instance.query("MATCH (n:Demo) RETURN n LIMIT 5;")
    print("rows:", rels)


asyncio.run(main())
PY
```

The adapter performs a health check on initialization, so failures surface before any writes occur. Update the provider settings when pointing at Aura/Enterprise clusters and guard secrets via Secret Manager.

To try ArangoDB instead, install `pip install 'oneiric[graph-arangodb]'`, start `arangodb:3.11` locally, update `[adapters.selections] graph = "arangodb"`, and reuse the same bridge snippet (swap `create_node` for `create_vertex` and `query` for `query_aql`)—the adapter keeps the synchronous python-arango driver off the event loop via `asyncio.to_thread`.

For in-process analytics, switch to DuckDB PGQ: `pip install 'oneiric[graph-duckdb-pgq]'`, keep `[adapters.selections] graph = "duckdb_pgq"`, and reuse the bridge snippet above with the methods `ingest_edges`/`neighbors`/`query`. The sample settings already include a DuckDB configuration that stores `.oneiric_cache/graphs.duckdb`; delete the file between runs if you want a clean slate.

### Firestore variant (GCP/emulator)

Switch the selection to Firestore when exercising Google Cloud deployments:

```toml
[adapters.selections]
nosql = "firestore"
```

If you are running the Firestore emulator locally (`gcloud emulators firestore start --host-port localhost:8080`), populate `[adapters.provider_settings.firestore]` with `emulator_host = "localhost:8080"`. When deploying to Cloud Run, drop the emulator host and provide a service-account JSON path (or rely on ADC). The Mongo snippet from above doubles as a Firestore smoke test—`set_document`/`query_documents` share the same shape.

## 9. Cloud Tasks + Pub/Sub queue adapters

Cloud Run DAG triggers rely on queue adapters, and the demo config now populates both Cloud Tasks and Pub/Sub provider settings. You can enqueue a workflow run directly from the CLI (this calls the configured queue adapter via the workflow bridge):

```bash
uv run python -m oneiric.cli --demo workflow enqueue demo-workflow --json
```

The demo workflow ships with `metadata.scheduler` so the bridge knows to use the queue adapter (`queue` category / `cli` provider) even when you do not supply `--queue-category` or `--provider` flags. Remote manifests mirror this pattern by pointing workloads at `queue.scheduler` (Cloud Tasks) or other queue categories per workflow.

You can also control the fallback queue via config: set `[workflows.options] queue_category = "queue.scheduler"` (as shown in `docs/examples/demo_settings.toml`) so `RuntimeOrchestrator` routes enqueue calls through the Cloud Tasks adapter when workflow metadata does not provide an override.

Here is a lower-level smoke test that shows how to use the adapter bridge directly to enqueue a DAG trigger into Cloud Tasks:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("queue", provider="cloudtasks")
    task_name = await handle.instance.enqueue({"dag": "demo", "event": "start"})
    print(task_name)


asyncio.run(main())
PY
```

Swap `provider="pubsub"` to publish a DAG start event into Pub/Sub (the adapter supports `read` + `ack` when a subscription is configured). In Cloud Run, point `http_target_url` at your orchestrator ingress and ensure the service account listed in the settings has the `Cloud Tasks Enqueuer` role.

## 10. Streaming queues (Kafka + RabbitMQ)

Install the `queue-streaming` extra (`pip install 'oneiric[queue-streaming]'`) and run local brokers (e.g., Redpanda/Confluent for Kafka, the official RabbitMQ Docker image for AMQP). Select the provider via the settings:

```toml
[adapters.selections]
queue = "kafka"      # or "rabbitmq"
```

Then use the queue bridge to publish/consume test messages:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("queue")
    if handle.provider == "kafka":
        await handle.instance.publish(b"stream-demo", key=b"demo")
        print(await handle.instance.consume())
    else:
        await handle.instance.publish(b"stream-demo")
        messages = await handle.instance.consume()
        print(messages)
        for message in messages:
            await handle.instance.ack(message["message"])


asyncio.run(main())
PY
```

Update the manifest entries (`queue.kafka`, `queue.rabbitmq`) when deploying so other orchestrations can request the desired streaming provider.

## 11. Slack + Teams notifications

Slack and Teams are now first-class messaging adapters. Once you populate `demo_settings.toml` with the appropriate credentials/webhook URLs, you can target either platform by selecting the provider via `adapters.selections`:

```toml
[adapters.selections]
notifications = "slack"    # or "teams" / "webhook"
```

Then run a quick bridge script to emit a message:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.adapters.messaging.common import NotificationMessage
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("messaging", provider=settings.adapters.selections.get("notifications", "slack"))
    result = await handle.instance.send_notification(
        NotificationMessage(
            target="#platform-alerts",
            title="Demo deploy",
            text="The sandbox deploy finished successfully.",
        )
    )
    print(result.model_dump())


asyncio.run(main())
PY
```

For Teams, set `target` to a webhook URL override or leave unset to use the default configured in the settings file. For Slack, `target` is treated as the channel; omit it to fall back to `default_channel`.

## 12. Generic webhook adapter

Need to call PagerDuty, Discord, or a bespoke webhook? Configure `[adapters.provider_settings.webhook]` with the default URL and headers, then select `notifications = "webhook"` in the settings file. The same script used above works, and you can override HTTP details per message via `NotificationMessage.extra_payload`, for example:

```python
NotificationMessage(
    text="custom payload",
    extra_payload={
        "method": "put",
        "headers": {"X-Debug": "1"},
        "body": {"status": "ok", "message": "Deploy complete"},
    },
)
```

This adapter keeps the orchestrator lean while still covering ad-hoc integrations during the migration away from ACB.

## 13. Workflow notify → Slack/Teams bridge

Workflows often emit structured notifications via the builtin `workflow.notify` action. The new ChatOps adapters can consume that payload by translating it into `NotificationMessage`. Here’s a tiny harness that logs the notification (via the action) and forwards it to Slack:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.actions.workflow import WorkflowNotifyAction
from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.adapters.messaging.common import NotificationMessage
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)

    notify = WorkflowNotifyAction()
    record = await notify.execute({
        "message": "Deploy complete",
        "channel": "deploy",
        "level": "info",
        "context": {"service": "demo", "revision": "2025-12-09"},
    })

    slack = await bridge.use("messaging", provider="slack")
    await slack.instance.send_notification(
        NotificationMessage(
            target="#platform-alerts",
            title=f"[{record['level'].upper()}] {record['channel']}",
            text=record["message"],
            extra_payload={"blocks": []},
        )
    )


asyncio.run(main())
PY
```

Swap `provider="teams"` or `"webhook"` to forward the same notification elsewhere. The orchestration parity plan assumes this pattern when wiring DAG/service supervisors to surface events without relying on legacy ACB integrations.

## 14. Vector adapters (Pinecone + Qdrant)

Keep the vector SDKs optional by installing the extras you need:

```bash
pip install 'oneiric[vector-pinecone]'      # Managed Pinecone clusters
pip install 'oneiric[vector-qdrant]'        # Local or hosted Qdrant
pip install 'oneiric[vector]'               # Installs both extras
```

`demo_settings.toml` now ships with `[adapters.provider_settings.pinecone]` and `[adapters.provider_settings.qdrant]` blocks. Uncomment the selection you want to test:

```toml
[adapters.selections]
vector = "pinecone"   # Or "qdrant"
```

Smoke-test the adapter by upserting and querying a handful of documents:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.adapters.vector import VectorDocument
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("vector")

    docs = [
        VectorDocument(
            id=f"demo-{i}",
            vector=[float(i)] * handle.settings.default_dimension,
            metadata={"label": f"sample-{i}"},
        )
        for i in range(3)
    ]
    await handle.instance.upsert("demo-collection", docs)
    results = await handle.instance.search(
        "demo-collection",
        query_vector=[1.0] * handle.settings.default_dimension,
        limit=2,
    )
    for row in results:
        print(row.id, row.score)


asyncio.run(main())
PY
```

The Pinecone adapter auto-creates the index if needed; the Qdrant adapter assumes a local docker container (`docker run -p 6333:6333 qdrant/qdrant`) or a managed endpoint reachable from your machine.

## 15. Embedding adapters (OpenAI + local notes)

Install the extra for hosted OpenAI embeddings (or the aliases that bundle LLM stacks):

```bash
pip install 'oneiric[embedding-openai]'   # Hosted OpenAI embeddings
pip install 'oneiric[embedding]'          # Alias for the hosted embedding stack
pip install 'oneiric[ai]'                 # Embedding + LLM extras
```

> **Local adapters:** Sentence Transformers + ONNX wheels are not yet published for Python 3.14 on macOS x86_64, so their extras stay disabled. Follow `ONNX_GUIDE.md` (uses `uvx --python 3.13 --with onnxruntime ...`) if you need those adapters in a side environment until upstream wheels land.

Populate the relevant provider settings in `demo_settings.toml` (OpenAI shares the `[adapters.provider_settings.openai]` block with the LLM adapter; Sentence Transformers/ONNX have settings blocks ready for future support), then select a provider:

```toml
[adapters.selections]
embedding = "openai"
```

Run a quick embedding batch end to end:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main() -> None:
    texts = [
        "Oneiric orchestrates AI-first workloads.",
        "Vector databases enable semantic search.",
    ]
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("embedding")
    batch = await handle.instance.embed_texts(texts)
    for result in batch.results:
        print(result.text[:40], "→", len(result.embedding), "dims")


asyncio.run(main())
PY
```

Switch the selection to `"sentence_transformers"` or `"onnx"` to keep everything local. Sentence Transformers downloads models into `.oneiric_cache/sentence-transformers`, while the ONNX adapter expects a converted model at the path referenced in the sample settings file.

## 16. Dispatch manifest-driven events

Remote manifests can register event handlers with `event_topics` metadata. After bundling the sample manifest, emit an event using the CLI helper:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli event emit demo.user.created \
    --payload '{"user_id":"cli"}' --json
```

The handler declared in `docs/sample_remote_manifest*.yaml` listens to `demo.user.created` and logs the payload. The CLI prints a per-handler summary (or emits JSON when `--json` is provided) that now includes duration and attempt counts so you can see when dispatcher retries occur. Use the new manifest fields to refine routing: `event_filters` let you match on `payload.*` or `headers.*`, `event_priority` controls the ordering of handlers, and `event_fanout_policy="exclusive"` ensures only the highest priority handler runs when a manifest needs active/passive style fan-out.

## 17. Execute manifest-defined DAG workflows

Workflow entries can include a `dag` specification pointing at task domain keys. Use the CLI helper to execute the DAG declared in the sample manifest:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli workflow run remote-workflow \
    --context '{"user_id":"cli"}' --json
```

Each DAG node references a task key (e.g., `remote-task`). The workflow bridge uses the task bridge to activate task implementations and run them in topological order, returning per-node results.

Workflow checkpoints automatically persist to the SQLite file referenced under `[runtime_paths]` in `docs/examples/demo_settings.toml` (defaults to `.oneiric_cache/workflow_checkpoints.sqlite`). Override it via the same settings block or pass `--workflow-checkpoints PATH` / `--no-workflow-checkpoints` to `oneiric.cli orchestrate` when running long-lived deployments.
