# Remote manifests

Remote manifests describe adapters/services/tasks/events/workflows/actions that can be
hydrated at runtime. This package handles schema models, signature verification, loading,
and telemetry for remote sync.

## Key modules

- `models.py` - manifest models and validation.
- `loader.py` - fetch/verify/ingest manifests into the resolver.
- `security.py` - ED25519 signature verification helpers.
- `telemetry.py` - sync telemetry (`remote_status.json`).

Docs: `docs/REMOTE_MANIFEST_SCHEMA.md`, `docs/SIGNATURE_VERIFICATION.md`.
