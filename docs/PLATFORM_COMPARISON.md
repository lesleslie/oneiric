# Runtime & Workflow Platform Comparison

This briefing contrasts Oneiric with Cadence, Temporal, Apache Airflow, Prefect, and Nitric so we can position Oneiric’s resolver/lifecycle stack against the dominant workflow and serverless orchestration platforms.

## Executive Summary

- **Oneiric** specializes in deterministic component resolution, lifecycle-managed hot swaps, and remote manifest delivery with signed artifacts—features the other platforms largely treat as downstream configuration concerns.[^oneiric-core][^manifest][^signatures]
- **Cadence** and **Temporal** provide durable workflow execution engines with replay semantics and long-running activity coordination, but they expect users to solve adapter/service selection outside their runtimes; they complement Oneiric rather than replace it.[^cadence-structure][^temporal-overview]
- **Airflow** and **Prefect** focus on DAG-centric data pipelines, prioritizing scheduling, retries, and UI-driven monitoring over fine-grained runtime swaps or signed component delivery.[^airflow-readme][^prefect-readme]
- **Nitric** targets multi-language, serverless application scaffolding with managed cloud resource provisioning. Its strengths lie in infrastructure-as-code abstractions rather than resolver observability or adapter explainability.[^nitric-overview]

Use Oneiric when you need explainable selection, secure remote packaging, and runtime swaps for adapters/actions; pair it with one of the workflow engines when durable execution or pipeline scheduling is required.

## Snapshot Comparison

| Platform | Primary Focus | Execution Model | Delivery & Hosting | Language / SDK Coverage | Strengths | Key Gaps vs Oneiric |
| --- | --- | --- | --- | --- | --- | --- |
| **Oneiric** | Resolver + lifecycle + remote manifest infrastructure | Hot-swappable domains (adapters, services, tasks, events, workflows) with 4-tier precedence and health-checked swaps | Python package with serverless profile (Cloud Run), signed manifest sync, CLI tooling | Python runtime, adapters/actions registered via metadata and remote manifests | Deterministic selection explainability, ED25519-signed manifests, serverless toggles, remote watchers, structured observability | No built-in durable workflow scheduler yet (orchestration parity still in progress) |
| **Cadence** | Self-hosted workflow orchestration (Uber OSS) | Stateful workflows & activities with history scanners/fixers | Multi-service Go stack with Cassandra/MySQL/Postgres + Elasticsearch + Kafka dependencies | Go SDKs (plus wrappers) | Fault-tolerant long-running workflows, rich reconciliation tooling | No resolver/manifest semantics; operator must manage infra dependencies |
| **Temporal** | Durable execution platform + managed cloud | Deterministic workflow replay, commands/futures, cross-language SDKs | Self-hosted Temporal Server or Temporal Cloud SaaS | Go, Java, TypeScript, Python, .NET, PHP, Ruby | Unified workflow APIs, Temporal Cloud SLA, Nexus for cross-service calls | Component selection/config left to user-land; no adapter hot swapping |
| **Apache Airflow** | DAG-based batch pipeline orchestration | Python-authored DAGs executed by schedulers/workers; metadata DB | Self-hosted (Celery/Kubernetes/Standalone) | Python tasks/operators; REST/CLI | Mature ecosystem, provider packages, UI | No explainable resolver, limited runtime swapping, no signed component pipeline |
| **Prefect** | Flow-based orchestration with hybrid cloud | Declarative flows, blocks, automations, serverless deployments | Prefect Cloud (SaaS) or Prefect Server | Python (Flows, Deployments) | Modern developer UX, automation engine, block-based integrations | Focused on orchestration, not component resolution or multi-domain registries |
| **Nitric** | Multi-language serverless backend framework | Evented services with auto-provisioned cloud resources | CLI + Pulumi-based provisioning across AWS/GCP/Azure | Node.js, Python, Go (plus experimental Dart/C#/JVM) | Cross-cloud abstractions, built-in secret/resource management | Lacks deterministic resolver metadata, signed manifest story, or adapter hot swaps |

## Platform Notes

### Oneiric

- **Deterministic resolution & lifecycle orchestration:** Shared candidate model, 4-tier precedence (override → inferred priority → stack level → registration order), and per-domain activation/swap APIs ensure explainable selection and rollback-safe hot swaps across adapters, services, tasks, events, and workflows.[^oneiric-core]
- **Remote manifest pipeline:** v2 schema adds capability descriptors, retry policies, dependency/platform constraints, and event/DAG metadata while remaining backward compatible; manifests can be delivered via HTTP/S3/GCS/OCI and tied to stack levels for multi-tenant overrides.[^manifest]
- **Supply-chain controls:** ED25519 signatures, canonical JSON verification, multi-key trust, and CLI workflows (publish, rotate keys) protect remote packages from tampering.[^signatures]
- **Serverless-first posture:** Cloud Run Procfile, profile toggles (watchers off, inline manifests, secret precedence), buildpack docs, and remote loader hardening (httpx + tenacity/aiobreaker) make the runtime portable to modern serverless stacks.[^serverless-plan]
- **Roadmap:** Remaining workstreams target orchestration parity (event dispatcher, DAG runtime, supervisors) and adapter completeness (messaging/scheduler, NoSQL, graph), with a single cut-over planned to replace ACB entirely.[^serverless-plan][^strategic-roadmap]

### Cadence (Uber)

- **Open-source workflow engine** with a Go-based control plane, multi-service architecture (`service/` submodules), and heavy reliance on persistence tiers (Cassandra/MySQL/Postgres) plus Elasticsearch/Kafka.[^cadence-structure]
- **Scanner/fixer workflows** enforce data integrity invariants (e.g., `concreteExecutionExists`) and require dedicated worker configuration to enable domain-specific remediation.[^cadence-structure]
- **Operational maturity** includes Docker compose bundles for dependencies, schema tooling, and worker configs, but no opinionated resolver/manifest system—component wiring remains an application concern.

### Temporal

- **Durable execution system** offering workflow replay, futures/awaitables, memoized state, and an extensive SDK matrix (Go, Java, TS, Python, .NET, PHP, Ruby).[^temporal-overview]
- **Temporal Cloud** provides managed namespaces, SLAs, and Nexus for cross-service calls; self-hosted server releases follow semantic versioning with defined upgrade guarantees.[^temporal-server]
- **Develop/Operate experience:** CLI, SDK metrics hooks, cancellation/heartbeat APIs, and docs covering observability, patching, and release stages. Like Cadence, Temporal expects external tooling for adapter selection or manifest delivery.

### Apache Airflow

- **Python-authored DAG orchestration stack** with schedulers, executors, and a metadata DB. Provider packages supply hundreds of operators/hooks for cloud services, transferring, and messaging use cases.[^airflow-readme]
- **Semantic versioning & release process** plus provider backports allow gradual upgrades, but configuration is largely static (environment variables or connections), and runtime swapping or signed adapter delivery fall outside Airflow’s purview.

### Prefect

- **Modern flow orchestrator** emphasizing developer ergonomics, blocks, automations, and hybrid deployment (self-managed workers with SaaS control plane). Documentation highlights ECS workers, serverless provisioning, and automation actions.[^prefect-readme]
- **Prefect blocks** act as resource descriptors similar to Oneiric manifest entries but are invoked at runtime rather than driving deterministic selection for every adapter.

### Nitric

- **Multi-language serverless framework** that provisions infrastructure (via Pulumi providers) and exposes a CLI (`nitric up`) to deploy APIs, queues, and websites across AWS/GCP/Azure.[^nitric-overview]
- **Project model** relies on `nitric.yaml` plus stack-specific files (e.g., `nitric.aws.yaml`) and service directories; SDKs exist for Node.js, Python, Go, with experimental support for Dart/C#/JVM.[^nitric-overview]
- Focus is on resource provisioning and event-driven service scaffolding rather than deterministic component selection or signed manifest distribution.

## Fit Guide

- **Pair Oneiric with Cadence or Temporal** when you need deterministic adapter/service selection feeding into durable workflows. Oneiric can hot swap caches, queues, or secrets adapters while Cadence/Temporal manage long-running workflows.
- **Layer Oneiric under Airflow or Prefect** to centralize credential management, messaging adapters, and remote manifests while those platforms handle DAG scheduling and UI/alerting.
- **Use Nitric for greenfield serverless stacks** that need multi-cloud provisioning; adopt Oneiric within Nitric services when you require explainable selection logic, remote manifest delivery, or ED25519-verified component supply chains.

---

[^oneiric-core]: README.md:11-210; docs/RESOLUTION_LAYER_SPEC.md:1-110
[^manifest]: docs/REMOTE_MANIFEST_SCHEMA.md:1-200
[^signatures]: docs/SIGNATURE_VERIFICATION.md:1-200
[^serverless-plan]: docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md:1-152
[^strategic-roadmap]: docs/STRATEGIC_ROADMAP.md:1-149
[^cadence-structure]: https://github.com/cadence-workflow/cadence/blob/master/CONTRIBUTING.md
[^temporal-overview]: https://docs.temporal.io/workflow-execution
[^temporal-server]: https://docs.temporal.io/temporal-service/temporal-server
[^airflow-readme]: https://github.com/apache/airflow/blob/main/README.md
[^prefect-readme]: https://github.com/prefecthq/prefect/blob/main/README.md
[^nitric-overview]: https://github.com/nitrictech/nitric/tree/main/docs
