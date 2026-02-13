# Oneiric Operational Modes

Oneiric supports two operational modes designed for different use cases: **Lite Mode** for development and testing, and **Standard Mode** for production deployments with remote resolution and distributed configuration.

______________________________________________________________________

## Mode Comparison

| Feature | Lite Mode | Standard Mode |
|---------|-----------|---------------|
| **Setup Time** | < 2 minutes | ~ 5 minutes |
| **Configuration** | Local only | Local + Remote |
| **Remote Resolution** | No | Yes |
| **Cloud Backup** | No | Yes |
| **Adapter Distribution** | Local only | Via Dhruva |
| **Manifest Sync** | Manual | Automatic |
| **Best For** | Development, Testing | Production, Multi-env |
| **Dependencies** | None | Dhruva (optional) |
| **Network Required** | No | Yes (for remote features) |

______________________________________________________________________

## Lite Mode (Development)

### Overview

Lite Mode is designed for **local development and testing**. It operates completely standalone with no external dependencies, using local configuration files and built-in adapters.

### Setup Time

**< 2 minutes** from installation to first resolve

### Features

**Local Configuration**:

- File-based configuration (YAML/TOML/JSON)
- No remote fetching
- Fast startup (< 100ms)

**Built-in Adapters**:

- 80+ adapters included
- No remote installation needed
- All adapters available immediately

**Simple Lifecycle**:

- No remote sync
- No signature verification
- Direct component activation

### Quick Start

```bash
# 1. Set mode to lite
export ONEIRIC_MODE=lite

# 2. Initialize configuration
oneiric init

# 3. Load configuration
oneiric load config.yaml

# 4. Start Oneiric
oneiric start

# 5. Verify health
oneiric health --probe
```

### Configuration Example

```yaml
# oneiric.yaml (Lite Mode)
mode: "lite"

# Local configuration only
remote:
  enabled: false

# Adapters (built-in)
adapters:
  postgresql:
    provider: pgvector
    connection_string: "postgresql://localhost/db"

  redis:
    provider: redis
    connection_string: "redis://localhost:6379"

# Services
services:
  payment:
    class: "PaymentService"
    dependencies:
      - postgresql
      - redis
```

### Usage Patterns

**Development Workflow**:

```bash
# Install Oneiric
uv add oneiric

# Create config
cat > oneiric.yaml << EOF
mode: lite
adapters:
  postgresql:
    provider: pgvector
    connection_string: "postgresql://localhost/dev"
EOF

# Start and test
oneiric start
oneiric resolve
```

**Testing Workflow**:

```bash
# Use test configuration
export ONEIRIC_CONFIG="tests/config/test.yaml"
oneiric start

# Run tests
pytest tests/integration/test_adapters.py

# Cleanup
oneiric stop
```

### Advantages

✅ **Fast Setup**: No external services required
✅ **Zero Dependencies**: Works completely offline
✅ **Quick Iteration**: No remote sync delays
✅ **Simple Debugging**: Everything is local
✅ **Low Overhead**: No background sync processes

### Limitations

❌ **No Remote Resolution**: All adapters must be local
❌ **No Cloud Backup**: Configuration is local only
❌ **Manual Updates**: Adapters must be updated manually
❌ **Single Environment**: No multi-environment support

______________________________________________________________________

## Standard Mode (Production)

### Overview

Standard Mode is designed for **production deployments** with remote resolution, distributed configuration, and cloud backup support. It integrates with Dhruva for adapter distribution and can sync configuration from cloud storage.

### Setup Time

**~ 5 minutes** including Dhruva and cloud configuration

### Features

**Remote Resolution**:

- Fetch adapters from Dhruva
- Signed manifest delivery
- Automatic version updates

**Distributed Configuration**:

- Cloud backup (S3/Azure/GCS)
- Multi-environment support
- Configuration versioning

**Enhanced Security**:

- ED25519 signature verification
- TLS for MCP connections
- Secret management integration

**Operational Resilience**:

- Automatic health checks
- Graceful degradation
- Remote sync retry logic

### Quick Start

```bash
# 1. Set mode to standard
export ONEIRIC_MODE=standard

# 2. Configure remote URL
export DHruVA_MCP_URL="http://localhost:8683/mcp"

# 3. Initialize with remote
oneiric init --remote-url http://localhost:8683/mcp

# 4. Sync from manifest
oneiric remote-sync \
  --manifest docs/sample_remote_manifest.yaml \
  --refresh-interval 120

# 5. Start Oneiric
oneiric start

# 6. Verify health
oneiric health --probe
```

### Configuration Example

```yaml
# oneiric.yaml (Standard Mode)
mode: "standard"

# Remote configuration
remote:
  enabled: true
  url: "http://dhruva:8683/mcp"
  manifest: "docs/sample_remote_manifest.yaml"
  refresh_interval: 120
  verify_signatures: true
  public_key: "/path/to/public_key.pem"

# Cloud backup
cloud_backup:
  enabled: true
  provider: "s3"
  url: "s3://my-bucket/oneiric/config.yaml"
  sync_interval: 300

# Adapters (can be remote)
adapters:
  postgresql:
    provider: pgvector
    connection_string: "postgresql://prod-db/pgvector"

  redis:
    provider: redis
    connection_string: "redis://prod-redis:6379"

# Orchestrator integration
orchestrator:
  mahavishnu_url: "http://mahavishnu:8680/mcp"
```

### Environment Variables

```bash
# Mode selection
export ONEIRIC_MODE=standard

# Remote configuration
export DHruVA_MCP_URL="http://dhruva:8683/mcp"
export ONEIRIC_REMOTE_MANIFEST="s3://my-bucket/manifest.json"
export ONEIRIC_MANIFEST_PUBLIC_KEY="/path/to/public_key.pem"

# Cloud backup
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Orchestrator
export MAHAVISHNU_MCP_URL="http://mahavishnu:8680/mcp"
```

### Usage Patterns

**Production Deployment**:

```bash
# Configure environment
export ONEIRIC_MODE=standard
export DHruVA_MCP_URL="http://dhruva:8683/mcp"

# Sync from production manifest
oneiric remote-sync \
  --manifest s3://my-bucket/oneiric/prod_manifest.json \
  --refresh-interval 300

# Start with health checks
oneiric start --health-path /tmp/health.json

# Monitor
oneiric health --probe --json
```

**Multi-Environment Setup**:

```bash
# Development
export ONEIRIC_ENV=dev
export ONEIRIC_REMOTE_MANIFEST="s3://my-bucket/oneiric/dev_manifest.json"
oneiric start

# Staging
export ONEIRIC_ENV=staging
export ONEIRIC_REMOTE_MANIFEST="s3://my-bucket/oneiric/staging_manifest.json"
oneiric start

# Production
export ONEIRIC_ENV=prod
export ONEIRIC_REMOTE_MANIFEST="s3://my-bucket/oneiric/prod_manifest.json"
oneiric start
```

### Advantages

✅ **Remote Resolution**: Access to distributed adapter registry
✅ **Cloud Backup**: Configuration disaster recovery
✅ **Automatic Updates**: Remote manifest sync
✅ **Multi-Environment**: Separate configs per environment
✅ **Enhanced Security**: Signature verification and TLS
✅ **Operational Resilience**: Health checks and retry logic

### Requirements

**Optional Services**:

- **Dhruva** (for remote manifests): http://localhost:8683/mcp
- **Mahavishnu** (for orchestration): http://localhost:8680/mcp
- **Cloud Storage** (for backup): S3/Azure/GCS

**Network Access**:

- Connectivity to Dhruva MCP server
- Connectivity to cloud storage (if using backup)
- Outbound internet access (if using public cloud)

**Security**:

- ED25519 public key for manifest verification
- TLS certificates for MCP connections
- IAM roles for cloud storage access

______________________________________________________________________

## Mode Switching

### Switching from Lite to Standard

```bash
# 1. Stop Oneiric
oneiric stop

# 2. Export current configuration
oneiric export --output oneiric_backup.yaml

# 3. Switch mode
export ONEIRIC_MODE=standard

# 4. Configure remote
oneiric init --remote-url http://localhost:8683/mcp

# 5. Import configuration
oneiric load oneiric_backup.yaml

# 6. Start in standard mode
oneiric start
```

### Switching from Standard to Lite

```bash
# 1. Stop Oneiric
oneiric stop

# 2. Export current configuration
oneiric export --output oneiric_backup.yaml

# 3. Switch mode
export ONEIRIC_MODE=lite

# 4. Disable remote (optional)
oneiric disable-remote

# 5. Import configuration
oneiric load oneiric_backup.yaml

# 6. Start in lite mode
oneiric start
```

______________________________________________________________________

## Serverless Profile (Cloud Run)

Oneiric includes a **serverless profile** optimized for Google Cloud Run and other serverless platforms.

### Profile Characteristics

- **No Watchers**: File watching disabled (use polling)
- **No Remote Sync**: Manifest baked into build
- **No Background Tasks**: All execution is request-scoped
- **Fast Startup**: < 500ms cold start time
- **Low Memory**: < 128MB baseline

### Configuration

```bash
# Set serverless profile
export ONEIRIC_PROFILE=serverless

# Use serverless config
export ONEIRIC_CONFIG=/workspace/config/serverless.toml
```

### Build Process

```bash
# 1. Package manifest
uv run python -m oneiric.cli manifest pack \
  --input docs/sample_remote_manifest.yaml \
  --output build/serverless_manifest.json

# 2. Build container
docker build -t oneiric-serverless .

# 3. Deploy to Cloud Run
gcloud run deploy oneiric \
  --image gcr.io/project/oneiric-serverless \
  --platform managed \
  --region us-central1
```

### Serverless Config Example

```toml
# serverless.toml
[oneiric]
profile = "serverless"
mode = "lite"

[oneiric.remote]
enabled = false
# Manifest is baked into container at /workspace/manifest.json

[oneiric.watchers]
enabled = false
# No file watching in serverless

[oneiric.runtime]
supervisor_enabled = true
health_path = "/tmp/runtime_health.json"
```

### Advantages

✅ **Fast Cold Starts**: No background processes
✅ **Low Memory**: Minimal footprint
✅ **Scale to Zero**: No costs when idle
✅ **Stateless**: Perfect for serverless

### Limitations

❌ **No Hot Reload**: Must redeploy for config changes
❌ **No Remote Sync**: Manifest must be baked in
❌ **No Watchers**: File watching disabled

______________________________________________________________________

## Mode Selection Guide

### Choose Lite Mode When:

- **Local Development**: You're developing locally and don't need remote features
- **Testing**: You're running tests in CI/CD and want fast execution
- **Offline Development**: You don't have reliable internet access
- **Simple Deployments**: You have a single environment and simple adapter needs
- **Proof of Concept**: You're prototyping and don't need production features

### Choose Standard Mode When:

- **Production Deployment**: You're deploying to production and need reliability
- **Multi-Environment**: You have dev/staging/prod environments
- **Remote Adapters**: You need to fetch adapters from Dhruva
- **Cloud Backup**: You want configuration backup in cloud storage
- **Team Collaboration**: Multiple teams need to share configurations
- **Compliance**: You need signature verification and audit trails

### Choose Serverless Profile When:

- **Cloud Run**: You're deploying to Google Cloud Run
- **AWS Lambda**: You're using AWS Lambda or similar FaaS
- **Scale to Zero**: You want to minimize costs when idle
- **Stateless**: Your workload is request-scoped and stateless
- **Fast Startup**: You need sub-second cold start times

______________________________________________________________________

## Performance Comparison

| Metric | Lite Mode | Standard Mode | Serverless Profile |
|--------|-----------|---------------|-------------------|
| **Startup Time** | < 100ms | ~ 500ms | < 500ms |
| **Memory Usage** | ~ 50MB | ~ 100MB | ~ 80MB |
| **Resolve Latency** | < 1ms | < 5ms | < 2ms |
| **Config Load** | < 10ms | ~ 100ms | < 20ms |
| **Remote Sync** | N/A | ~ 500ms | N/A |
| **Scale to Zero** | No | No | Yes |

______________________________________________________________________

## Troubleshooting

### "Remote sync failed in Standard Mode"

**Solution**: Check Dhruva connectivity and manifest URL

```bash
# Check Dhruva health
curl http://localhost:8683/mcp/health

# Verify manifest URL
oneiric remote-sync --verify-only --manifest manifest.yaml

# Check network connectivity
ping dhruva
```

### "Cannot find adapter in Lite Mode"

**Solution**: Use Standard Mode or install adapter locally

```bash
# Option 1: Switch to Standard Mode
export ONEIRIC_MODE=standard
oneiric enable-remote --url http://localhost:8683/mcp

# Option 2: Install adapter locally
oneiric activate adapter postgresql --provider pgvector
```

### "Manifest signature verification failed"

**Solution**: Check public key configuration

```bash
# Verify public key path
export ONEIRIC_MANIFEST_PUBLIC_KEY="/path/to/public_key.pem"

# Test signature verification
oneiric manifest verify --input manifest.json

# Disable verification (not recommended for production)
export ONEIRIC_VERIFY_SIGNATURES=false
```

______________________________________________________________________

## Next Steps

- [Service Dependencies](../reference/service-dependencies.md) - External service integration
- [Configuration Reference](../reference/config.md) - Complete configuration options
- [Production Deployment](../deployment/PRODUCTION.md) - Production best practices
- [Cloud Run Guide](../deployment/CLOUD_RUN.md) - Serverless deployment
- [Troubleshooting](../runbooks/TROUBLESHOOTING.md) - Common issues and solutions

______________________________________________________________________

## Appendix: Configuration Templates

### Lite Mode Template

```yaml
# oneiric.lite.yaml
mode: lite

remote:
  enabled: false

cloud_backup:
  enabled: false

adapters:
  postgresql:
    provider: pgvector
    connection_string: "postgresql://localhost/dev"

services:
  payment:
    class: "PaymentService"
```

### Standard Mode Template

```yaml
# oneiric.standard.yaml
mode: standard

remote:
  enabled: true
  url: "http://dhruva:8683/mcp"
  manifest: "docs/sample_remote_manifest.yaml"
  refresh_interval: 120
  verify_signatures: true

cloud_backup:
  enabled: true
  provider: "s3"
  url: "s3://my-bucket/oneiric/config.yaml"
  sync_interval: 300

orchestrator:
  mahavishnu_url: "http://mahavishnu:8680/mcp"

adapters:
  postgresql:
    provider: pgvector
    connection_string: "postgresql://prod-db/pgvector"

services:
  payment:
    class: "PaymentService"
```

### Serverless Profile Template

```toml
# serverless.toml
[oneiric]
profile = "serverless"
mode = "lite"

[oneiric.remote]
enabled = false

[oneiric.watchers]
enabled = false

[oneiric.runtime]
supervisor_enabled = true
health_path = "/tmp/runtime_health.json"

[oneiric.adapters.postgresql]
provider = "pgvector"
connection_string = "postgresql://prod-db/pgvector"
```

______________________________________________________________________

**Last Updated**: 2025-02-09
**Oneiric Version**: v0.3.3
**Status**: Production Ready
