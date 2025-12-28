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

## Extension points

- Add adapters in `oneiric/adapters/` and register via entry points or config.
- Add actions in `oneiric/actions/` and register via metadata in `oneiric/actions/bootstrap.py`.
- Remote manifests hydrate all domains via `oneiric/remote/loader.py`.

See `docs/examples/LOCAL_CLI_DEMO.md` for hands-on CLI examples.
