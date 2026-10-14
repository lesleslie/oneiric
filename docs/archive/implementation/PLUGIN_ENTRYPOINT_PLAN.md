# Plugin & Entry-Point Discovery Plan

> **Archive Notice (2025-12-19):** Superseded by the implemented entry-point loader and `docs/ONEIRIC_VS_ACB.md`.

This document captures the scaffold for Phase 4's plugin protocol. The goal is to
allow adapter/service/task/event/workflow providers to register themselves via
Python entry points, so runtimes can load third-party integrations without
manually editing manifests.

## Objectives

- Standardize entry-point groups per domain (e.g., `oneiric.adapters`,
  `oneiric.services`).
- Provide a thin loader that enumerates installed packages, imports their
  registrations, and returns callables/metadata blocks that can be fed into the
  resolver.
- Keep the interface opt-in and side-effect free—plugin modules should expose
  declarative metadata or factory functions, not mutate global state.

## Proposed API

```python
from oneiric import plugins

# Discover adapter factories published under `entry_points = {"oneiric.adapters": ...}`
for entry_point in plugins.iter_entry_points("oneiric.adapters"):
    factory = entry_point.load()
    metadata = factory()
    resolver.register_from_pkg(metadata.package, metadata.path, metadata.adapters)
```

- `plugins.iter_entry_points(group: str)` handles compatibility with both the
  legacy `importlib.metadata.entry_points()[group]` API and the new `.select()`
  API introduced in Python 3.10+.
- `plugins.load_callables(group: str)` loads each entry point and returns typed
  callables while logging (but not crashing) on failure.
- Future work: helper shims that understand adapter metadata payloads so plugin
  authors can publish `AdapterMetadata` lists directly.

## Roadmap

1. **Scaffold (this change):** add the reusable loader + documentation to guide
   plugin authors. Keep resolver integration manual for now.
1. **Integration:** add CLI flag (`--plugins`) and runtime bootstrap option to
   auto-register plugin packages before config/remote resolution.
1. **Samples:** publish a reference plugin package and update CONTRIBUTING/AGENTS
   with publishing steps.
1. **Validation:** enforce capability checks (version compatibility, domain
   support) before registering plugin-provided metadata.

## Current Status

- Entry-point auto-loading now runs before local config/remote manifests in both
  the CLI and `main.py`, and the new `oneiric.cli plugins` command surfaces
  diagnostics (groups loaded, payload counts, and failures) for operators.
- `docs/examples/plugins/hello_oneiric_plugin/` ships as a working adapter +
  service plugin to demonstrate packaging, entry-point metadata, and CLI
  verification flows.
