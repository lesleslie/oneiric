# Oneiric Service Dependencies

This document describes the service dependencies and integration points for Oneiric in the ecosystem architecture.

## Overview

Oneiric is designed as a **standalone resolver** that can operate independently or integrate with other ecosystem services. It has no required runtime dependencies but provides optional integrations for enhanced functionality.

---

## Required Services

**None** - Oneiric is fully standalone and requires no external services to operate.

### Core Capabilities (Standalone)

- **Configuration Management**: Local file-based configuration with YAML/TOML/JSON support
- **Component Resolution**: 4-tier precedence resolver (explicit → stack → priority → registration)
- **Lifecycle Management**: Pause/resume/drain states with SQLite-backed activity store
- **Local Adapters**: 80+ built-in adapters for databases, queues, storage, messaging, etc.
- **Event Dispatcher**: Topic-based pub/sub with filters, fan-out, and retry policies
- **Workflow Orchestration**: DAG execution with checkpoints and telemetry
- **Observability**: Structured logging, runtime telemetry, and health snapshots

Oneiric can run completely offline with local configuration and adapters only.

---

## Optional Integrations

### Mahavishnu (Orchestrator)

**Role**: Orchestrator - Coordinates workflows across repositories

**Integration Purpose**:
- Component resolution for multi-repo workflows
- Cross-repository adapter sharing
- Workflow execution coordination
- Distributed task scheduling

**Protocol**: MCP (Model Context Protocol)

**Connection Details**:
```bash
# Default URL
http://localhost:8680/mcp

# Enable in Oneiric
export MAHAVISHNU_MCP_URL="http://localhost:8680/mcp"
```

**Features**:
- **Remote Resolution**: Resolve adapters from Mahavishnu's registry
- **Workflow Routing**: Route workflows through Mahavishnu orchestrator
- **Pool Management**: Execute tasks on Mahavishnu worker pools
- **Memory Aggregation**: Cross-pool memory search and retrieval

**Health Check**:
```bash
# Check Mahavishnu connection
oneiric health --probe --json

# View remote status
oneiric remote-status --json
```

**When to Use**:
- Multi-repository workflow orchestration
- Distributed task execution
- Cross-service component sharing
- Production deployments with Mahavishnu

**Startup Order**: Oneiric → Mahavishnu (Oneiric must be running before Mahavishnu connects)

---

### Dhruva (Curator)

**Role**: Asset Manager - Manages adapter distribution and remote manifests

**Integration Purpose**:
- Remote adapter distribution
- Signed manifest delivery
- Adapter version management
- Cloud-based configuration backup

**Protocol**: MCP (Model Context Protocol)

**Connection Details**:
```bash
# Default URL
http://localhost:8683/mcp

# Enable in Oneiric
export DHruVA_MCP_URL="http://localhost:8683/mcp"
```

**Features**:
- **Remote Manifests**: Fetch signed manifests from Dhruva
- **Adapter Registry**: Discover and install adapters remotely
- **Version Control**: Track adapter versions and dependencies
- **Signature Verification**: ED25519 signature validation for security

**Health Check**:
```bash
# Sync from Dhruva manifest
oneiric remote-sync \
  --manifest docs/sample_remote_manifest.yaml \
  --refresh-interval 120

# Verify signature
oneiric manifest verify --input manifest.json
```

**When to Use**:
- Production deployments with remote adapter management
- Multi-environment configuration synchronization
- Signed manifest delivery for security
- Adapter distribution across teams

**Startup Order**: Oneiric → Dhruva (Oneiric fetches from Dhruva on startup)

---

### Cloud Storage (Configuration Backup)

**Role**: Optional backup for remote configuration

**Supported Providers**:
- **AWS S3**: `s3://bucket-name/path/to/config.yaml`
- **Azure Blob Storage**: `azure://container/path/to/config.yaml`
- **Google Cloud Storage**: `gs://bucket-name/path/to/config.yaml`

**Integration Purpose**:
- Remote configuration backup
- Disaster recovery
- Multi-environment synchronization
- Configuration versioning

**Configuration**:
```yaml
# oneiric.yaml
remote_config:
  enabled: true
  provider: "s3"  # or "azure", "gcs"
  url: "s3://my-bucket/oneiric/config.yaml"
  sync_interval: 300  # seconds
```

**Environment Variables**:
```bash
# AWS S3
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Azure Blob
export AZURE_STORAGE_ACCOUNT="your-account"
export AZURE_STORAGE_KEY="your-key"

# GCS
export GOOGLE_CLOUD_PROJECT="your-project"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

**When to Use**:
- Production configuration backup
- Disaster recovery
- Multi-region deployment
- Configuration audit trail

**Required**: Optional - Oneiric works without cloud storage

---

### Optional MCP Integrations

Oneiric can connect to any MCP-compliant service for extended functionality:

**Session-Buddy (Session Manager)**
- **URL**: http://localhost:8678/mcp
- **Purpose**: Session context and state management
- **Use Case**: Share session state across workflows

**Akosha (Diviner)**
- **URL**: http://localhost:8682/mcp
- **Purpose**: Knowledge graph and memory aggregation
- **Use Case**: Cross-session memory retrieval

**Crackerjack (Inspector)**
- **URL**: http://localhost:8676/mcp
- **Purpose**: Quality checks and CI/CD integration
- **Use Case**: Automated quality gates

---

## Startup Order

### Standalone Mode (Lite)
```
Oneiric only
No external dependencies
```

### Ecosystem Mode (Standard)
```
1. Oneiric (Resolver) - must start first
2. Dhruva (Curator) - optional, for remote manifests
3. Mahavishnu (Orchestrator) - optional, for workflow coordination
```

**Rationale**: Oneiric must be running before other services can connect to it for component resolution.

---

## Network Configuration

### Local Development
```bash
# All services on localhost
export ONEIRIC_HOST="127.0.0.1"
export ONEIRIC_PORT=8681
export MAHAVISHNU_MCP_URL="http://localhost:8680/mcp"
export DHruVA_MCP_URL="http://localhost:8683/mcp"
```

### Production Deployment
```bash
# Use explicit interfaces
export ONEIRIC_HOST="10.0.1.10"  # Explicit IP
export ONEIRIC_PORT=8681
export MAHAVISHNU_MCP_URL="http://mahavishnu:8680/mcp"
export DHruVA_MCP_URL="http://dhruva:8683/mcp"
```

**Security Note**: For production, bind to explicit interfaces (not `0.0.0.0`) and use firewall rules to restrict access.

---

## Health and Readiness

### Health Endpoints

```bash
# Liveness probe (is the process running?)
oneiric health --liveness

# Readiness probe (are all dependencies ready?)
oneiric health --probe

# Full health snapshot
oneiric health --json
```

### Health Check Response

```json
{
  "status": "healthy",
  "timestamp": "2025-02-09T12:00:00Z",
  "dependencies": {
    "mahavishnu": {
      "status": "connected",
      "url": "http://localhost:8680/mcp",
      "latency_ms": 5
    },
    "dhruva": {
      "status": "connected",
      "url": "http://localhost:8683/mcp",
      "latency_ms": 3
    }
  },
  "domains": {
    "adapter": {"registered": 85, "active": 83},
    "service": {"registered": 5, "active": 5}
  }
}
```

---

## Troubleshooting

### "Cannot resolve adapter"

**Symptoms**:
```
Error: No adapter found for key 'postgresql'
```

**Diagnosis**:
```bash
# Check adapter registry
oneiric list --domain adapter --shadowed

# Check remote sync status
oneiric remote-status --json
```

**Solutions**:
1. **Adapter not registered**: Install adapter locally or enable remote resolution
   ```bash
   oneiric activate adapter postgresql --provider pgvector
   ```

2. **Remote resolution disabled**: Enable remote resolution
   ```bash
   export ONEIRIC_MODE=standard
   oneiric enable-remote --url http://localhost:8683/mcp
   ```

3. **Dhruva unreachable**: Check connection
   ```bash
   curl http://localhost:8683/mcp/health
   ```

---

### "Remote sync failed"

**Symptoms**:
```
Error: Failed to sync from remote manifest
```

**Diagnosis**:
```bash
# Verify manifest URL
oneiric remote-sync --manifest /path/to/manifest.yaml --verify-only

# Check signature
oneiric manifest verify --input manifest.json
```

**Solutions**:
1. **Invalid manifest**: Verify manifest syntax
   ```bash
   oneiric manifest validate --input manifest.yaml
   ```

2. **Signature verification failed**: Check public key
   ```bash
   export ONEIRIC_MANIFEST_PUBLIC_KEY="/path/to/public_key.pem"
   ```

3. **Network error**: Check connectivity
   ```bash
   curl -I http://localhost:8683/mcp/manifest
   ```

---

### "Component not responding"

**Symptoms**:
```
Error: Adapter 'postgresql' not responding
```

**Diagnosis**:
```bash
# Check activity state
oneiric activity --domain adapter --key postgresql

# Check health
oneiric health --probe --json
```

**Solutions**:
1. **Paused state**: Resume component
   ```bash
   oneiric resume adapter postgresql
   ```

2. **Draining state**: Wait for drain to complete
   ```bash
   oneiric activity --domain adapter --key postgresql
   ```

3. **Lifecycle error**: Check logs
   ```bash
   oneiric status --domain adapter --key postgresql --json
   ```

---

### "Mahavishnu connection refused"

**Symptoms**:
```
Error: Connection refused to Mahavishnu MCP server
```

**Diagnosis**:
```bash
# Check Mahavishnu status
curl http://localhost:8680/mcp/health

# Check Oneiric remote status
oneiric remote-status --json
```

**Solutions**:
1. **Mahavishnu not running**: Start Mahavishnu
   ```bash
   mahavishnu mcp start
   ```

2. **Wrong URL**: Update configuration
   ```bash
   export MAHAVISHNU_MCP_URL="http://localhost:8680/mcp"
   ```

3. **Firewall blocking**: Check network rules
   ```bash
   # Allow TCP 8680
   sudo ufw allow 8680/tcp
   ```

---

## Configuration Examples

### Lite Mode (Standalone)
```yaml
# oneiric.yaml
mode: "lite"
remote:
  enabled: false
adapters:
  postgresql:
    provider: pgvector
    connection_string: "postgresql://localhost/db"
```

### Standard Mode (With Dhruva)
```yaml
# oneiric.yaml
mode: "standard"
remote:
  enabled: true
  url: "http://localhost:8683/mcp"
  manifest: "docs/sample_remote_manifest.yaml"
  refresh_interval: 120
adapters:
  postgresql:
    provider: pgvector
    connection_string: "postgresql://localhost/db"
```

### Production Mode (Full Ecosystem)
```yaml
# oneiric.yaml
mode: "standard"
remote:
  enabled: true
  url: "http://dhruva:8683/mcp"
  manifest: "s3://my-bucket/oneiric/manifest.json"
  refresh_interval: 300
cloud_backup:
  enabled: true
  provider: "s3"
  url: "s3://my-bucket/oneiric/config.yaml"
  sync_interval: 600
orchestrator:
  mahavishnu_url: "http://mahavishnu:8680/mcp"
```

---

## Monitoring and Observability

### Metrics to Monitor

**Dependency Health**:
- Mahavishnu connection status
- Dhruva sync success rate
- Remote manifest fetch latency

**Component Health**:
- Adapter registration count
- Service active/draining/paused counts
- Lifecycle state transitions

**Performance**:
- Resolution latency (p50, p95, p99)
- Remote sync duration
- Health check response time

### Logging

```bash
# Enable debug logging
export ONEIRIC_LOG_LEVEL="debug"

# View logs
tail -f .oneiric_cache/runtime_telemetry.json

# Export logs
oneiric status --json > oneiric_status.json
```

### Dashboards

Recommended dashboards:
- **Dependency Health**: Mahavishnu/Dhruva connection status
- **Component Lifecycle**: Active/paused/drained component counts
- **Resolution Performance**: Latency histograms
- **Remote Sync**: Success rate, duration, error breakdown

---

## Security Considerations

### Network Security
- **Local Dev**: Bind to `127.0.0.1` only
- **Production**: Bind to explicit interface with firewall rules
- **MCP Connections**: Use TLS in production

### Authentication
- **Mahavishnu**: JWT-based authentication
- **Dhruva**: API token or mutual TLS
- **Cloud Storage**: IAM roles or service accounts

### Signature Verification
- **Remote Manifests**: ED25519 signatures required
- **Public Key**: Configure via `ONEIRIC_MANIFEST_PUBLIC_KEY`
- **Verification Failure**: Reject unsigned manifests

### Secrets Management
- **Never Commit Secrets**: Use environment variables
- **Rotate Secrets**: Use `oneiric secrets rotate`
- **Secret Providers**: Infisical, AWS Secrets Manager, GCP Secret Manager

---

## Next Steps

- [Operational Modes Guide](../guides/operational-modes.md) - Lite vs Standard mode setup
- [Configuration Reference](config.md) - Complete configuration options
- [MCP Integration](../integration/mcp.md) - MCP server setup and protocol
- [Troubleshooting Guide](../runbooks/TROUBLESHOOTING.md) - Common issues and solutions
- [Production Deployment](../deployment/PRODUCTION.md) - Production best practices

---

**Last Updated**: 2025-02-09
**Oneiric Version**: v0.3.3
**Status**: Production Ready
