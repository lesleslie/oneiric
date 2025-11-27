# Systemd Service Deployment Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-26
**Target:** Oneiric v0.1.0+ on Linux with systemd

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Systemd Service Configuration](#systemd-service-configuration)
5. [Installation](#installation)
6. [Service Management](#service-management)
7. [Configuration](#configuration)
8. [Logging](#logging)
9. [Security Hardening](#security-hardening)
10. [Monitoring Integration](#monitoring-integration)
11. [Troubleshooting](#troubleshooting)

---

## Overview

Running Oneiric as a systemd service provides:

- **Automatic Startup:** Service starts on boot
- **Process Supervision:** Automatic restart on failure
- **Resource Limits:** CPU/memory controls via cgroups
- **Security Isolation:** User/group separation, restricted filesystem access
- **Logging Integration:** Centralized logging via journald
- **Health Monitoring:** Watchdog support for hanging processes

---

## Prerequisites

### System Requirements

- Linux distribution with systemd (Ubuntu 20.04+, Debian 11+, RHEL 8+, etc.)
- Python 3.14+ installed
- UV package manager installed
- Non-root user for running the service

### Install UV

```bash
# Install UV package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify installation
uv --version
```

### Create Service User

```bash
# Create dedicated user (no login shell)
sudo useradd -r -s /bin/false -m -d /opt/oneiric oneiric

# Verify user created
id oneiric
```

---

## Quick Start

### 1. Install Oneiric

```bash
# Switch to oneiric user
sudo -u oneiric -s

# Navigate to installation directory
cd /opt/oneiric

# Clone repository (or download release)
git clone https://github.com/your-org/oneiric.git .

# Install with UV
uv sync --frozen

# Verify installation
uv run python -m oneiric.cli --version

# Exit back to your user
exit
```

### 2. Create Service File

```bash
# Copy service template
sudo cp systemd/oneiric.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable oneiric

# Start service
sudo systemctl start oneiric

# Check status
sudo systemctl status oneiric
```

### 3. Verify Service

```bash
# Check service health
sudo -u oneiric uv run python -m oneiric.cli health --probe

# View logs
sudo journalctl -u oneiric -f
```

---

## Systemd Service Configuration

### Basic Service File

**File:** `/etc/systemd/system/oneiric.service`

```ini
[Unit]
Description=Oneiric - Universal Resolution Layer
Documentation=https://github.com/your-org/oneiric
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=oneiric
Group=oneiric

# Working directory
WorkingDirectory=/opt/oneiric

# Environment
Environment="PATH=/opt/oneiric/.local/bin:/usr/local/bin:/usr/bin"
Environment="ONEIRIC_CONFIG=/opt/oneiric/settings"
Environment="LOG_LEVEL=INFO"
Environment="ONEIRIC_LOG_FORMAT=json"

# Environment file (optional - for secrets)
EnvironmentFile=-/etc/oneiric/environment

# Start command
ExecStart=/opt/oneiric/.local/bin/uv run python -m oneiric.cli orchestrate \
  --manifest /opt/oneiric/settings/manifest.yaml \
  --refresh-interval 120

# Pre-start health check
ExecStartPre=/opt/oneiric/.local/bin/uv run python -m oneiric.cli health --probe

# Reload command (graceful restart)
ExecReload=/bin/kill -HUP $MAINPID

# Restart policy
Restart=on-failure
RestartSec=10s
StartLimitBurst=5
StartLimitInterval=300s

# Timeout
TimeoutStartSec=60s
TimeoutStopSec=30s

# Watchdog (optional - requires application support)
# WatchdogSec=30s

# Standard output/error to journal
StandardOutput=journal
StandardError=journal
SyslogIdentifier=oneiric

# Resource limits
LimitNOFILE=65536
LimitNPROC=4096

# Nice priority (lower = higher priority)
Nice=-5

[Install]
WantedBy=multi-user.target
```

### Advanced Service File (Production)

**File:** `/etc/systemd/system/oneiric.service`

```ini
[Unit]
Description=Oneiric - Universal Resolution Layer (Production)
Documentation=https://github.com/your-org/oneiric
After=network-online.target
Wants=network-online.target
# Add dependencies if needed
# Requires=redis.service postgresql.service

[Service]
Type=exec
User=oneiric
Group=oneiric

# Working directory
WorkingDirectory=/opt/oneiric

# Environment
Environment="PATH=/opt/oneiric/.local/bin:/usr/local/bin:/usr/bin"
Environment="ONEIRIC_CONFIG=/opt/oneiric/settings"
Environment="LOG_LEVEL=INFO"
Environment="ONEIRIC_LOG_FORMAT=json"
Environment="OTEL_SERVICE_NAME=oneiric"
Environment="PROMETHEUS_METRICS_PORT=9090"

# Environment file for secrets
EnvironmentFile=-/etc/oneiric/environment

# Start command
ExecStart=/opt/oneiric/.local/bin/uv run python -m oneiric.cli orchestrate \
  --manifest /opt/oneiric/settings/manifest.yaml \
  --refresh-interval 120

# Pre-start validation
ExecStartPre=/bin/sh -c 'test -r /opt/oneiric/settings/manifest.yaml'
ExecStartPre=/opt/oneiric/.local/bin/uv run python -m oneiric.cli health --probe

# Reload (graceful restart)
ExecReload=/bin/kill -HUP $MAINPID

# Post-stop cleanup
ExecStopPost=/bin/sh -c 'rm -f /var/run/oneiric.pid'

# Restart policy
Restart=on-failure
RestartSec=10s
StartLimitBurst=5
StartLimitInterval=300s

# Timeout
TimeoutStartSec=60s
TimeoutStopSec=30s

# Watchdog
# WatchdogSec=30s

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=oneiric

# Resource limits (cgroups v2)
LimitNOFILE=65536
LimitNPROC=4096
MemoryMax=2G
CPUQuota=200%  # 2 cores

# Nice priority
Nice=-5

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/oneiric/.oneiric_cache /opt/oneiric/logs
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM

# Capabilities (drop all, add only what's needed)
CapabilityBoundingSet=
# AmbientCapabilities=CAP_NET_BIND_SERVICE  # Only if binding to <1024

[Install]
WantedBy=multi-user.target
```

---

## Installation

### Manual Installation

```bash
# 1. Create oneiric user
sudo useradd -r -s /bin/false -m -d /opt/oneiric oneiric

# 2. Install Oneiric
sudo -u oneiric bash << 'EOF'
cd /opt/oneiric
git clone https://github.com/your-org/oneiric.git .
uv sync --frozen
EOF

# 3. Create directories
sudo mkdir -p /opt/oneiric/{settings,logs,.oneiric_cache}
sudo chown -R oneiric:oneiric /opt/oneiric

# 4. Copy configuration
sudo cp -r settings/* /opt/oneiric/settings/

# 5. Install service file
sudo cp systemd/oneiric.service /etc/systemd/system/

# 6. Create environment file (optional)
sudo mkdir -p /etc/oneiric
sudo touch /etc/oneiric/environment
sudo chmod 600 /etc/oneiric/environment

# 7. Reload systemd
sudo systemctl daemon-reload

# 8. Enable and start service
sudo systemctl enable oneiric
sudo systemctl start oneiric

# 9. Verify
sudo systemctl status oneiric
```

### Automated Installation Script

**File:** `scripts/install-systemd.sh`

```bash
#!/bin/bash
set -e

# Install Oneiric as systemd service

echo "==> Creating oneiric user..."
if ! id -u oneiric >/dev/null 2>&1; then
    sudo useradd -r -s /bin/false -m -d /opt/oneiric oneiric
fi

echo "==> Installing Oneiric..."
sudo -u oneiric bash << 'EOF'
cd /opt/oneiric
if [ ! -d .git ]; then
    git clone https://github.com/your-org/oneiric.git .
fi
uv sync --frozen
EOF

echo "==> Setting up directories..."
sudo mkdir -p /opt/oneiric/{settings,logs,.oneiric_cache}
sudo chown -R oneiric:oneiric /opt/oneiric

echo "==> Installing service file..."
sudo cp systemd/oneiric.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "==> Enabling service..."
sudo systemctl enable oneiric

echo "==> Starting service..."
sudo systemctl start oneiric

echo "==> Service status:"
sudo systemctl status oneiric

echo "==> Installation complete!"
echo "View logs: sudo journalctl -u oneiric -f"
```

---

## Service Management

### Start/Stop/Restart

```bash
# Start service
sudo systemctl start oneiric

# Stop service
sudo systemctl stop oneiric

# Restart service
sudo systemctl restart oneiric

# Graceful reload (send HUP signal)
sudo systemctl reload oneiric

# Check status
sudo systemctl status oneiric

# Is service active?
sudo systemctl is-active oneiric

# Is service enabled?
sudo systemctl is-enabled oneiric
```

### Enable/Disable

```bash
# Enable (start on boot)
sudo systemctl enable oneiric

# Disable (don't start on boot)
sudo systemctl disable oneiric

# Enable and start
sudo systemctl enable --now oneiric
```

### Service Dependencies

```bash
# View service dependencies
sudo systemctl list-dependencies oneiric

# View reverse dependencies (what depends on this)
sudo systemctl list-dependencies --reverse oneiric
```

---

## Configuration

### Environment File

**File:** `/etc/oneiric/environment`

```bash
# Oneiric environment variables
# This file is sourced by systemd (not a shell script!)

# Core configuration
ONEIRIC_CONFIG=/opt/oneiric/settings
ONEIRIC_STACK_ORDER=production:100,staging:50,default:0

# Logging
LOG_LEVEL=INFO
ONEIRIC_LOG_FORMAT=json

# OpenTelemetry
OTEL_SERVICE_NAME=oneiric-production
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317

# Monitoring
PROMETHEUS_METRICS_PORT=9090

# Secrets (DO NOT COMMIT!)
API_KEY=your-secret-api-key
REDIS_PASSWORD=your-redis-password
```

**Permissions:**

```bash
# Secure environment file
sudo chmod 600 /etc/oneiric/environment
sudo chown root:root /etc/oneiric/environment
```

### Settings Directory

```bash
# Settings structure
/opt/oneiric/settings/
├── app.yml
├── adapters.yml
├── services.yml
├── tasks.yml
├── events.yml
├── workflows.yml
└── manifest.yaml

# Permissions
sudo chown -R oneiric:oneiric /opt/oneiric/settings
sudo chmod -R 640 /opt/oneiric/settings/*.yml
```

---

## Logging

### View Logs

```bash
# View all logs
sudo journalctl -u oneiric

# Follow logs (tail -f)
sudo journalctl -u oneiric -f

# Last 100 lines
sudo journalctl -u oneiric -n 100

# Since 1 hour ago
sudo journalctl -u oneiric --since "1 hour ago"

# Today's logs
sudo journalctl -u oneiric --since today

# Filter by priority (err, warning, info, debug)
sudo journalctl -u oneiric -p err

# JSON output
sudo journalctl -u oneiric -o json-pretty

# Export logs
sudo journalctl -u oneiric > oneiric.log
```

### Log Rotation

Journald automatically handles log rotation, but you can configure it:

**File:** `/etc/systemd/journald.conf`

```ini
[Journal]
SystemMaxUse=500M
SystemKeepFree=1G
SystemMaxFileSize=50M
MaxRetentionSec=1month
```

Apply changes:

```bash
sudo systemctl restart systemd-journald
```

### Persistent Logging

```bash
# Enable persistent logging
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald

# Verify
sudo journalctl --disk-usage
```

---

## Security Hardening

### File Permissions

```bash
# Service file permissions
sudo chmod 644 /etc/systemd/system/oneiric.service
sudo chown root:root /etc/systemd/system/oneiric.service

# Environment file permissions
sudo chmod 600 /etc/oneiric/environment
sudo chown root:root /etc/oneiric/environment

# Application directory
sudo chown -R oneiric:oneiric /opt/oneiric
sudo chmod -R 755 /opt/oneiric
```

### Systemd Security Features

The advanced service file includes:

- **`NoNewPrivileges=true`** - Prevent privilege escalation
- **`PrivateTmp=true`** - Private /tmp directory
- **`ProtectSystem=strict`** - Read-only filesystem (except explicit paths)
- **`ProtectHome=true`** - Hide /home directories
- **`ReadWritePaths=`** - Allow writes only to specific paths
- **`CapabilityBoundingSet=`** - Drop all Linux capabilities
- **`SystemCallFilter=@system-service`** - Restrict system calls
- **`RestrictAddressFamilies=`** - Limit network protocols
- **`MemoryDenyWriteExecute=true`** - Prevent code execution in writable memory

### AppArmor/SELinux

**AppArmor Profile** (Ubuntu/Debian):

```bash
# Create profile
sudo nano /etc/apparmor.d/opt.oneiric

# Profile content
#include <tunables/global>

/opt/oneiric/bin/oneiric {
  #include <abstractions/base>
  #include <abstractions/python>

  /opt/oneiric/** r,
  /opt/oneiric/.oneiric_cache/** rw,
  /opt/oneiric/logs/** rw,
  /opt/oneiric/settings/** r,

  # Network
  network inet stream,
  network inet6 stream,

  # Deny everything else
  deny /home/** rw,
  deny /root/** rw,
}

# Load profile
sudo apparmor_parser -r /etc/apparmor.d/opt.oneiric
```

---

## Monitoring Integration

### Prometheus Node Exporter

```bash
# Install node_exporter
sudo apt-get install prometheus-node-exporter

# Oneiric metrics are exposed on :9090/metrics
# Scrape with Prometheus

# Example prometheus.yml
scrape_configs:
  - job_name: 'oneiric'
    static_configs:
      - targets: ['localhost:9090']
```

### Systemd Metrics

```bash
# View service metrics
systemd-cgtop

# Service CPU/memory usage
systemctl status oneiric

# Detailed resource usage
systemctl show oneiric -p CPUUsageNSec -p MemoryCurrent

# All properties
systemctl show oneiric
```

### Alerting on Service Failure

**File:** `/etc/systemd/system/oneiric-failure-notify.service`

```ini
[Unit]
Description=Oneiric Failure Notification
After=oneiric.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/notify-failure.sh oneiric

[Install]
WantedBy=multi-user.target
```

**Script:** `/usr/local/bin/notify-failure.sh`

```bash
#!/bin/bash
SERVICE=$1
STATUS=$(systemctl is-failed $SERVICE)

if [ "$STATUS" = "failed" ]; then
    # Send alert (email, Slack, PagerDuty, etc.)
    echo "Service $SERVICE failed at $(date)" | mail -s "Alert: $SERVICE Failed" admin@example.com
fi
```

**Add OnFailure hook:**

```ini
# In oneiric.service
[Unit]
OnFailure=oneiric-failure-notify.service
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check status for errors
sudo systemctl status oneiric

# View detailed logs
sudo journalctl -u oneiric -n 50

# Test command manually
sudo -u oneiric bash
cd /opt/oneiric
uv run python -m oneiric.cli orchestrate --manifest /opt/oneiric/settings/manifest.yaml
```

### Permission Denied Errors

```bash
# Check file permissions
ls -la /opt/oneiric

# Fix ownership
sudo chown -R oneiric:oneiric /opt/oneiric

# Check directory access
sudo -u oneiric test -r /opt/oneiric/settings/manifest.yaml && echo "OK" || echo "FAIL"
```

### Service Crashes on Start

```bash
# Increase start timeout
sudo systemctl edit oneiric

# Add:
[Service]
TimeoutStartSec=120s

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart oneiric
```

### High Memory Usage

```bash
# Check current usage
systemctl status oneiric | grep Memory

# Set memory limit
sudo systemctl edit oneiric

# Add:
[Service]
MemoryMax=4G
MemoryHigh=3G

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart oneiric
```

### Service Keeps Restarting

```bash
# Check restart count
systemctl show oneiric -p NRestarts

# View crash history
sudo journalctl -u oneiric | grep "Failed with result"

# Disable auto-restart temporarily
sudo systemctl edit oneiric

# Add:
[Service]
Restart=no

# Debug manually
sudo -u oneiric bash
cd /opt/oneiric
uv run python -m oneiric.cli health --probe
```

---

## Next Steps

- [Docker Deployment](./DOCKER_DEPLOYMENT.md) - Container-based deployment
- [Kubernetes Deployment](./KUBERNETES_DEPLOYMENT.md) - Orchestrated deployment
- [Monitoring Setup](../monitoring/MONITORING_SETUP.md) - Configure metrics and alerting
- [Runbooks](../runbooks/README.md) - Incident response procedures
