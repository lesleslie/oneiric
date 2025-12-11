# NoSQL Adapters (MongoDB, DynamoDB, Firestore)

**Last Updated:** 2025-12-09
**Scope:** Configuration guidance and manifest snippets for the Oneiric NoSQL adapters introduced in the Q1 2026 sprint.

______________________________________________________________________

## 1. Extras & Installation

The NoSQL adapters ship as optional extras so default installs stay lightweight. Install the providers you need:

```bash
# MongoDB (Motor)
pip install 'oneiric[nosql-mongo]'

# DynamoDB (aioboto3)
pip install 'oneiric[nosql-dynamo]'

# Firestore
pip install 'oneiric[nosql-firestore]'

# Meta extra for all NoSQL adapters
pip install 'oneiric[nosql]'
```

Each adapter guards its heavy dependency and raises a descriptive `LifecycleError` if the extra is missing.

______________________________________________________________________

## 2. MongoDB Adapter

**Module:** `oneiric.adapters.nosql.mongodb.MongoDBAdapter`
**Extra:** `oneiric[nosql-mongo]`
**Key settings:** URI or host/port credentials, default collection, TLS toggle, replica set, auth source.

### Sample configuration (`demo_settings.toml`)

```toml
[adapters.selections]
nosql = "mongodb"

[adapters.provider_settings.mongodb]
uri = "mongodb://localhost:27017"
database = "oneiric_demo"
default_collection = "workflow_state"
tls = false
```

### Manifest entry (`docs/sample_remote_manifest.yaml`)

```yaml
- domain: adapter
  key: nosql.primary
  provider: mongodb
  factory: oneiric.adapters.nosql.mongodb:MongoDBAdapter
  metadata:
    description: MongoDB document store for workflow/audit state
    serverless:
      profile: serverless
      remote_refresh_enabled: false
      watchers_enabled: false
```

### CLI smoke test

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
    doc_id = await handle.instance.insert_one({"env": settings.app.environment, "ts": datetime.utcnow().isoformat()})
    print("inserted", doc_id)
    docs = await handle.instance.find(NoSQLQuery(limit=3, sort=[["ts", -1]]))
    for doc in docs:
        print(doc.model_dump())


asyncio.run(main())
PY
```

______________________________________________________________________

## 3. DynamoDB Adapter

**Module:** `oneiric.adapters.nosql.dynamodb.DynamoDBAdapter`
**Extra:** `oneiric[nosql-dynamo]`
**Key settings:** table name, region, optional endpoint URL (LocalStack), AWS creds/profile, consistent reads toggle, primary key field.

### Sample configuration

```toml
[adapters.selections]
nosql = "dynamodb"

[adapters.provider_settings.dynamodb]
table_name = "oneiric-demo-table"
region_name = "us-central1"
endpoint_url = "http://localhost:4566"  # LocalStack
aws_access_key_id = "test"
aws_secret_access_key = "test"
consistent_reads = true
```

### Manifest entry (`docs/sample_remote_manifest_v2.yaml`)

```yaml
- domain: adapter
  key: nosql.primary
  provider: dynamodb
  factory: oneiric.adapters.nosql.dynamodb:DynamoDBAdapter
  metadata:
    description: DynamoDB table for workflow state
    serverless:
      profile: serverless
      remote_refresh_enabled: false
      watchers_enabled: false
```

### CLI smoke test

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
    handle = await bridge.use("nosql")
    await handle.instance.put_item({"id": "demo", "status": "ok"})
    doc = await handle.instance.get_item({"id": "demo"})
    print(doc.model_dump() if doc else None)


asyncio.run(main())
PY
```

______________________________________________________________________

## 4. Firestore Adapter

**Module:** `oneiric.adapters.nosql.firestore.FirestoreAdapter`
**Extra:** `oneiric[nosql-firestore]`
**Key settings:** project ID, collection name, credentials file (optional), emulator host.

### Sample configuration

```toml
[adapters.selections]
nosql = "firestore"

[adapters.provider_settings.firestore]
project_id = "demo-project"
collection = "workflow_state"
credentials_file = "/secrets/service-account.json"
emulator_host = "localhost:8080" # optional, for emulator runs
```

### Manifest entry (`docs/sample_remote_manifest_v2.yaml`)

```yaml
- domain: adapter
  key: nosql.firestore
  provider: firestore
  factory: oneiric.adapters.nosql.firestore:FirestoreAdapter
  metadata:
    description: Firestore collection for workflow state (Cloud Run friendly)
    serverless:
      profile: serverless
      remote_refresh_enabled: false
      watchers_enabled: false
```

### CLI smoke test

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
    handle = await bridge.use("nosql")
    await handle.instance.set_document("demo", {"status": "ok"}, merge=True)
    docs = await handle.instance.query_documents(filters=[("status", "==", "ok")], limit=5)
    for doc in docs:
        print(doc.model_dump())


asyncio.run(main())
PY
```

______________________________________________________________________

## 5. Best Practices

1. **Secrets:** Prefer Secret Manager adapters for credentials (Mongo URI, AWS keys) and use inline config only for dev.
1. **Serverless deployments:** Package manifests with the desired NoSQL adapter and disable remote polling to avoid cold-start penalties.
1. **Testing:** Use fakes (Mongo) or local emulators (LocalStack/DynamoDB Local) so CI can exercise adapters without real cloud resources.
1. **Logging:** Adapters emit structured spans (`adapter.nosql.*`) for CRUD operations; scrape them in Cloud Logging / Loki for auditing.

Keep this file synchronized with future NoSQL additions (Firestore, Cassandra, etc.) so operators have a single source of truth for configuration.
