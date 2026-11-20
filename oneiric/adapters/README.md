# Built-in adapters

This directory contains Oneiric's built-in adapters for caches, queues, storage, secrets,
HTTP clients, messaging, databases, etc. Adapters are discovered via resolver metadata and
can be swapped at runtime.

## Structure

- Subpackages group adapters by domain (e.g., `cache/`, `queue/`, `messaging/`).
- `metadata.py` defines adapter metadata helpers.
- `bootstrap.py` registers built-ins with the resolver.
- `bridge.py` and `watcher.py` provide domain bridge wiring.

## Adding a new adapter

1. Add a module under the appropriate subpackage.
2. Expose metadata (capabilities, provider id, settings model).
3. Register via `oneiric/adapters/bootstrap.py` or entry points.

Docs: `docs/README.md`, `docs/examples/LOCAL_CLI_DEMO.md`.
