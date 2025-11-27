# Phases Summary (Quick Reference)

1. **Core Resolver**: candidate model, registries, precedence, explain; hot-swap
   primitives; TaskGroup helpers.
1. **Adapters**: modularize bootstrap; stack_level; resolver bridge; config watcher;
   CLI/debug; adapter settings via Pydantic.
1. **Cross-Domain**: services/tasks/events/workflows on resolver; activation/swap
   hooks; per-domain settings.
1. **Plugins/Remote**: entry-point discovery; remote manifest fetch/verify/cache/
   install; secret-backed creds; source metadata.
1. **Observability/Resiliency**: OTel tracing/metrics/logging; health/readiness;
   backpressure/timeouts; retry/circuit breaker helpers.
1. **Lifecycle/Safety**: lifecycle contract, cleanup/rollback, pause/resume; cancel-
   safe utilities everywhere.
1. **Tooling/UX**: CLI list/why/explain/swap/health; sample manifests; stack-order
   template; tests for precedence/swap/remote integrity.
1. **Config/Secrets**: Pydantic settings for selection + provider settings; secret
   source hook using secret adapter; config schema formalized.
