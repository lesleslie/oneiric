---
title: Writing a Custom Adapter
status: active
role: canonical
topic: lifecycle
last_reviewed: 2026-09-09
---

# Writing a Custom Adapter

Oneiric adapters are pluggable components registered through Python entry points. This guide walks through the canonical pattern using the bundled `hello_oneiric_plugin` example as a starting point.

> **Terminology:** an **adapter** is one *candidate* in the resolver with `domain='adapter'`, identified by `key` (category, e.g. `cache`, `database`, `vector`) and `provider` (implementation, e.g. `redis`, `memcached`).

## When to write a custom adapter

Reach for a custom adapter when the bundled adapters don't fit your runtime. Typical triggers:

- A proprietary HTTP client, queue backend, or vector DB that has no upstream Oneiric adapter yet
- An internal service-mesh sidecar that needs first-class lifecycle hooks (init / health / shutdown)
- A managed cloud offering (Redis Enterprise, Pinecone, Turso) where you want provider-tagged resolution but don't want to vendor it into core

In all cases, the bundled example at `docs/examples/plugins/hello_oneiric_plugin/` is the shortest path from `pyproject.toml` to a working registered adapter.

## The plugin example

The example ships three files:

```
docs/examples/plugins/hello_oneiric_plugin/
├── pyproject.toml
├── README.md
└── hello_oneiric_plugin/
    └── __init__.py
```

- `pyproject.toml` declares the entry-point groups `oneiric.adapters` and `oneiric.services` so the resolver finds the plugin at startup.
- `__init__.py` exposes `adapter_entries()` and `service_entries()` factories that return `AdapterMetadata` and `Candidate` payloads.
- `oneiric.plugins.register_entrypoint_plugins` (called from `_initialize_state` in the CLI bootstrap) normalizes those payloads and registers them with the resolver.

Install in editable mode to develop locally:

```bash
uv pip install -e docs/examples/plugins/hello_oneiric_plugin
```

Then set `plugins.auto_load = true` in your settings or pass `--demo` to the CLI on the first run.

## Lifecycle hooks

Adapters implement these hooks; the resolver invokes them in this order:

- `async def init(self) -> None` — called once at registration; open connections here.
- `async def health(self) -> HealthStatus` — periodic liveness check.
- `async def shutdown(self) -> None` — graceful close during cleanup.
- `async def bind(self, **kwargs) -> None` — optional late-binding hook.

**Critical:** the lifecycle hook is `init`, not `initialize`. See `ADAPTER_LIFECYCLE_TEMPLATE.md` for the canonical signature and the exact return types.

## Factory-path convention

When registering through the resolver, factory paths follow `module.path:ClassName`:

```yaml
settings_model: "my_package.adapters.redis:RedisCacheSettings"
factory: "my_package.adapters.redis:RedisCacheAdapter"
```

Both keys are mandatory in remote manifests — `settings_model` drives Pydantic validation, `factory` drives instantiation. See `REMOTE_MANIFEST_SCHEMA.md` for the full schema, including per-domain `key`, `provider`, `priority`, and `stack_level` semantics.

## Verification

After installing your plugin, verify it registered:

```bash
oneiric list --domain adapter --shadowed
```

You should see your provider listed in the *Active adapters* section (or *Shadowed adapters* if a higher-priority candidate is already active for that key). For a richer diagnostic with entry-point group / error info:

```bash
oneiric plugins --json
```

If the plugin is missing, the most common causes are: (a) the package is installed but `plugins.auto_load` is `false` in settings; (b) the entry-point group name is misspelled — it must be exactly `oneiric.adapters`; (c) the factory function raises on import — `oneiric plugins` will surface the error.

## See also

- `docs/examples/plugins/hello_oneiric_plugin/README.md` — complete runnable example
- `docs/ADAPTER_LIFECYCLE_TEMPLATE.md` — canonical lifecycle template
- `docs/analysis/ADAPTER_STRATEGY.md` — design strategy and existing adapter categories
- `docs/REMOTE_MANIFEST_SCHEMA.md` — full `settings_model` and `factory` schema
