# Oneiric CLI Reference

**Last Updated:** 2025-02-02
**Version:** 0.3.3

Complete reference for all Oneiric CLI commands with examples, use cases, and troubleshooting tips.

______________________________________________________________________

## Table of Contents

1. [Installation & Setup](#installation--setup)
1. [Global Options](#global-options)
1. [Domain Commands](#domain-commands)
1. [Resolution Commands](#resolution-commands)
1. [Lifecycle Commands](#lifecycle-commands)
1. [Orchestration Commands](#orchestration-commands)
1. [Event & Workflow Commands](#event--workflow-commands)
1. [Remote Manifest Commands](#remote-manifest-commands)
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
uv run python -m oneiric.cli --install-completion

# Restart shell or source
source ~/.bashrc  # or ~/.zshrc
```

### Configuration

```bash
# Set config file location
export ONEIRIC_CONFIG=/path/to/config.toml

# Default locations (checked in order):
# 1. $ONEIRIC_CONFIG
# 2. ~/.oneiric.toml
# 3. ./settings/app.toml
```

### Demo Mode

Most commands support `--demo` flag to use built-in demo providers:

```bash
# Use demo adapters/services/tasks
uv run python -m oneiric.cli --demo list --domain adapter
```

______________________________________________________________________

## Global Options

| Option | Description | Example |
|--------|-------------|---------|
| `--demo` | Use built-in demo providers | `--demo list --domain adapter` |
| `--config PATH` | Specify config file | `--config /path/to/config.toml status` |
| `--suppress-events` | Filter out event log output | `--suppress-events list --domain adapter` |
| `--json` | Output JSON instead of tables | `list --domain adapter --json` |
| `--verbose` | Enable verbose logging | `--verbose health --probe` |
| `--help` | Show command help | `swap --help` |

______________________________________________________________________

## Domain Commands

### `list`

List all registered components for a domain.

```bash
# List all adapters
oneiric.cli list --domain adapter

# List services
oneiric.cli list --domain service

# Include shadowed (inactive) candidates
oneiric.cli list --domain adapter --shadowed

# JSON output for scripts
oneiric.cli list --domain adapter --json

# Filter by key
oneiric.cli list --domain adapter --key cache
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
oneiric.cli status --domain adapter --key cache

# Show service status
oneiric.cli status --domain service --key payment-processor

# JSON output
oneiric.cli status --domain adapter --key cache --json

# Include lifecycle state
oneiric.cli status --domain adapter --key cache --verbose
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
oneiric.cli explain --domain adapter --key cache

# Explain service selection
oneiric.cli explain --domain service --key status

# Show all candidates with reasons
oneiric.cli explain --domain adapter --key cache --verbose

# JSON output
oneiric.cli explain --domain adapter --key cache --json
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
oneiric.cli swap --domain adapter --key cache --provider memcached

# Force swap (skip health check)
oneiric.cli swap --domain adapter --key cache --provider memcached --force

# Dry run (show what would happen)
oneiric.cli swap --domain adapter --key cache --provider memcached --dry-run

# Swap service
oneiric.cli swap --domain service --key payment-processor --provider stripe
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

### `resolve`

Manually trigger resolution (useful for debugging).

```bash
# Resolve and display result
oneiric.cli resolve --domain adapter --key cache

# Show all candidates
oneiric.cli resolve --domain adapter --key cache --all

# Test with different priority
ONEIRIC_STACK_ORDER="custom:20" oneiric.cli resolve --domain adapter --key cache
```

______________________________________________________________________

## Lifecycle Commands

### `health`

Check health of components or entire system.

```bash
# Probe all components
oneiric.cli health --probe

# Probe specific domain
oneiric.cli health --domain adapter --key cache

# JSON output for monitoring
oneiric.cli health --probe --json

# Continuous monitoring (watch mode)
oneiric.cli health --probe --watch --interval 30
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
oneiric.cli pause --domain service --key email-sender --note "Maintenance window"

# Pause multiple components
oneiric.cli pause --domain service --key payment-processor
oneiric.cli pause --domain adapter --key queue

# Resume paused component
oneiric.cli pause --resume --domain service --key email-sender
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
oneiric.cli drain --domain service --key worker --note "Deploying new version"

# Resume drained component
oneiric.cli drain --resume --domain service --key worker
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
oneiric.cli activity

# Show specific domain
oneiric.cli activity --domain service

# JSON output
oneiric.cli activity --json

# Filter by state
oneiric.cli activity --state paused
oneiric.cli activity --state draining
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
oneiric.cli supervisor-info

# Check if enabled
oneiric.cli supervisor-info --json

# Use with specific config
ONEIRIC_CONFIG=/path/to/config.toml oneiric.cli supervisor-info
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

______________________________________________________________________

## Orchestration Commands

### `orchestrate`

Start the runtime orchestrator (long-running process).

```bash
# Basic orchestrator
oneiric.cli orchestrate

# With remote manifest
oneiric.cli orchestrate --manifest docs/sample_remote_manifest.yaml

# With refresh interval
oneiric.cli orchestrate --manifest manifest.yaml --refresh-interval 120

# Serverless profile (Cloud Run)
oneiric.cli orchestrate --profile serverless --no-remote

# With scheduler HTTP server
oneiric.cli orchestrate --http-port 8080

# Inspect without running
oneiric.cli orchestrate --print-dag --workflow fastblocks.workflows.fulfillment
oneiric.cli orchestrate --events --inspect-json
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--manifest PATH` | Remote manifest URL/path | None |
| `--refresh-interval SEC` | Remote refresh interval | 300 |
| `--profile NAME` | Runtime profile (default/serverless) | default |
| `--no-remote` | Disable remote sync | False |
| `--no-watchers` | Disable config watchers | False |
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
oneiric.cli event emit --topic user.created \
  --payload '{"user_id":"123","email":"user@example.com"}'

# With metadata
oneiric.cli event emit --topic order.paid \
  --payload '{"order_id":"456"}' \
  --metadata '{"source":"web"}'

# JSON output
oneiric.cli event emit --topic test.event --payload '{}' --json

# Dry run (show handlers without dispatching)
oneiric.cli event emit --topic test.event --payload '{}' --dry-run
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
oneiric.cli workflow plan --workflow fastblocks.workflows.fulfillment

# JSON output
oneiric.cli workflow plan --workflow myapp.workflows.process \
  --json

# Include node details
oneiric.cli workflow plan --workflow myapp.workflows.process \
  --verbose
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
oneiric.cli workflow run --workflow fastblocks.workflows.fulfillment \
  --context '{"order_id":"123"}'

# With checkpoints
oneiric.cli workflow run --workflow myapp.workflows.process \
  --context '{"user_id":"456"}' \
  --workflow-checkpoints

# Resume from checkpoint
oneiric.cli workflow run --workflow myapp.workflows.process \
  --context '{"user_id":"456"}' \
  --resume-checkpoint

# JSON output
oneiric.cli workflow run --workflow myapp.workflows.process \
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
oneiric.cli workflow enqueue --workflow fastblocks.workflows.fulfillment \
  --context '{"order_id":"123"}'

# Specify queue category
oneiric.cli workflow enqueue --workflow myapp.workflows.process \
  --context '{"user_id":"456"}' \
  --queue-category queue.scheduler

# Specify provider
oneiric.cli workflow enqueue --workflow myapp.workflows.process \
  --context '{}' --provider cloudtasks

# JSON output
oneiric.cli workflow enqueue --workflow myapp.workflows.process \
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
oneiric.cli action-invoke workflow.notify \
  --workflow fastblocks.workflows.fulfillment \
  --payload '{"message":"Deploy ready","channel":"deploys"}' \
  --send-notification

# Custom adapter override
oneiric.cli action-invoke workflow.notify \
  --workflow myapp.workflows.deploy \
  --payload '{"status":"success"}' \
  --send-notification \
  --notify-adapter messaging \
  --notify-target "#platform-alerts"

# JSON output
oneiric.cli action-invoke workflow.notify \
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
oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml

# Watch mode (continuous sync)
oneiric.cli remote-sync --manifest manifest.yaml --watch --refresh-interval 120

# One-time sync
oneiric.cli remote-sync --manifest https://cdn.example.com/manifest.yaml

# Verbose output
oneiric.cli remote-sync --manifest manifest.yaml --verbose
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
oneiric.cli remote-status

# JSON output
oneiric.cli remote-status --json

# Show per-domain details
oneiric.cli remote-status --verbose
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
oneiric.cli manifest pack \
  --input docs/sample_remote_manifest.yaml \
  --output build/manifest.json

# With signature
oneiric.cli manifest pack \
  --input manifest.yaml \
  --output manifest.signed.json \
  --sign \
  --private-key-path private_key.pem

# Validate only
oneiric.cli manifest pack \
  --input manifest.yaml \
  --validate-only
```

**Use Cases:**

- Cloud Run deployment
- JSON manifest generation
- Manifest signing
- Pre-deployment validation

### `manifest sign`

Sign a manifest with ED25519 key.

```bash
# Generate keypair (one-time)
oneiric.cli manifest generate-keypair --output-dir ./

# Sign manifest
oneiric.cli manifest sign \
  --input manifest.yaml \
  --output manifest.signed.yaml \
  --private-key-path private_key.pem

# Verify signature
oneiric.cli manifest verify \
  --input manifest.signed.yaml \
  --public-key-path public_key.pem
```

**Use Cases:**

- Manifest security
- Supply chain integrity
- Remote manifest verification
- CI/CD integration

______________________________________________________________________

## Observability Commands

### `telemetry`

Show runtime telemetry.

```bash
# Show all telemetry
oneiric.cli telemetry

# Event telemetry
oneiric.cli telemetry --events

# Workflow telemetry
oneiric.cli telemetry --workflows

# JSON output
oneiric.cli telemetry --json
```

**Output Example:**

```
Runtime Telemetry:

Last Event Dispatch:
  Topic: order.created
  Handlers: 3
  Duration: 145ms
  Attempts: 1
  Errors: 0

Last Workflow Execution:
  Workflow: fastblocks.workflows.fulfillment
  Nodes: 4
  Duration: 2.3s
  Retries: 1
  Errors: 0
```

**Use Cases:**

- Debug runtime behavior
- Performance analysis
- Error tracking
- Dashboard data source

### `logs`

Show structured logs (if file sink configured).

```bash
# Show recent logs
oneiric.cli logs

# Filter by domain
oneiric.cli logs --domain adapter

# Filter by level
oneiric.cli logs --level error

# Tail logs
oneiric.cli logs --tail

# JSON output
oneiric.cli logs --json
```

**Use Cases:**

- Local debugging
- Log inspection
- Error investigation
- Development testing

______________________________________________________________________

## Plugin & Secrets Commands

### `plugins`

List entry-point plugins.

```bash
# List all plugins
oneiric.cli plugins

# Show specific group
oneiric.cli plugins --group oneiric.adapters

# Verbose output
oneiric.cli plugins --verbose
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
oneiric.cli secrets rotate --keys redis_url,api_key

# Rotate all secrets
oneiric.cli secrets rotate --all

# Dry run
oneiric.cli secrets rotate --keys api_key --dry-run
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
oneiric.cli health --probe --json > health.json
cat health.json

# Verify critical components
oneiric.cli status --domain adapter --key cache --json
oneiric.cli status --domain service --key payment-processor --json

# Test workflow plan
oneiric.cli workflow plan --workflow fastblocks.workflows.fulfillment

# Test event routing (dry run)
oneiric.cli event emit --topic test.smoke --payload '{}' --dry-run

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
oneiric.cli health --domain adapter --key $COMPONENT --provider $NEW_PROVIDER

# Perform swap
oneiric.cli swap --domain adapter --key $COMPONENT --provider $NEW_PROVIDER

# Verify
oneiric.cli status --domain adapter --key $COMPONENT

# If failed, rollback
if [ $? -ne 0 ]; then
  echo "Swap failed, rolling back..."
  oneiric.cli swap --domain adapter --key $COMPONENT --provider $OLD_PROVIDER --force
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
oneiric.cli manifest pack \
  --input manifest.yaml \
  --output build/manifest.json

# Start orchestrator
oneiric.cli orchestrate \
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
oneiric.cli manifest pack \
  --input manifest.yaml \
  --validate-only

# Sign manifest
oneiric.cli manifest sign \
  --input manifest.yaml \
  --output manifest.signed.yaml \
  --private-key-path $PRIVATE_KEY_PATH

# Verify signature
oneiric.cli manifest verify \
  --input manifest.signed.yaml \
  --public-key-path $PUBLIC_KEY_PATH

# Test sync
oneiric.cli remote-sync --manifest manifest.signed.yaml --dry-run

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
oneiric.cli drain --domain service --key worker --note "$NOTE"

# Wait for drain
sleep 30

# Check activity
oneiric.cli activity --domain service --json

# Health check
oneiric.cli health --probe --domain service --key worker

# When resolved, resume
oneiric.cli drain --resume --domain service --key worker --note "Incident resolved"

echo "Incident response complete!"
```

______________________________________________________________________

## Troubleshooting

### Issue: Command not found

**Solution:**

```bash
# Use full module path
python -m oneiric.cli [command]

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
oneiric.cli list --domain adapter --shadowed

# Explain resolution
oneiric.cli explain --domain adapter --key cache

# Use demo mode to test
oneiric.cli --demo list --domain adapter
```

### Issue: Swap fails health check

**Solution:**

```bash
# Check health manually
oneiric.cli health --domain adapter --key cache --provider memcached

# Force swap if you're sure
oneiric.cli swap --domain adapter --key cache --provider memcached --force

# Check logs for errors
oneiric.cli logs --tail
```

### Issue: Remote sync fails

**Solution:**

```bash
# Check manifest URL
curl -v $MANIFEST_URL

# Verify signature
oneiric.cli manifest verify --input manifest.yaml

# Check remote status
oneiric.cli remote-status --verbose

# Sync with verbose output
oneiric.cli remote-sync --manifest manifest.yaml --verbose
```

### Issue: Orchestrator won't start

**Solution:**

```bash
# Check config
oneiric.cli supervisor-info

# Validate manifest
oneiric.cli manifest pack --input manifest.yaml --validate-only

# Test health
oneiric.cli health --probe

# Check logs
tail -f .oneiric_cache/runtime.log
```

### Issue: Events not dispatching

**Solution:**

```bash
# Check event handlers
oneiric.cli orchestrate --events --inspect-json

# Dry run event
oneiric.cli event emit --topic test.event --payload '{}' --dry-run

# Check telemetry
oneiric.cli telemetry --events

# Verify event dispatcher
oneiric.cli status --domain event --key dispatcher
```

### Issue: Workflow fails

**Solution:**

```bash
# Check workflow plan
oneiric.cli workflow plan --workflow myapp.workflows.process

# Run with checkpoints
oneiric.cli workflow run --workflow myapp.workflows.process \
  --context '{}' --workflow-checkpoints

# Check telemetry
oneiric.cli telemetry --workflows

# Resume from checkpoint
oneiric.cli workflow run --workflow myapp.workflows.process \
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

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid usage |
| 3 | Component not found |
| 4 | Health check failed |
| 5 | Swap failed |
| 6 | Remote sync failed |

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
