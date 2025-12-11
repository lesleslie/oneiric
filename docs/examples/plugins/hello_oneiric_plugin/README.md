# Hello Oneiric Plugin

This reference package shows how to publish a lightweight adapter plugin via entry points.
It registers a single `cache` adapter plus a status service that demonstrate how plugin
payloads can bundle `AdapterMetadata` and complete `Candidate` objects.

## Quick Start

1. Install the package in editable mode while developing:
   ```bash
   uv pip install -e docs/examples/plugins/hello_oneiric_plugin
   ```
1. Set `plugins.auto_load = true` in your `settings.toml` or pass `--demo` to the CLI.
1. Run any CLI command (e.g., `oneiric plugins`) to verify the plugin is discovered.

## Files

- `pyproject.toml` defines the entry-point groups:
  ```toml
  [project.entry-points."oneiric.adapters"]
  hello_adapter = "hello_oneiric_plugin:adapter_entries"

  [project.entry-points."oneiric.services"]
  hello_service = "hello_oneiric_plugin:service_entries"
  ```
- `hello_oneiric_plugin/__init__.py` exposes `adapter_entries()` and `service_entries()`
  helpers that return `AdapterMetadata` and `Candidate` payloads. These payloads are
  normalized automatically by `plugins.register_entrypoint_plugins`.

## Testing the Plugin

Activate the demo adapter via the CLI:

```bash
oneiric --demo plugins
oneiric --demo list --domain adapter --shadowed
```

You should see the `hello.entrypoint` provider available. The same package can be
referenced inside manifests by provider name to route real traffic.
