______________________________________________________________________

## status: active role: canonical date: 2026-05-10 last_reviewed: 2026-07-17 superseded_by: null blocks_on: [] topic: lifecycle

# Oneiric CLI Reference

**Last Updated:** 2025-02-02
**Version:** 0.21.1

Complete reference for all Oneiric CLI commands with examples, use cases, and troubleshooting tips.

______________________________________________________________________

## Table of Contents

1. [Installation & Setup](#installation--setup)
1. [Global Options](#global-options)
1. [Domain Commands](#domain-commands)
1. [Resolution Commands](#resolution-commands)
1. [Lifecycle Commands](#lifecycle-commands)
   - [Process Management](#process-management)
1. [Orchestration Commands](#orchestration-commands)
1. [Event & Workflow Commands](#event--workflow-commands)
1. [Remote Manifest Commands](#remote-manifest-commands)
   - [Manifest Commands](#manifest-commands)
1. [Observability Commands](#observability-commands)
1. [Plugin & Secrets Commands](#plugin--secrets-commands)
1. [Common Patterns](#common-patterns)
1. [Troubleshooting](#troubleshooting)

______________________________________________________________________

## Installation & Setup

### Shell Completions

Install shell completions for bash/zsh/fish:

```bash
# Install completions
uv run oneiric --install-completion

# Restart shell or source
source ~/.bashrc  # or ~/.zshrc
```

### Configuration

```bash
# Set config file location
export ONEIRIC_CONFIG=/path/to/config.toml

# Default locations (checked in order):
# 1. $ONEIRIC_CONFIG / --config
# 2. env overrides (ONEIRIC_* / PROJECT_*)
# 3. ./settings/<project>.yaml or .yml
# 4. ./settings/local.yaml
# 5. ~/.config/<project>/config.yaml
# 6. ~/.config/<project>/local.yaml
```

### Demo Mode

Most commands support `--demo` flag to use built-in demo providers:

```bash
# Use demo adapters/services/tasks
uv run oneiric --demo list --domain adapter
```

______________________________________________________________________

## Global Options

| Option | Description | Example |
|--------|-------------|---------|
| `--demo` | Use built-in demo providers | `--demo list --domain adapter` |
| `--config PATH` | Specify config file | `--config /path/to/config.toml status` |
| `--suppress-events` | Filter out event log output | `--suppress-events list --domain adapter` |
| `--json` | Output JSON instead of tables | `list --domain adapter --json` |
| `--help` | Show command help | `swap --help` |

______________________________________________________________________

## Domain Commands

### `list`

List all registered components for a domain.

```bash
# List all adapters
oneiric list --domain adapter

# List services
oneiric list --domain service

# Include shadowed (inactive) candidates
oneiric list --domain adapter --shadowed

# JSON output for scripts
oneiric list --domain adapter --json

# Filter by key
oneiric list --domain adapter --key cache
```

**Output Example:**

```
Domain: adapter
Key            Provider    Stack Level  Priority  Source
cache          redis       10           10        builtin
cache          memcached   5            5         builtin
queue          cloudtasks  10           10        builtin
messaging      sendgrid    10           10        builtin
```

**Use Cases:**

- Discover available adapters/services
- Verify provider registration
- Check shadowed candidates
- Audit configuration

### `status`

Show status of a specific component.

```bash
# Show adapter status
oneiric status --domain adapter --key cache

# Show service status
oneiric status --domain service --key payment-processor

# JSON output
oneiric status --domain adapter --key cache --json

# Include lifecycle state
oneiric status --domain adapter --key cache --shadowed
```

**Output Example (JSON):**

```json
{
  "domain": "adapter",
  "key": "cache",
  "provider": "redis",
  "state": "ready",
  "activated_at": "2025-02-02T10:30:00Z",
  "metadata": {
    "stack_level": 10,
    "priority": 10,
    "version": "1.0.0"
  }
}
```

**Use Cases:**

- Check if component is active
- Verify configuration
- Debug resolution issues
- Health checks

### `explain`

Explain why a component was selected.

```bash
# Explain adapter selection
oneiric explain --domain adapter --key cache

# Explain service selection
oneiric explain --domain service --key status

# Show all candidates with reasons
oneiric explain --domain adapter --key cache

# JSON output
oneiric explain --domain adapter --key cache --json
```

**Output Example:**

```
Resolution for adapter:cache
Selected: redis (score: 100)

Reasoning:
  ✓ Explicit config: adapters.yml selections.cache = "redis"
  ✓ Stack level: 10 (higher than memcached: 5)
  ✓ Priority: 10 (from ONEIRIC_STACK_ORDER)

Shadowed candidates:
  - memcached (score: 45)
    Reason: Lower stack level (5 < 10)
  - memory (score: 20)
    Reason: Lower priority and no config override
```

**Use Cases:**

- Understand resolution logic
- Debug unexpected provider selection
- Verify configuration precedence
- Document decisions

______________________________________________________________________

## Resolution Commands

### `swap`

Hot-swap to a different provider.

```bash
# Swap cache from Redis to Memcached
oneiric swap --domain adapter --key cache --provider memcached

# Force swap (skip health check)
oneiric swap --domain adapter --key cache --provider memcached --force

# Swap service
oneiric swap --domain service --key payment-processor --provider stripe
```

**What Happens:**

1. Resolve new provider
1. Instantiate new instance
1. Run health check
1. If healthy: bind, cleanup old, complete
1. If unhealthy: rollback (unless `--force`)

**Use Cases:**

- Update provider without restart
- A/B test different implementations
- Emergency provider switch
- Blue-green deployments

______________________________________________________________________

## Lifecycle Commands

### `version`

Print the installed Oneiric version and exit with `ExitCode.SUCCESS`.

```bash
oneiric version
# oneiric: 0.21.1

oneiric version --json  # (inherits the global --json flag from the root callback)
```

The older `--version`/`-V` Typer flags still work but emit a
`DeprecationWarning` directing callers to `oneiric version`.

### `doctor`

Run diagnostic checks against the component's runtime and report pass/fail
status per check.

| Option | Description |
|--------|-------------|
| `--json` | Emit checks as a JSON object (`{"checks": {name: {status, detail}}}`). |

```bash
oneiric doctor

oneiric doctor --json
```

When the subclass hook raises `NotImplementedError`, `doctor` exits with
`ExitCode.UNAVAILABLE` (3). When it raises any other exception, the
command exits with `ExitCode.ERROR` (1).

### `health`

Check health of components or entire system.

```bash
# Probe all components
oneiric health --probe

# Probe specific domain
oneiric health --domain adapter --key cache

# JSON output for monitoring
oneiric health --probe --json

# Continuous monitoring (watch mode)
oneiric health --probe --json
```

**Output Example:**

```
Component Health Status:
✓ adapter:cache (redis) - healthy (2.3ms)
✓ adapter:queue (cloudtasks) - healthy (145ms)
✗ adapter:messaging (sendgrid) - unhealthy (connection timeout)
✓ service:status - healthy (0.5ms)

Overall: 3/4 healthy
```

**Use Cases:**

- Pre-deployment health checks
- Monitoring dashboards
- Incident response
- Smoke tests

### `pause`

Pause a component (stops accepting new work).

```bash
# Pause component
oneiric pause --domain service --key email-sender --note "Maintenance window"

# Pause multiple components
oneiric pause --domain service --key payment-processor
oneiric pause --domain adapter --key queue

# Resume paused component
oneiric pause --resume --domain service --key email-sender
```

**Use Cases:**

- Maintenance windows
- Graceful degradation
- Testing without impact
- Emergency isolation

### `drain`

Drain a component (finish existing work, stop new work).

```bash
# Drain component
oneiric drain --domain service --key worker --note "Deploying new version"

# Resume drained component
oneiric drain --resume --domain service --key worker
```

**Difference from Pause:**

- **Pause:** Immediate stop
- **Drain:** Finish in-flight work, then stop

**Use Cases:**

- Zero-downtime deployments
- Graceful shutdowns
- Queue draining

### `activity`

Show pause/drain activity state.

```bash
# Show all activity
oneiric activity

# Show specific domain
oneiric activity --domain service

# JSON output
oneiric activity --json
```

**Output Example:**

```json
{
  "domains": {
    "adapter": {
      "counts": {"paused": 1, "draining": 0, "note_only": 2},
      "entries": [
        {"key": "queue", "paused": true, "draining": false, "note": "Maintenance"}
      ]
    },
    "service": {
      "counts": {"paused": 0, "draining": 1, "note_only": 0},
      "entries": [
        {"key": "worker", "paused": false, "draining": true, "note": "Deploying"}
      ]
    }
  },
  "totals": {"paused": 1, "draining": 1, "note_only": 2}
}
```

**Use Cases:**

- Check system state before changes
- Verify maintenance mode
- Dashboard data source
- Audit trail

### `supervisor-info`

Show Service Supervisor status and configuration.

```bash
# Show supervisor status
oneiric supervisor-info

# Check if enabled
oneiric supervisor-info --json

# Use with specific config
ONEIRIC_CONFIG=/path/to/config.toml oneiric supervisor-info
```

**Output Example:**

```
Service Supervisor Status:
Enabled: Yes (via config)

Configuration:
  Loop Interval: 30s
  Activity Store: .oneiric_cache/domain_activity.sqlite
  Health Snapshot: .oneiric_cache/runtime_health.json

Active State:
  adapter:queue - paused (Maintenance)
  service:worker - draining (Deploying)

Profile: serverless
  Watchers: Disabled
  Remote: Disabled
  Secrets: adapter:secrets
```

**Use Cases:**

- Verify supervisor is running
- Debug pause/drain behavior
- Validate serverless profile
- Pre-deployment checks

### `load-test`

Run an in-process load test against the resolver/lifecycle pipeline and
report latency statistics.

| Option | Description | Default |
|--------|-------------|---------|
| `--total`, `-t` | Total tasks to execute. | `1000` |
| `--concurrency`, `-c` | Maximum concurrent tasks. | `50` |
| `--warmup` | Warmup tasks to run before measuring. | `0` |
| `--sleep-ms` | Sleep duration per task (ms). | `0.0` |
| `--payload-bytes` | Payload bytes hashed per task. | `0` |
| `--timeout` | Cancel the run after this many seconds. | None |
| `--json` | Emit the result as JSON. | `False` |

```bash
oneiric load-test

oneiric load-test --total 5000 --concurrency 200 --json
```

### `shell`

Start an interactive IPython admin shell pre-loaded with the active
configuration layer, settings validator, and lifecycle query helpers.
Session tracking is routed through Session-Buddy MCP.

```bash
oneiric shell
# Oneiric> show_layers()           # Show config layer precedence
# Oneiric> validate_config()       # Validate current configuration
# Oneiric> reload_settings()       # Reload from all layers
```

The shell does not accept any flags.

### Process Management

The `start` / `stop` / `process-status` commands wrap the long-running
`orchestrate` process behind a PID file so it can run in the background.
The PID file defaults to
`<cache_dir>/orchestrator.pid` (`<cache_dir>` comes from the active
settings layer; `~/.oneiric_cache/orchestrator.pid` by default).

#### `start`

Spawn the orchestrator in the background.

| Option | Description |
|--------|-------------|
| `--config PATH` | Path to settings file. |
| `--profile NAME` | Runtime profile (`default`, `serverless`). |
| `--manifest URI` | Override manifest URL/path. |
| `--refresh-interval SECONDS` | Override remote refresh interval. |
| `--no-remote` | Disable remote sync/refresh. |
| `--workflow-checkpoints PATH` | Workflow checkpoint SQLite store (defaults to cache dir). |
| `--no-workflow-checkpoints` | Disable workflow DAG checkpoint persistence. |
| `--http-port PORT` | Run the builtin scheduler HTTP server on this port. |
| `--http-host HOST` | Interface for the scheduler HTTP server (`0.0.0.0` default). |
| `--no-http` | Disable the builtin scheduler HTTP server. |
| `--pid-file PATH` | Path to the PID file for the background process. |

```bash
oneiric start --http-port 8080 --profile serverless

oneiric start --config settings/prod.yaml --refresh-interval 120 --pid-file /var/run/oneiric.pid
```

`start` exits `1` if the orchestrator is already running or fails to
launch.

#### `stop`

Stop the background orchestrator (sends SIGTERM, then escalates as
needed).

| Option | Description |
|--------|-------------|
| `--pid-file PATH` | Path to PID file (defaults to `<cache_dir>/orchestrator.pid`). |

```bash
oneiric stop

oneiric stop --pid-file /var/run/oneiric.pid
```

`stop` exits `1` if no orchestrator is running or the stop fails.

#### `process-status`

Show whether the background orchestrator is running and on which PID
file.

| Option | Description |
|--------|-------------|
| `--pid-file PATH` | Path to PID file (defaults to `<cache_dir>/orchestrator.pid`). |
| `--json` | Emit status payload as JSON. |

```bash
oneiric process-status

oneiric process-status --json
```

When the orchestrator is not running and a stale PID file is present, the
command prints its location so operators can clean it up.

______________________________________________________________________

## Orchestration Commands

### `orchestrate`

Start the runtime orchestrator (long-running process).

```bash
# Basic orchestrator
oneiric orchestrate

# With remote manifest
oneiric orchestrate --manifest docs/sample_remote_manifest.yaml

# With refresh interval
oneiric orchestrate --manifest manifest.yaml --refresh-interval 120

# Serverless profile (Cloud Run)
oneiric orchestrate --profile serverless --no-remote

# With scheduler HTTP server
oneiric orchestrate --http-port 8080

# Inspect without running
oneiric orchestrate --print-dag --workflow fastblocks.workflows.fulfillment
oneiric orchestrate --events --inspect-json
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--manifest PATH` | Remote manifest URL/path | None |
| `--refresh-interval SEC` | Remote refresh interval | 300 |
| `--profile NAME` | Runtime profile (default/serverless) | default |
| `--no-remote` | Disable remote sync | False |
| `--no-workflow-checkpoints` | Disable workflow DAG checkpoint persistence | False |
| `--http-port PORT` | Enable scheduler HTTP server | None |
| `--print-dag` | Print workflow DAG and exit | False |
| `--events` | Print event handlers and exit | False |
| `--inspect-json` | Output inspection as JSON | False |

**Use Cases:**

- Long-running service orchestrator
- Cloud Run deployment
- Remote manifest sync
- DAG/event inspection

______________________________________________________________________

## Event & Workflow Commands

### `event emit`

Emit an event to the event dispatcher.

```bash
# Emit event with JSON payload
oneiric event emit --topic user.created \
  --payload '{"user_id":"123","email":"user@example.com"}'

# With headers
oneiric event emit --topic order.paid \
  --payload '{"order_id":"456"}' \
  --headers '{"source":"web"}'

# JSON output
oneiric event emit --topic test.event --payload '{}' --json
```

**Output Example:**

```
Event dispatched: user.created
Matched handlers: 2
  ✓ user.created.handler (priority: 10) - dispatched
  ✓ audit.logger (priority: 5) - dispatched

Results:
  user.created.handler: success (23ms)
  audit.logger: success (5ms)
```

**Use Cases:**

- Test event handlers
- Manual event triggering
- Integration testing
- Debug event routing

### `workflow plan`

Show workflow DAG plan without executing.

```bash
# Show workflow plan
oneiric workflow plan --workflow fastblocks.workflows.fulfillment

# JSON output
oneiric workflow plan --workflow myapp.workflows.process \
  --json

# Include node details
oneiric workflow plan --workflow myapp.workflows.process \
  --json
```

**Output Example:**

```
Workflow: fastblocks.workflows.fulfillment

DAG Structure:
  validate_order → process_payment → ship_order → send_confirmation
                                     ↘ notify_customer

Nodes (4):
  validate_order
    Type: task
    Implementation: fastblocks.tasks.validate
    Retry: 3 attempts, exponential backoff
    Timeout: 30s

  process_payment
    Type: task
    Implementation: fastblocks.tasks.payment
    Dependencies: validate_order
    Retry: 5 attempts

  ship_order
    Type: task
    Implementation: fastblocks.tasks.shipping
    Dependencies: process_payment

  send_confirmation
    Type: task
    Implementation: fastblocks.tasks.email
    Dependencies: ship_order

  notify_customer
    Type: event
    Topic: order.shipped
    Dependencies: process_payment
```

**Use Cases:**

- Understand workflow structure
- Verify dependencies
- Debug execution order
- Documentation generation

### `workflow run`

Execute a workflow once (without enqueueing).

```bash
# Run workflow
oneiric workflow run --workflow fastblocks.workflows.fulfillment \
  --context '{"order_id":"123"}'

# With checkpoints
oneiric workflow run --workflow myapp.workflows.process \
  --context '{"user_id":"456"}' \
  --workflow-checkpoints

# Resume from checkpoint
oneiric workflow run --workflow myapp.workflows.process \
  --context '{"user_id":"456"}' \
  --resume-checkpoint

# JSON output
oneiric workflow run --workflow myapp.workflows.process \
  --context '{}' --json
```

**Use Cases:**

- Manual workflow execution
- Testing workflows
- Debug failures
- Checkpoint testing

### `workflow enqueue`

Enqueue a workflow for execution (via queue adapter).

```bash
# Enqueue workflow
oneiric workflow enqueue --workflow fastblocks.workflows.fulfillment \
  --context '{"order_id":"123"}'

# Specify queue category
oneiric workflow enqueue --workflow myapp.workflows.process \
  --context '{"user_id":"456"}' \
  --queue-category queue.scheduler

# Specify provider
oneiric workflow enqueue --workflow myapp.workflows.process \
  --context '{}' --provider cloudtasks

# JSON output
oneiric workflow enqueue --workflow myapp.workflows.process \
  --context '{}' --json
```

**Output Example:**

```
Workflow enqueued: fastblocks.workflows.fulfillment
Queue: queue.scheduler (cloudtasks)
Task ID: projects/myproject/locations/us-central1/queues/workflows/tasks/abc123

ETA: 2025-02-02T10:35:00Z
```

**Use Cases:**

- Cloud Tasks integration
- Async workflow execution
- Pub/Sub integration
- Job scheduling

### `action-invoke`

Invoke an action (including workflow.notify).

```bash
# Invoke workflow.notify action
oneiric action-invoke workflow.notify \
  --workflow fastblocks.workflows.fulfillment \
  --payload '{"message":"Deploy ready","channel":"deploys"}' \
  --send-notification

# Custom adapter override
oneiric action-invoke workflow.notify \
  --workflow myapp.workflows.deploy \
  --payload '{"status":"success"}' \
  --send-notification \
  --notify-adapter messaging \
  --notify-target "#platform-alerts"

# JSON output
oneiric action-invoke workflow.notify \
  --workflow myapp.workflows.deploy \
  --payload '{}' --json
```

**Use Cases:**

- Send notifications from CLI
- Test notification routing
- ChatOps integration
- Alert testing

______________________________________________________________________

## Remote Manifest Commands

### `remote-sync`

Sync components from remote manifest.

```bash
# Sync from manifest
oneiric remote-sync --manifest docs/sample_remote_manifest.yaml

# Watch mode (continuous sync)
oneiric remote-sync --manifest manifest.yaml --watch --refresh-interval 120

# One-time sync
oneiric remote-sync --manifest https://cdn.example.com/manifest.yaml
```

**Use Cases:**

- Load remote components
- Continuous sync in production
- CDN-based component delivery
- Multi-service coordination

### `remote-status`

Show remote sync status and telemetry.

```bash
# Show remote status
oneiric remote-status

# JSON output
oneiric remote-status --json

# Show per-domain details
oneiric remote-status --json
```

**Output Example:**

```
Remote Sync Status:
Manifest: https://cdn.example.com/manifest.yaml
Last Sync: 2025-02-02T10:30:00Z (5 minutes ago)
Status: Success

Registrations:
  adapters: 15 registered
  services: 5 registered
  tasks: 8 registered
  events: 12 registered
  workflows: 3 registered

Sync Metrics:
  Duration: 2.3s
  Latency Budget: 5s ✓
  Success Rate: 100% (last 10 syncs)
```

**Use Cases:**

- Verify remote sync health
- Check registration counts
- Monitor sync latency
- Debug remote issues

### `manifest pack`

Package YAML manifest to JSON.

```bash
# Pack manifest
oneiric manifest pack \
  --input docs/sample_remote_manifest.yaml \
  --output build/manifest.json

# Compact output
oneiric manifest pack \
  --input manifest.yaml \
  --output build/manifest.json \
  --compact

# Write to stdout
oneiric manifest pack \
  --input manifest.yaml \
  --stdout
```

**Use Cases:**

- Cloud Run deployment
- JSON manifest generation
- Manifest signing
- Pre-deployment validation

### `manifest sign`

Sign a manifest with an ED25519 key.

```bash
# Sign manifest (PEM key)
oneiric manifest sign \
  --input manifest.yaml \
  --private-key private_key.pem \
  --output manifest.signed.yaml

# Sign with raw 32-byte key and key id
oneiric manifest sign \
  --input manifest.yaml \
  --private-key ed25519.raw \
  --key-id prod-2026-q2 \
  --append

# Expire after one hour
oneiric manifest sign \
  --input manifest.yaml \
  --private-key private_key.pem \
  --expires-in 3600 \
  --stdout
```

**Use Cases:**

- Manifest security
- Supply chain integrity
- Remote manifest verification
- CI/CD integration

### Manifest Commands

The `manifest` sub-app (`manifest_app` in `oneiric.cli`) bundles manifest
packaging helpers.

#### `manifest export`

Generate a fresh `RemoteManifest` from the registered builtin adapter
and action metadata.

| Option | Description | Default |
|--------|-------------|---------|
| `--output`, `-o` | Destination manifest file (use `-` for stdout). | `build/manifest.yaml` |
| `--version` | Default version for entries (semver). | _required_ |
| `--source` | Manifest source identifier. | `oneiric-production` |
| `--format` | Output format (`yaml` or `json`). | `yaml` |
| `--no-adapters` | Exclude adapter entries. | `False` |
| `--no-actions` | Exclude action entries. | `False` |
| `--pretty`/`--compact` | Pretty-print the output. | `pretty` |
| `--stdout` | Write output to stdout regardless of `--output`. | `False` |

```bash
oneiric manifest export --version 1.2.0

oneiric manifest export --version 0.9.0 --format json --no-actions --stdout
```

The `--version` option is required and supplies the manifest entry
`version` for every emitted adapter/action payload.

______________________________________________________________________

## Observability Commands

The runtime observability surface is exposed via [`health`](#health),
[`activity`](#activity), and [`load-test`](#load-test) — there is no
`telemetry` or `logs` subcommand in this release.

______________________________________________________________________

## Plugin & Secrets Commands

### `plugins`

List entry-point plugins.

```bash
# List all plugins
oneiric plugins

# JSON output
oneiric plugins --json
```

**Output Example:**

```
Entry-Point Plugins:

oneiric.adapters:
  myapp.adapters.CacheProvider (redis) ✓
  myapp.adapters.QueueProvider (cloudtasks) ✓

oneiric.services:
  myapp.services.PaymentService ✓

oneiric.tasks:
  myapp.tasks.SendEmail ✓

Errors: 0
Loaded: 5 candidates
```

**Use Cases:**

- Verify plugin loading
- Debug plugin issues
- Audit installed plugins
- Development testing

### `secrets rotate`

Rotate (invalidate) cached secrets.

```bash
# Rotate specific keys
oneiric secrets rotate --keys redis_url,api_key

# Rotate all secrets
oneiric secrets rotate --all

# Override provider
oneiric secrets rotate --all --provider vault
```

**Use Cases:**

- Force secret refresh
- Rotate credentials
- Clear cached secrets
- Security incidents

______________________________________________________________________

## Common Patterns

### Pattern 1: Smoke Test Before Deploy

```bash
#!/bin/bash
# pre-deploy-smoke-test.sh

set -e

echo "Running pre-deploy smoke tests..."

# Check health
oneiric health --probe --json > health.json
cat health.json

# Verify critical components
oneiric status --domain adapter --key cache --json
oneiric status --domain service --key payment-processor --json

# Test workflow plan
oneiric workflow plan --workflow fastblocks.workflows.fulfillment

# Test event routing
oneiric event emit --topic test.smoke --payload '{}' --json

echo "Smoke tests passed!"
```

### Pattern 2: Zero-Downtime Swap

```bash
#!/bin/bash
# zero-downtime-swap.sh

COMPONENT="cache"
OLD_PROVIDER="redis"
NEW_PROVIDER="memcached"

echo "Starting zero-downtime swap..."

# Pre-flight: check new provider health
oneiric health --domain adapter --key $COMPONENT --probe

# Perform swap
oneiric swap --domain adapter --key $COMPONENT --provider $NEW_PROVIDER

# Verify
oneiric status --domain adapter --key $COMPONENT

# If failed, rollback
if [ $? -ne 0 ]; then
  echo "Swap failed, rolling back..."
  oneiric swap --domain adapter --key $COMPONENT --provider $OLD_PROVIDER --force
  exit 1
fi

echo "Swap successful!"
```

### Pattern 3: Orchestrator Deployment

```bash
#!/bin/bash
# deploy-orchestrator.sh

MANIFEST_URL="https://cdn.example.com/manifest.yaml"
REFRESH_INTERVAL=120
HTTP_PORT=8080

echo "Deploying orchestrator..."

# Package manifest
oneiric manifest pack \
  --input manifest.yaml \
  --output build/manifest.json

# Start orchestrator
oneiric orchestrate \
  --manifest $MANIFEST_URL \
  --refresh-interval $REFRESH_INTERVAL \
  --http-port $HTTP_PORT \
  --profile serverless
```

### Pattern 4: Remote Manifest CI/CD

```bash
#!/bin/bash
# ci-manifest-validation.sh

set -e

echo "Validating remote manifest..."

# Validate schema
oneiric manifest pack \
  --input manifest.yaml \
  --output build/manifest.json

# Sign manifest
oneiric manifest sign \
  --input manifest.yaml \
  --private-key $PRIVATE_KEY_PATH \
  --output manifest.signed.yaml

# Test sync
oneiric remote-sync --manifest manifest.signed.yaml --watch

echo "Manifest validation passed!"
```

### Pattern 5: Incident Response

```bash
#!/bin/bash
# incident-response.sh

COMPONENT="service:worker"
NOTE="Incident #123: High error rate"

echo "Starting incident response..."

# Drain component gracefully
oneiric drain --domain service --key worker --note "$NOTE"

# Wait for drain
sleep 30

# Check activity
oneiric activity --domain service --json

# Health check
oneiric health --probe --domain service --key worker

# When resolved, resume
oneiric drain --resume --domain service --key worker --note "Incident resolved"

echo "Incident response complete!"
```

______________________________________________________________________

## Troubleshooting

### Issue: Command not found

**Solution:**

```bash
# Use the installed console script
oneiric [command]

# Or install via pip
pip install oneiric
oneiric [command]
```

### Issue: Config file not found

**Solution:**

```bash
# Set config explicitly
export ONEIRIC_CONFIG=/path/to/config.toml

# Or create default
cp docs/examples/demo_settings.toml ~/.oneiric.toml
```

### Issue: "No candidate found"

**Solution:**

```bash
# Check what's registered
oneiric list --domain adapter --shadowed

# Explain resolution
oneiric explain --domain adapter --key cache

# Use demo mode to test
oneiric --demo list --domain adapter
```

### Issue: Swap fails health check

**Solution:**

```bash
# Check health manually
oneiric health --domain adapter --key cache --probe

# Force swap if you're sure
oneiric swap --domain adapter --key cache --provider memcached --force

# Check logs for errors
tail -f .oneiric_cache/runtime.log
```

### Issue: Remote sync fails

**Solution:**

```bash
# Check manifest URL
curl -v $MANIFEST_URL

# Check remote status
oneiric remote-status --json

# Sync with watch mode
oneiric remote-sync --manifest manifest.yaml --watch
```

### Issue: Orchestrator won't start

**Solution:**

```bash
# Check config
oneiric supervisor-info

# Validate manifest
oneiric manifest pack --input manifest.yaml --output build/manifest.json

# Test health
oneiric health --probe

# Check logs
tail -f .oneiric_cache/runtime.log
```

### Issue: Events not dispatching

**Solution:**

```bash
# Check event handlers
oneiric orchestrate --events --inspect-json

# Dry run event
oneiric event emit --topic test.event --payload '{}' --json

# Check telemetry
oneiric activity --json

# Verify event dispatcher
oneiric status --domain event --key dispatcher
```

### Issue: Workflow fails

**Solution:**

```bash
# Check workflow plan
oneiric workflow plan --workflow myapp.workflows.process

# Run with checkpoints
oneiric workflow run --workflow myapp.workflows.process \
  --context '{}' --workflow-checkpoints

# Check activity
oneiric activity --json

# Resume from checkpoint
oneiric workflow run --workflow myapp.workflows.process \
  --context '{}' --resume-checkpoint
```

______________________________________________________________________

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ONEIRIC_CONFIG` | Config file path | `/path/to/config.toml` |
| `ONEIRIC_PROFILE` | Runtime profile | `serverless` |
| `ONEIRIC_STACK_ORDER` | Priority order | `prod:20,dev:10,local:0` |
| `ONEIRIC_RUNTIME_SUPERVISOR__ENABLED` | Enable supervisor | `true`/`false` |
| `ONEIRIC_ACTIVITY_STORE` | Activity store path | `/workspace/.oneiric_cache/domain_activity.sqlite` |
| `ONEIRIC_LOG_LEVEL` | Log level | `DEBUG`, `INFO`, `WARNING` |

______________________________________________________________________

## Exit Codes

The canonical exit codes are defined by
`oneiric.cli.base.ExitCode`:

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | `SUCCESS` | Command completed normally |
| 1 | `ERROR` | Generic runtime failure |
| 2 | `USAGE_ERROR` | Invalid arguments or configuration |
| 3 | `UNAVAILABLE` | Component's `doctor`/`health` hooks raised `NotImplementedError` |
| 4 | `PERMISSION_DENIED` | Insufficient permissions for the requested operation |
| 124 | `TIMEOUT` | Operation exceeded its deadline |

Subcommands may raise other codes (e.g. `process-status` exits `1` when the
orchestrator is already running); the table above covers the standard
contract used by `OneiricCLIBase` and its subclasses.

______________________________________________________________________

## Further Reading

- **Quick Start:** `README.md`
- **Migration Guide:** `docs/MIGRATION_GUIDE.md`
- **Architecture:** `docs/NEW_ARCH_SPEC.md`
- **Deployment:** `docs/deployment/CLOUD_RUN_BUILD.md`
- **Runbooks:** `docs/runbooks/`

______________________________________________________________________

## Support

- **Issues:** https://github.com/lesleslie/oneiric/issues
- **Documentation:** `docs/README.md`
- **Examples:** `docs/examples/LOCAL_CLI_DEMO.md`
