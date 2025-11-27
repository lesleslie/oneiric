# Adapter Migration Plan (ACB → Oneiric)

Goal: reuse existing adapter implementations by wrapping them with Oneiric’s resolver
and lifecycle. Add provider/stack metadata, typed settings, and lifecycle hooks.

## Steps

1. **Inventory**: list adapter categories/providers to migrate. Note required deps and
   settings.
1. **Metadata**: for each adapter module, declare provider metadata:
   - `provider` (e.g., `redis`, `memory`), `category` (e.g., `cache`), `version`,
     `capabilities`, `stack_level` (z-index), and identifiers.
1. **Settings**: define a Pydantic settings model per provider (e.g.,
   `RedisCacheSettings`). Keep them provider-scoped and loaded via Oneiric config
   module.
1. **Lifecycle wrapper**: wrap the adapter class to implement lifecycle contract:
   - `init()` (async/awaitable), `health()`, `cleanup()`, optional `pause()/resume()`.
   - Ensure resource creation is in `init`, teardown in `cleanup`.
1. **Candidate registration**: in the adapters bridge, register a `Candidate` with:
   - domain=`adapter`, key=`category`, provider, priority (from register_pkg), stack_level,
     factory/import path, metadata, health hook.
1. **Resolver bridge**: ensure adapter resolution uses the shared precedence rules
   (config override → pkg priority → stack_level → last-write).
1. **Config wiring**:
   - Adapter selection: config domain/key → provider (e.g., `adapters.cache = redis`).
   - Provider settings: load via Pydantic settings layer; allow secret-source hook to
     fill missing secrets.
1. **Hot swap ready**: verify init/health/cleanup are safe; support swap with rollback
   on failed init/health.
1. **Testing**:
   - Unit: lifecycle hooks (init/cleanup), health passes/fails, settings validation.
   - Resolver: precedence (stack order, stack_level), swap, shadowed candidates.
   - Integration: adapter operates with real or mocked backend; secrets source populates
     config when enabled.

## Minimal code touch points per adapter

- Add metadata module/section with provider, category, stack_level.
- Add/adjust settings model.
- Implement lifecycle methods; ensure resources are created/closed there.
- Register candidate in adapters bridge with factory and metadata.
- Remove legacy static registration calls; rely on resolver registration.
