# Phases Summary (Quick Reference)

1) **Core Resolver**: candidate model, registries, precedence, explain; hot-swap
   primitives; TaskGroup helpers.
2) **Adapters**: modularize bootstrap; stack_level; resolver bridge; config watcher;
   CLI/debug; adapter settings via Pydantic.
3) **Cross-Domain**: services/tasks/events/workflows on resolver; activation/swap
   hooks; per-domain settings.
4) **Plugins/Remote**: entry-point discovery; remote manifest fetch/verify/cache/
   install; secret-backed creds; source metadata.
5) **Observability/Resiliency**: OTel tracing/metrics/logging; health/readiness;
   backpressure/timeouts; retry/circuit breaker helpers.
6) **Lifecycle/Safety**: lifecycle contract, cleanup/rollback, pause/resume; cancel-
   safe utilities everywhere.
7) **Tooling/UX**: CLI list/why/explain/swap/health; sample manifests; stack-order
   template; tests for precedence/swap/remote integrity.
8) **Config/Secrets**: Pydantic settings for selection + provider settings; secret
   source hook using secret adapter; config schema formalized.
