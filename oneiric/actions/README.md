# Built-in actions

Action kits are resolver-managed helpers for automation (compression, HTTP fetch,
workflow orchestration, notifications, validation, etc.). They are registered via
metadata and invoked through the ActionBridge or CLI.

## Structure

- `metadata.py` defines `ActionMetadata` and registry helpers.
- `bootstrap.py` registers built-in action kits.
- Individual modules (e.g., `compression.py`, `workflow.py`) implement kits.

## Adding a new action kit

1. Create a module with a class exposing `metadata` and `execute`.
1. Add the metadata to `builtin_action_metadata()` in `bootstrap.py`.
1. Optionally add docs/examples for CLI `action-invoke` usage.

Docs: `docs/REMOTE_MANIFEST_SCHEMA.md` (action entries), `docs/examples/LOCAL_CLI_DEMO.md`.
