# Domain bridges

Domain bridges provide domain-specific behavior on top of the shared resolver/lifecycle
stack. Each bridge translates resolver candidates into domain objects and exposes
operations like `status`, `swap`, or `emit`/`run` depending on the domain.

## Modules

- `base.py`, `protocols.py`, `services.py`, `tasks.py`, `events.py`, `workflows.py`
- `watchers.py` provides per-domain watcher wrappers around `runtime.watchers`.
-
- Adapter bridge: `oneiric/adapters/bridge.py`
- Action bridge: `oneiric/actions/bridge.py`

Docs: `docs/RESOLUTION_LAYER_SPEC.md`, `docs/REMOTE_MANIFEST_SCHEMA.md`.
