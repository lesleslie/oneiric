# Oneiric Shell Quick Reference

## Start Shell

```bash
oneiric shell
```

## Convenience Functions

| Function | Description |
|----------|-------------|
| `reload_settings()` | Reload configuration from all layers |
| `show_layers()` | Display config layer precedence table |
| `validate_config()` | Validate current Pydantic model |

## Available Objects

| Object | Type | Description |
|--------|------|-------------|
| `config` | OneiricSettings | Current configuration instance |
| `OneiricSettings` | class | Configuration class |

## Configuration Layers (Precedence)

1. **Environment** - `ONEIRIC_*` variables (highest)
1. **Local** - `settings/local.yaml` (gitignored)
1. **YAML** - `settings/oneiric.yaml` (committed)
1. **Defaults** - Pydantic field defaults (lowest)

## Session Tracking

- **Component**: `oneiric`
- **Type**: `foundation`
- **Tracking**: Via Session-Buddy MCP
- **Events**: `session_start`, `session_end`

## Metadata

```python
{
  "version": "0.5.1",
  "adapters": [],
  "component_type": "foundation"
}
```

## Examples

```python
# Inspect config
config.server_name
config.runtime_paths.cache_dir

# Validate
validate_config()

# Reload after editing YAML
reload_settings()

# Show layer precedence
show_layers()
```

## Python Help

```python
help()          # Python help
%help_shell     # Shell magic commands
```

## Related

- Mahavishnu: `mahavishnu shell` (workflow orchestration)
- Session-Buddy: `session-buddy shell` (session management)
