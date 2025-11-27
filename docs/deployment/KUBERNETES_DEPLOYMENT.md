# Kubernetes Deployment Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-26
**Target:** Oneiric v0.1.0+ on Kubernetes 1.28+

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Deployment Manifests](#deployment-manifests)
5. [ConfigMaps & Secrets](#configmaps--secrets)
6. [Persistent Volumes](#persistent-volumes)
7. [Services & Ingress](#services--ingress)
8. [Autoscaling](#autoscaling)
9. [Monitoring Integration](#monitoring-integration)
10. [Helm Chart](#helm-chart)
11. [Production Best Practices](#production-best-practices)
12. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Deployment Strategy

- **Rolling Updates:** Zero-downtime deployments with configurable surge/unavailability
- **Resource Management:** CPU/memory requests and limits
- **Health Probes:** Liveness and readiness probes with proper timing
- **Horizontal Scaling:** HPA based on CPU/memory/custom metrics
- **PersistentVolume:** Cache storage with appropriate access modes

### Components

```
┌─────────────────────────────────────────┐
│           Ingress Controller            │
│  (nginx/traefik/istio)                  │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────▼─────────┐
        │   Service (LB)     │
        └─────────┬─────────┘
                  │
     ┌────────────▼────────────┐
     │   Deployment (3 pods)    │
     │  ┌──────────────────┐   │
     │  │  oneiric:latest  │   │
     │  └──────────────────┘   │
     └────────────┬────────────┘
                  │
     ┌────────────▼────────────┐
     │  PersistentVolumeClaim  │
     │     (cache storage)     │
     └─────────────────────────┘
```

---

## Prerequisites

### Required Tools

```bash
# Kubernetes CLI
kubectl version --client

# (Optional) Helm 3+
helm version

# (Optional) Kustomize
kubectl kustomize --help
```

### Cluster Requirements

- Kubernetes 1.28+
- StorageClass available for PersistentVolumes
- Ingress controller (nginx/traefik/istio)
- Metrics Server (for HPA)
- Prometheus Operator (for monitoring)

### Container Registry

```bash
# Build and push image
docker build -t your-registry.com/oneiric:0.1.0 .
docker push your-registry.com/oneiric:0.1.0
```

---

## Quick Start

### Deploy All Resources

```bash
# Create namespace
kubectl create namespace oneiric

# Create secrets
kubectl create secret generic oneiric-secrets \
  --from-literal=api-key=your-api-key \
  --namespace oneiric

# Apply all manifests
kubectl apply -f k8s/ -n oneiric

# Watch deployment rollout
kubectl rollout status deployment/oneiric -n oneiric

# Check pods
kubectl get pods -n oneiric -w

# View logs
kubectl logs -f deployment/oneiric -n oneiric
```

### Verify Deployment

```bash
# Check health
kubectl exec -it deployment/oneiric -n oneiric -- \
  python -m oneiric.cli health --probe

# Get service endpoint
kubectl get svc oneiric -n oneiric

# Port forward for testing
kubectl port-forward svc/oneiric 8000:8000 -n oneiric
curl http://localhost:8000/health
```

---

## Deployment Manifests

### Namespace

**File:** `k8s/00-namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: oneiric
  labels:
    app: oneiric
    environment: production
```

### Deployment

**File:** `k8s/10-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oneiric
  namespace: oneiric
  labels:
    app: oneiric
    version: v0.1.0
spec:
  # Replicas (will be overridden by HPA)
  replicas: 3

  # Rolling update strategy
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1         # Allow 1 extra pod during update
      maxUnavailable: 0   # Keep all pods available during update

  # Selector
  selector:
    matchLabels:
      app: oneiric

  # Pod template
  template:
    metadata:
      labels:
        app: oneiric
        version: v0.1.0
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
        prometheus.io/path: "/metrics"

    spec:
      # Security context (run as non-root)
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000

      # Service account (for RBAC)
      serviceAccountName: oneiric

      # Init containers (optional)
      initContainers:
        - name: wait-for-dependencies
          image: busybox:1.36
          command: ['sh', '-c', 'echo "Waiting for dependencies..." && sleep 5']

      # Main container
      containers:
        - name: oneiric
          image: your-registry.com/oneiric:0.1.0
          imagePullPolicy: IfNotPresent

          # Ports
          ports:
            - name: http
              containerPort: 8000
              protocol: TCP
            - name: metrics
              containerPort: 9090
              protocol: TCP

          # Environment variables
          env:
            - name: ONEIRIC_CONFIG
              value: /app/settings
            - name: LOG_LEVEL
              value: INFO
            - name: ONEIRIC_LOG_FORMAT
              value: json
            - name: OTEL_SERVICE_NAME
              value: oneiric
            - name: PROMETHEUS_METRICS_PORT
              value: "9090"

          # Environment from ConfigMap
          envFrom:
            - configMapRef:
                name: oneiric-config

          # Secrets
          volumeMounts:
            - name: settings
              mountPath: /app/settings
              readOnly: true
            - name: cache
              mountPath: /app/.oneiric_cache
            - name: logs
              mountPath: /app/logs

          # Resource requests/limits
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: 2000m
              memory: 2Gi

          # Liveness probe (restart if unhealthy)
          livenessProbe:
            exec:
              command:
                - python
                - -m
                - oneiric.cli
                - health
                - --probe
            initialDelaySeconds: 60
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 3
            successThreshold: 1

          # Readiness probe (remove from service if not ready)
          readinessProbe:
            exec:
              command:
                - python
                - -m
                - oneiric.cli
                - health
                - --probe
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
            successThreshold: 1

          # Startup probe (allow slow startup)
          startupProbe:
            exec:
              command:
                - python
                - -m
                - oneiric.cli
                - health
                - --probe
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 12  # 120 seconds total

          # Security context
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false  # Set to true if possible
            capabilities:
              drop:
                - ALL

      # Volumes
      volumes:
        - name: settings
          configMap:
            name: oneiric-settings
        - name: cache
          persistentVolumeClaim:
            claimName: oneiric-cache
        - name: logs
          emptyDir: {}

      # Pod affinity (spread across nodes)
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - oneiric
                topologyKey: kubernetes.io/hostname

      # Tolerations (optional)
      # tolerations:
      #   - key: "workload"
      #     operator: "Equal"
      #     value: "oneiric"
      #     effect: "NoSchedule"

      # Node selector (optional)
      # nodeSelector:
      #   workload: oneiric
```

---

## ConfigMaps & Secrets

### ConfigMap

**File:** `k8s/20-configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: oneiric-config
  namespace: oneiric
data:
  ONEIRIC_STACK_ORDER: "production:100,staging:50,default:0"
  ONEIRIC_CACHE_DIR: "/app/.oneiric_cache"
  OTEL_EXPORTER_OTLP_ENDPOINT: "http://tempo.monitoring:4317"
```

**File:** `k8s/21-configmap-settings.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: oneiric-settings
  namespace: oneiric
data:
  app.yml: |
    name: oneiric
    version: 0.1.0

  adapters.yml: |
    cache: redis
    storage: s3

  services.yml: |
    status: builtin

  # Add other YAML config files as needed
```

### Secrets

**File:** `k8s/30-secret.yaml`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: oneiric-secrets
  namespace: oneiric
type: Opaque
stringData:
  # API keys (base64 encoded automatically)
  api-key: "your-api-key-here"
  redis-password: "your-redis-password"

  # Certificate for manifest signature verification
  manifest-public-key.pem: |
    -----BEGIN PUBLIC KEY-----
    MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA...
    -----END PUBLIC KEY-----
```

**Create from file:**

```bash
kubectl create secret generic oneiric-secrets \
  --from-literal=api-key=your-api-key \
  --from-file=manifest-public-key.pem=/path/to/public-key.pem \
  --namespace oneiric
```

---

## Persistent Volumes

### PersistentVolumeClaim

**File:** `k8s/40-pvc.yaml`

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: oneiric-cache
  namespace: oneiric
  labels:
    app: oneiric
spec:
  accessModes:
    - ReadWriteMany  # Allow multiple pods to share cache
  storageClassName: fast-ssd  # Use your StorageClass
  resources:
    requests:
      storage: 10Gi
```

### StorageClass (Example - EBS)

**File:** `k8s/41-storageclass.yaml`

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
  encrypted: "true"
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
```

---

## Services & Ingress

### Service (ClusterIP)

**File:** `k8s/50-service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: oneiric
  namespace: oneiric
  labels:
    app: oneiric
spec:
  type: ClusterIP
  selector:
    app: oneiric
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
    - name: metrics
      port: 9090
      targetPort: 9090
      protocol: TCP
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 3600
```

### Service (LoadBalancer - Production)

**File:** `k8s/51-service-lb.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: oneiric-lb
  namespace: oneiric
  annotations:
    # AWS-specific annotations
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    service.beta.kubernetes.io/aws-load-balancer-internal: "false"
spec:
  type: LoadBalancer
  selector:
    app: oneiric
  ports:
    - name: http
      port: 80
      targetPort: 8000
      protocol: TCP
```

### Ingress (nginx)

**File:** `k8s/52-ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: oneiric
  namespace: oneiric
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  tls:
    - hosts:
        - oneiric.example.com
      secretName: oneiric-tls
  rules:
    - host: oneiric.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: oneiric
                port:
                  number: 8000
```

---

## Autoscaling

### Horizontal Pod Autoscaler (CPU)

**File:** `k8s/60-hpa.yaml`

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: oneiric
  namespace: oneiric
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: oneiric

  minReplicas: 3
  maxReplicas: 10

  metrics:
    # CPU utilization
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70

    # Memory utilization
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80

  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300  # Wait 5 min before scaling down
      policies:
        - type: Percent
          value: 50  # Scale down max 50% of pods at a time
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0  # Scale up immediately
      policies:
        - type: Percent
          value: 100  # Double pods at a time
          periodSeconds: 15
        - type: Pods
          value: 4  # Or add max 4 pods at a time
          periodSeconds: 15
      selectPolicy: Max  # Use the most aggressive policy
```

### Pod Disruption Budget

**File:** `k8s/61-pdb.yaml`

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: oneiric
  namespace: oneiric
spec:
  minAvailable: 2  # Keep at least 2 pods running during disruptions
  selector:
    matchLabels:
      app: oneiric
```

---

## Monitoring Integration

### ServiceMonitor (Prometheus Operator)

**File:** `k8s/70-servicemonitor.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: oneiric
  namespace: oneiric
  labels:
    app: oneiric
    prometheus: kube-prometheus
spec:
  selector:
    matchLabels:
      app: oneiric
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

### PrometheusRule (Alerts)

**File:** `k8s/71-prometheusrule.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: oneiric
  namespace: oneiric
spec:
  groups:
    - name: oneiric.rules
      interval: 30s
      rules:
        - alert: OneiricHighCPU
          expr: rate(container_cpu_usage_seconds_total{pod=~"oneiric-.*"}[5m]) > 0.8
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Oneiric pod CPU usage is high"

        - alert: OneiricPodDown
          expr: up{job="oneiric"} == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Oneiric pod is down"

        - alert: OneiricHighMemory
          expr: container_memory_usage_bytes{pod=~"oneiric-.*"} / container_spec_memory_limit_bytes{pod=~"oneiric-.*"} > 0.9
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Oneiric pod memory usage is high"
```

---

## Helm Chart

### Chart Structure

```
oneiric-chart/
├── Chart.yaml
├── values.yaml
├── values-production.yaml
├── templates/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── pvc.yaml
│   ├── hpa.yaml
│   ├── serviceaccount.yaml
│   ├── servicemonitor.yaml
│   └── _helpers.tpl
└── README.md
```

### Chart.yaml

```yaml
apiVersion: v2
name: oneiric
description: Oneiric - Universal Resolution Layer
type: application
version: 0.1.0
appVersion: "0.1.0"
maintainers:
  - name: Oneiric Team
    email: team@example.com
```

### values.yaml

```yaml
# Default values for oneiric Helm chart

replicaCount: 3

image:
  repository: your-registry.com/oneiric
  pullPolicy: IfNotPresent
  tag: "0.1.0"

imagePullSecrets: []
nameOverride: ""
fullnameOverride: ""

serviceAccount:
  create: true
  annotations: {}
  name: ""

podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9090"

podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: false
  capabilities:
    drop:
      - ALL

service:
  type: ClusterIP
  port: 8000
  metricsPort: 9090

ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: oneiric.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: oneiric-tls
      hosts:
        - oneiric.example.com

resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 2000m
    memory: 2Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

persistence:
  enabled: true
  storageClass: "fast-ssd"
  accessMode: ReadWriteMany
  size: 10Gi

config:
  stackOrder: "production:100,staging:50,default:0"
  logLevel: INFO

monitoring:
  enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s

nodeSelector: {}
tolerations: []
affinity: {}
```

### Install with Helm

```bash
# Add repository (if published)
helm repo add oneiric https://charts.example.com/oneiric
helm repo update

# Install chart
helm install oneiric oneiric/oneiric \
  --namespace oneiric \
  --create-namespace \
  --values values-production.yaml

# Upgrade chart
helm upgrade oneiric oneiric/oneiric \
  --namespace oneiric \
  --values values-production.yaml

# Uninstall
helm uninstall oneiric --namespace oneiric
```

---

## Production Best Practices

### 1. Resource Management

- Always set resource requests and limits
- Monitor actual usage and adjust
- Use VPA (Vertical Pod Autoscaler) for recommendations

### 2. High Availability

- Deploy across multiple nodes (anti-affinity)
- Use Pod Disruption Budgets
- Set `minAvailable` > 1

### 3. Security

- Run as non-root user
- Use read-only root filesystem where possible
- Drop all Linux capabilities
- Use NetworkPolicies to restrict traffic

### 4. Monitoring

- Deploy Prometheus ServiceMonitor
- Set up alerting rules
- Monitor pod health metrics

### 5. Scaling

- Use HPA with custom metrics (not just CPU/memory)
- Configure proper stabilization windows
- Test autoscaling under load

### 6. Updates

- Use rolling updates with appropriate surge/unavailability
- Test in staging before production
- Monitor rollout progress

---

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl get pods -n oneiric

# Describe pod
kubectl describe pod <pod-name> -n oneiric

# Check logs
kubectl logs <pod-name> -n oneiric
```

### Image Pull Errors

```bash
# Check ImagePullSecrets
kubectl get secret -n oneiric

# Create ImagePullSecret
kubectl create secret docker-registry regcred \
  --docker-server=your-registry.com \
  --docker-username=your-username \
  --docker-password=your-password \
  --namespace=oneiric
```

### PVC Not Binding

```bash
# Check PVC status
kubectl get pvc -n oneiric

# Describe PVC
kubectl describe pvc oneiric-cache -n oneiric

# Check StorageClass
kubectl get storageclass
```

### Ingress Not Working

```bash
# Check Ingress
kubectl get ingress -n oneiric
kubectl describe ingress oneiric -n oneiric

# Check Ingress Controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

---

## Next Steps

- [Systemd Deployment](./SYSTEMD_DEPLOYMENT.md) - Run as systemd service
- [Monitoring Setup](../monitoring/MONITORING_SETUP.md) - Configure Prometheus, Grafana, Loki
- [Runbooks](../runbooks/README.md) - Incident response procedures
- [Docker Deployment](./DOCKER_DEPLOYMENT.md) - Docker Compose alternative
