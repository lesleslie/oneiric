# oneiric package

This package contains the Oneiric runtime, resolver, domain bridges, and built-in adapters/actions.
For the full documentation map and runbooks, start with `docs/README.md` at the repo root.

## Quick map

- `core/` - config, logging, lifecycle, resolver primitives.
- `domains/` - domain bridge implementations (services/tasks/events/workflows).
- `adapters/` - built-in provider adapters.
- `actions/` - built-in action kits + metadata registration.
- `runtime/` - orchestrator, watchers, telemetry, scheduler, notifications.
- `remote/` - manifest models, loader, signature verification, telemetry.
- `cli.py` - CLI entrypoints and demo wiring.
- `demo.py` - playground/demo helpers (kept separate from production modules).

## Settings

Oneiric's settings use `pydantic_settings.BaseSettings` natively — see
[`docs/adr/0003-pydantic-settings-migration.md`](../adr/0003-pydantic-settings-migration.md)
and the implementation plan at
[`docs/plans/2026-10-11-pydantic-settings-migration.md`](../plans/2026-10-11-pydantic-settings-migration.md).
The custom source chain (init → env → alias → manifest → YAML → secrets)
lives in `oneiric/core/config.py::OneiricSettings.settings_customise_sources`;
custom source wrappers (auth-exclusion, alias-override, manifest-cache)
live in `oneiric/core/_sources.py`. Per-project env-var prefix
subclasses are built and memoized by `oneiric/core/build_settings.py`.

## Extension points

- Add adapters in `oneiric/adapters/` and register via entry points or config.
- Add actions in `oneiric/actions/` and register via metadata in `oneiric/actions/bootstrap.py`.
- Remote manifests hydrate all domains via `oneiric/remote/loader.py`.

See `docs/examples/LOCAL_CLI_DEMO.md` for hands-on CLI examples.
