# AlertManager Configuration for Oneiric

**Last Updated:** 2025-11-26
**Status:** Production Ready
**Maintainer:** Platform Team

______________________________________________________________________

## Table of Contents

1. \[[#overview|Overview]\]
1. \[[#quick-start|Quick Start]\]
1. \[[#installation|Installation]\]
1. \[[#configuration|Configuration]\]
1. \[[#routing-rules|Routing Rules]\]
1. \[[#notification-channels|Notification Channels]\]
1. \[[#escalation-policies|Escalation Policies]\]
1. \[[#silencing-alerts|Silencing Alerts]\]
1. \[[#troubleshooting|Troubleshooting]\]
1. \[[#best-practices|Best Practices]\]

______________________________________________________________________

## Overview

AlertManager handles alerts from Prometheus and Loki, routing them to appropriate notification channels (Slack, PagerDuty, email) based on severity and component.

### Key Features

- **Deduplication:** Prevents alert storms
- **Grouping:** Aggregates related alerts
- **Routing:** Directs alerts to correct teams
- **Silencing:** Temporarily mute alerts during maintenance
- **Escalation:** Auto-escalates critical alerts if unacknowledged

______________________________________________________________________

## Quick Start

Use a managed Alertmanager (or your existing alerting stack) and apply the configuration from `deployment/monitoring/alertmanager/`. Docker/Kubernetes walkthroughs have been removed.

### Test Alert Routing

```bash
# Send test alert
curl -X POST http://localhost:9093/api/v2/alerts \
  -H 'Content-Type: application/json' \
  -d '[{
    "labels": {
      "alertname": "TestAlert",
      "severity": "critical",
      "component": "test"
    },
    "annotations": {
      "summary": "Test alert for routing verification"
    }
  }]'

# Verify notification received (check Slack/email)
```

______________________________________________________________________

## Installation

Provision Alertmanager using your platform defaults and mount `deployment/monitoring/alertmanager/alertmanager.yml` plus any notification templates.

### Binary Installation

```bash
# Download AlertManager
wget https://github.com/prometheus/alertmanager/releases/download/v0.26.0/alertmanager-0.26.0.linux-amd64.tar.gz
tar xvfz alertmanager-*.tar.gz
cd alertmanager-*

# Start AlertManager
./alertmanager --config.file=alertmanager.yml &
```

______________________________________________________________________

## Configuration

### Main Configuration

**File:** `deployment/monitoring/alertmanager/alertmanager.yml`

```yaml
# AlertManager Configuration for Oneiric
# Version: 1.0
# Last Updated: 2025-11-26

global:
  # Global defaults
  resolve_timeout: 5m
  slack_api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
  pagerduty_url: 'https://events.pagerduty.com/v2/enqueue'

# Templates for notification formatting
templates:
  - '/etc/alertmanager/templates/*.tmpl'

# Routing tree (how alerts are routed)
route:
  # Default receiver
  receiver: 'platform-team'

  # Group alerts by these labels
  group_by: ['alertname', 'component', 'domain']

  # Wait time before sending initial notification
  group_wait: 10s

  # Wait time before sending notification about new alerts in group
  group_interval: 10s

  # Minimum time between re-notifications for same alert group
  repeat_interval: 12h

  # Child routes (match-based routing)
  routes:
    # Critical alerts → Page on-call + Slack
    - match:
        severity: critical
      receiver: 'oncall-page'
      group_wait: 5s
      group_interval: 5s
      repeat_interval: 4h
      continue: true  # Also send to platform team

    # Security alerts → Security team immediately
    - match:
        component: security
      receiver: 'security-team'
      group_wait: 0s
      group_interval: 5m
      repeat_interval: 1h
      continue: false  # Don't route to platform team

    # Warning alerts → Slack only
    - match:
        severity: warning
      receiver: 'platform-slack'
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 24h

    # Info alerts → Low-priority channel
    - match:
        severity: info
      receiver: 'platform-info'
      group_wait: 5m
      group_interval: 1h
      repeat_interval: 24h

    # Resolver alerts
    - match:
        component: resolver
      receiver: 'backend-team'
      repeat_interval: 8h

    # Lifecycle alerts
    - match:
        component: lifecycle
      receiver: 'devops-team'
      repeat_interval: 8h

    # Remote sync alerts
    - match:
        component: remote
      receiver: 'infrastructure-team'
      repeat_interval: 6h

# Inhibition rules (suppress alerts based on other active alerts)
inhibit_rules:
  # Inhibit warning if critical is firing
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'component']

  # Inhibit info if warning is firing
  - source_match:
      severity: 'warning'
    target_match:
      severity: 'info'
    equal: ['alertname', 'component']

  # Inhibit component alerts if system is down
  - source_match:
      alertname: 'OneiricDown'
    target_match_re:
      alertname: 'Oneiric.*'

  # Inhibit resolution alerts if lifecycle is failing
  - source_match:
      alertname: 'OneiricLifecycleSwapFailureRateHigh'
    target_match:
      alertname: 'OneiricResolutionFailureRateHigh'
    equal: ['domain']

# Notification receivers
receivers:
  # On-call paging (critical alerts)
  - name: 'oncall-page'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_SERVICE_KEY'
        description: '{{ .GroupLabels.alertname }}: {{ .GroupLabels.summary }}'
        details:
          severity: '{{ .GroupLabels.severity }}'
          component: '{{ .GroupLabels.component }}'
          firing_count: '{{ .Alerts.Firing | len }}'
          runbook: '{{ .CommonAnnotations.runbook_url }}'
    slack_configs:
      - channel: '#oncall-critical'
        title: '🚨 CRITICAL: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
        send_resolved: true

  # Security team (immediate notification)
  - name: 'security-team'
    email_configs:
      - to: 'security@example.com'
        headers:
          Subject: '🔐 SECURITY ALERT: {{ .GroupLabels.alertname }}'
    slack_configs:
      - channel: '#security-alerts'
        title: '🔐 SECURITY: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
        color: '#ff0000'
        send_resolved: true
    pagerduty_configs:
      - service_key: 'YOUR_SECURITY_PAGERDUTY_KEY'
        severity: 'critical'

  # Platform team (default)
  - name: 'platform-team'
    slack_configs:
      - channel: '#platform-alerts'
        title: '{{ .GroupLabels.severity | toUpper }}: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
        send_resolved: true
    email_configs:
      - to: 'platform@example.com'
        headers:
          Subject: '[{{ .GroupLabels.severity }}] {{ .GroupLabels.alertname }}'

  # Platform Slack only (warnings)
  - name: 'platform-slack'
    slack_configs:
      - channel: '#platform-warnings'
        title: '⚠️ WARNING: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
        color: '#ff9900'
        send_resolved: true

  # Platform info channel (low priority)
  - name: 'platform-info'
    slack_configs:
      - channel: '#platform-info'
        title: 'ℹ️ INFO: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
        color: '#0099ff'
        send_resolved: false

  # Backend team (resolution issues)
  - name: 'backend-team'
    slack_configs:
      - channel: '#backend-alerts'
        title: '🔍 RESOLVER: {{ .GroupLabels.alertname }}'
        send_resolved: true
    email_configs:
      - to: 'backend@example.com'

  # DevOps team (lifecycle issues)
  - name: 'devops-team'
    slack_configs:
      - channel: '#devops-alerts'
        title: '♻️ LIFECYCLE: {{ .GroupLabels.alertname }}'
        send_resolved: true
    email_configs:
      - to: 'devops@example.com'

  # Infrastructure team (remote sync)
  - name: 'infrastructure-team'
    slack_configs:
      - channel: '#infra-alerts'
        title: '☁️ REMOTE: {{ .GroupLabels.alertname }}'
        send_resolved: true
    email_configs:
      - to: 'infrastructure@example.com'
```

______________________________________________________________________

## Routing Rules

### Severity-Based Routing

| Severity | Receiver | Wait Time | Repeat Interval | Actions |
|----------|----------|-----------|-----------------|---------|
| **critical** | oncall-page | 5s | 4h | Page + Slack |
| **warning** | platform-slack | 30s | 24h | Slack only |
| **info** | platform-info | 5m | 24h | Slack (no resolve) |

### Component-Based Routing

| Component | Receiver | Team | Channel |
|-----------|----------|------|---------|
| **security** | security-team | Security | #security-alerts |
| **resolver** | backend-team | Backend | #backend-alerts |
| **lifecycle** | devops-team | DevOps | #devops-alerts |
| **remote** | infrastructure-team | Infrastructure | #infra-alerts |

### Custom Routing Example

```yaml
routes:
  # High SLA impact → Escalate immediately
  - match:
      sla_impact: high
    receiver: 'oncall-page'
    group_wait: 0s
    repeat_interval: 2h

  # Specific domain failures
  - match:
      domain: adapter
      component: resolver
    receiver: 'adapter-team'

  # Business hours vs off-hours
  - match:
      time: 'weekdays'
    receiver: 'business-hours-team'
  - match:
      time: 'nights-weekends'
    receiver: 'oncall-rotation'
```

______________________________________________________________________

## Notification Channels

### Slack

**Setup:**

1. **Create Slack App:** https://api.slack.com/apps
1. **Enable Incoming Webhooks**
1. **Add webhook URL to AlertManager config**

**Configuration:**

```yaml
slack_configs:
  - api_url: 'https://hooks.slack.com/services/T00/B00/REPLACE_ME'
    channel: '#alerts'
    username: 'AlertManager'
    icon_emoji: ':fire:'
    title: '{{ .GroupLabels.alertname }}'
    text: |
      *Summary:* {{ .CommonAnnotations.summary }}
      *Description:* {{ .CommonAnnotations.description }}
      *Runbook:* {{ .CommonAnnotations.runbook_url }}
      *Dashboard:* {{ .CommonAnnotations.dashboard_url }}
    send_resolved: true
    color: '{{ if eq .Status "firing" }}danger{{ else }}good{{ end }}'
```

### PagerDuty

**Setup:**

1. **Create PagerDuty Service**
1. **Get Integration Key**
1. **Add to AlertManager config**

**Configuration:**

```yaml
pagerduty_configs:
  - service_key: 'YOUR_PAGERDUTY_SERVICE_KEY'
    description: '{{ .CommonAnnotations.summary }}'
    severity: '{{ .GroupLabels.severity }}'
    details:
      component: '{{ .GroupLabels.component }}'
      alert_count: '{{ .Alerts.Firing | len }}'
      runbook: '{{ .CommonAnnotations.runbook_url }}'
```

### Email

**Configuration:**

```yaml
email_configs:
  - to: 'team@example.com'
    from: 'alerts@example.com'
    smarthost: 'smtp.gmail.com:587'
    auth_username: 'alerts@example.com'
    auth_password: 'app-password'
    headers:
      Subject: '[{{ .GroupLabels.severity }}] {{ .GroupLabels.alertname }}'
    html: |
      <h2>{{ .GroupLabels.alertname }}</h2>
      <p><strong>Severity:</strong> {{ .GroupLabels.severity }}</p>
      <p><strong>Summary:</strong> {{ .CommonAnnotations.summary }}</p>
      <p><strong>Description:</strong> {{ .CommonAnnotations.description }}</p>
      <p><a href="{{ .CommonAnnotations.runbook_url }}">Runbook</a></p>
```

### Webhook (Custom Integration)

```yaml
webhook_configs:
  - url: 'https://your-webhook.example.com/alerts'
    send_resolved: true
    http_config:
      bearer_token: 'YOUR_BEARER_TOKEN'
```

______________________________________________________________________

## Escalation Policies

### Basic Escalation

```yaml
# Alert fires → Slack
# After 15 min unresolved → Email
# After 30 min unresolved → Page

routes:
  - match:
      severity: critical
    receiver: 'slack-first'
    repeat_interval: 15m
    routes:
      - match:
          time: '>15m'
        receiver: 'email-escalation'
        routes:
          - match:
              time: '>30m'
            receiver: 'page-oncall'
```

### Time-Based Escalation

```yaml
# Business hours: Email → Slack
# Off-hours: Page immediately

routes:
  - match:
      severity: critical
    routes:
      - match:
          time: 'Mon-Fri 09:00-17:00'
        receiver: 'business-hours'
      - match:
          time: '*'
        receiver: 'oncall-page'
```

______________________________________________________________________

## Silencing Alerts

### Via UI

1. **Access AlertManager UI:** http://localhost:9093
1. **Click "Silences" tab**
1. **New Silence**
   - **Matchers:** `alertname="OneiricHealthCheck"`, `domain="adapter"`
   - **Start:** Now
   - **Duration:** 1h
   - **Creator:** Your name
   - **Comment:** "Maintenance window for adapter health checks"
1. **Create**

### Via CLI (amtool)

```bash
# Install amtool
go install github.com/prometheus/alertmanager/cmd/amtool@latest

# Create silence
amtool silence add \
  alertname="OneiricHealthCheck" \
  domain="adapter" \
  --duration=1h \
  --comment="Maintenance window"

# List active silences
amtool silence query

# Expire silence
amtool silence expire <silence-id>
```

### Via API

```bash
# Create silence
curl -X POST http://localhost:9093/api/v2/silences \
  -H 'Content-Type: application/json' \
  -d '{
    "matchers": [
      {"name": "alertname", "value": "OneiricHealthCheck", "isRegex": false},
      {"name": "domain", "value": "adapter", "isRegex": false}
    ],
    "startsAt": "2025-11-26T10:00:00Z",
    "endsAt": "2025-11-26T11:00:00Z",
    "createdBy": "admin",
    "comment": "Maintenance window"
  }'

# List silences
curl http://localhost:9093/api/v2/silences | jq

# Delete silence
curl -X DELETE http://localhost:9093/api/v2/silence/<id>
```

______________________________________________________________________

## Troubleshooting

### Alerts Not Firing

**Problem:** Expected alerts not reaching AlertManager

**Diagnosis:**

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Check alert rules loaded
curl http://localhost:9090/api/v1/rules

# Manually evaluate alert
curl 'http://localhost:9090/api/v1/query?query=<expr>'

# Check AlertManager status
curl http://localhost:9093/api/v2/status
```

**Solutions:**

1. **Alert rules not loaded:** Reload Prometheus config
1. **Alert expression not firing:** Test query in Prometheus UI
1. **AlertManager not reachable:** Check network connectivity

______________________________________________________________________

### Notifications Not Sent

**Problem:** Alerts firing but no notifications

**Diagnosis:**

```bash
# Check active alerts
curl http://localhost:9093/api/v2/alerts | jq

# Check AlertManager logs

# Test notification channel
curl -X POST http://localhost:9093/api/v2/alerts \
  -d '[{"labels":{"alertname":"Test"}}]'
```

**Solutions:**

1. **Webhook URL invalid:** Verify Slack/PagerDuty webhook
1. **Receiver misconfigured:** Check `alertmanager.yml` syntax
1. **Silenced:** Check active silences
1. **Routing mismatch:** Verify route matchers

______________________________________________________________________

## Best Practices

### 1. Alert Fatigue Prevention

- **Group related alerts:** Use `group_by`
- **Deduplicate:** Set appropriate `group_interval`
- **Tune thresholds:** Reduce false positives
- **Use inhibition rules:** Suppress redundant alerts

### 2. Notification Design

- **Actionable:** Include runbook links
- **Context-rich:** Add dashboard links, error details
- **Severity-appropriate:** Critical → Page, Warning → Slack
- **Resolve notifications:** Always send resolved alerts

### 3. Routing Strategy

- **Team-based:** Route by component ownership
- **Severity-based:** Different channels for critical/warning/info
- **Time-aware:** Business hours vs on-call
- **Escalation path:** Clear escalation policy

### 4. Maintenance Windows

- **Plan ahead:** Create silences before maintenance
- **Specific matchers:** Silence only affected alerts
- **Time-bound:** Set appropriate duration
- **Document:** Add clear comments

### 5. Testing

- **Test routing:** Send test alerts regularly
- **Verify channels:** Ensure all notification channels work
- **Simulate incidents:** Practice escalation procedures
- **Review logs:** Check AlertManager logs for errors

______________________________________________________________________

## Next Steps

1. **Configure notification channels:** Set up Slack/PagerDuty/email webhooks
1. **Customize routing:** Adjust routes for your team structure
1. **Test alerting:** Send test alerts and verify delivery
1. **Create runbooks:** Ensure all alerts link to runbooks
1. **Monitor AlertManager:** Add AlertManager metrics to dashboards

______________________________________________________________________

## Additional Resources

- **AlertManager Documentation:** https://prometheus.io/docs/alerting/latest/alertmanager/
- **amtool CLI Guide:** https://github.com/prometheus/alertmanager#amtool
- **Slack Setup:** https://api.slack.com/messaging/webhooks
- **PagerDuty Integration:** https://www.pagerduty.com/docs/guides/prometheus-integration-guide/
- **Oneiric Alert Rules:** `deployment/monitoring/prometheus/rules/alert_rules.yml`

______________________________________________________________________

**Document Version:** 1.0
**Last Reviewed:** 2025-11-26
**Next Review:** 2026-02-26
