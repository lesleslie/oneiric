# Oneiric Admin Shell

Universal component resolution and lifecycle management shell with session tracking.

## Overview

The Oneiric Admin Shell provides an interactive IPython environment for managing Oneiric configuration, inspecting component lifecycle, and tracking shell sessions via Session-Buddy MCP.

## Features

- **Configuration Management**: Inspect, validate, and reload layered configuration
- **Session Tracking**: Automatic session lifecycle tracking via Session-Buddy MCP
- **Component Metadata**: Version detection and adapter information
- **Convenience Functions**: Quick access to common operations
- **Rich Output**: Beautiful tables and formatted output with Rich

## Quick Start

### Start the Shell

```bash
cd /path/to/oneiric
oneiric shell
```

Or via Python:

```python
from oneiric.shell import OneiricShell
from oneiric.core.config import load_settings

config = load_settings()
shell = OneiricShell(config)
shell.start()
```

### Available Commands

#### Convenience Functions

```python
# Reload configuration from all layers
reload_settings()

# Display configuration layer precedence
show_layers()

# Validate current configuration
validate_config()
```

#### Available Objects

```python
# Current configuration object
config

# Configuration class
OneiricSettings
```

## Configuration Layers

Oneiric uses a layered configuration system with the following precedence (highest to lowest):

1. **Environment Variables** - Runtime overrides (`ONEIRIC_*`)
2. **Local YAML** - `settings/local.yaml` (gitignored)
3. **YAML Config** - `settings/oneiric.yaml` (committed)
4. **Defaults** - Pydantic field defaults

Example output from `show_layers()`:

```
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Layer   ┃ Source                        ┃ Status             ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ 1. Defaults │ Pydantic field defaults   │ Always active      │
│ 2. YAML      │ settings/oneiric.yaml     │ Committed to git  │
│ 3. Local     │ settings/local.yaml       │ Gitignored        │
│ 4. Environment │ ONEIRIC_* variables     │ Runtime overrides │
└───────────┴───────────────────────────────┴────────────────────┘
```

## Session Tracking

The Oneiric shell automatically tracks session lifecycle events via Session-Buddy MCP:

### Session Start Event

Emitted when shell starts:

```json
{
  "event_version": "1.0",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "session_start",
  "component_name": "oneiric",
  "shell_type": "OneiricShell",
  "timestamp": "2026-02-06T12:34:56.789Z",
  "pid": 12345,
  "user": {
    "username": "john",
    "home": "/home/john"
  },
  "hostname": "server01",
  "environment": {
    "python_version": "3.13.0",
    "platform": "Linux-6.5.0-x86_64",
    "cwd": "/home/john/projects/oneiric"
  },
  "metadata": {
    "version": "0.5.1",
    "adapters": [],
    "component_type": "foundation"
  }
}
```

### Session End Event

Emitted when shell exits:

```json
{
  "event_type": "session_end",
  "session_id": "sess_abc123",
  "timestamp": "2026-02-06T13:45:67.890Z",
  "metadata": {}
}
```

### Session Tracking Status

Session tracking is enabled by default. If Session-Buddy MCP is unavailable, the shell will still function but sessions won't be tracked.

## Component Metadata

The Oneiric shell provides component-specific metadata:

- **Component Name**: `oneiric`
- **Component Type**: `foundation` (provides to all other components)
- **Version**: Detected from package metadata
- **Adapters**: Empty list (Oneiric is foundation, not an orchestrator)

## Architecture

### Class Hierarchy

```
AdminShell (base class in oneiric/shell/core.py)
    ↓
OneiricShell (oneiric/shell/adapter.py)
```

### Key Methods

- `_get_component_name()`: Returns "oneiric" for session tracking
- `_get_component_version()`: Detects Oneiric package version
- `_get_adapters_info()`: Returns empty list (foundation component)
- `_get_banner()`: Generates Oneiric-specific banner
- `_add_oneiric_namespace()`: Adds convenience functions to namespace
- `_emit_session_start()`: Notifies Session-Buddy of session start
- `_emit_session_end()`: Notifies Session-Buddy of session end

### Session Tracking Flow

```
1. Shell.start() called
   ↓
2. _notify_session_start_async()
   ↓
3. SessionEventEmitter.emit_session_start()
   ↓
4. Session-Buddy MCP: track_session_start tool
   ↓
5. Session ID returned and stored
   ↓
6. User interacts with shell
   ↓
7. Shell exits (atexit hook)
   ↓
8. _sync_session_end() → _emit_session_end()
   ↓
9. SessionEventEmitter.emit_session_end()
   ↓
10. Session-Buddy MCP: track_session_end tool
```

## Examples

### Example 1: Inspect Configuration

```python
# Start shell
$ oneiric shell

# In shell:
Oneiric> config
OneiricSettings(server_name='Oneiric Config Server', ...)

Oneiric> config.server_name
'Oneiric Config Server'

Oneiric> config.runtime_paths.cache_dir
PosixPath('/home/user/.cache/oneiric')
```

### Example 2: Validate Configuration

```python
Oneiric> validate_config()
✓ Configuration is valid
```

### Example 3: Reload Settings

```python
# Edit settings/local.yaml externally
$ vim settings/local.yaml

# In shell:
Oneiric> reload_settings()
Settings reloaded

Oneiric> config  # Shows updated values
```

### Example 4: Show Configuration Layers

```python
Oneiric> show_layers()
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Layer   ┃ Source                        ┃ Status             ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ 1. Defaults │ Pydantic field defaults   │ Always active      │
│ 2. YAML      │ settings/oneiric.yaml     │ Committed to git  │
│ 3. Local     │ settings/local.yaml       │ Gitignored        │
│ 4. Environment │ ONEIRIC_* variables     │ Runtime overrides │
└───────────┴───────────────────────────────┴────────────────────┘
```

## Comparison with Other Shells

### Mahavishnu Shell

- **Purpose**: Workflow orchestration and repository management
- **Component Type**: `orchestrator`
- **Adapters**: LlamaIndex, Prefect, Agno
- **Helpers**: `ps()`, `top()`, `errors()`, `sync()`
- **Magic**: `%repos`, `%workflow`

### Oneiric Shell

- **Purpose**: Configuration and lifecycle management
- **Component Type**: `foundation`
- **Adapters**: None (provides to others)
- **Helpers**: `reload_settings()`, `show_layers()`, `validate_config()`
- **Magic**: Base magics only

### Session-Buddy Shell

- **Purpose**: Session tracking and knowledge management
- **Component Type**: `manager`
- **Adapters**: None
- **Helpers**: Session search, knowledge graph queries
- **Magic**: Session-specific magics

## Troubleshooting

### Session Tracking Unavailable

If you see "Session tracking unavailable", ensure Session-Buddy MCP is running:

```bash
# Check Session-Buddy status
cd /path/to/session-buddy
session-buddy mcp status

# Start Session-Buddy MCP
session-buddy mcp start
```

### Import Errors

If you get import errors, ensure you're using the local development version:

```bash
cd /path/to/oneiric
source .venv/bin/activate
python -c "from oneiric.shell import OneiricShell; print('OK')"
```

### Circular Import Errors

The adapter uses relative imports to avoid circular dependencies:

```python
# CORRECT (in adapter.py)
from .core import AdminShell
from .config import ShellConfig

# WRONG (causes circular import)
from oneiric.shell import AdminShell, ShellConfig
```

## Development

### Testing Session Tracking

```python
import asyncio
from oneiric.shell import OneiricShell
from oneiric.core.config import load_settings

async def test():
    config = load_settings()
    shell = OneiricShell(config)

    # Test metadata
    print(shell._get_component_name())  # "oneiric"
    print(shell._get_component_version())  # "0.5.1"
    print(shell._get_adapters_info())  # []

    # Test session tracking
    await shell._notify_session_start()
    print(f"Session ID: {shell.session_id}")

    await shell._notify_session_end()

asyncio.run(test())
```

### Adding New Helpers

To add new convenience functions, edit `_add_oneiric_namespace()` in `adapter.py`:

```python
def _add_oneiric_namespace(self) -> None:
    self.namespace.update({
        # Existing helpers...
        "my_helper": lambda: asyncio.run(self._my_helper()),
    })

async def _my_helper(self) -> None:
    """My custom helper function."""
    # Implementation here
    pass
```

## Files

- **`oneiric/shell/adapter.py`**: OneiricShell implementation
- **`oneiric/shell/core.py`**: Base AdminShell class
- **`oneiric/shell/session_tracker.py`**: SessionEventEmitter for MCP tracking
- **`oneiric/shell/event_models.py`**: Pydantic models for session events
- **`oneiric/cli.py`**: CLI with `oneiric shell` command

## See Also

- [Mahavishnu Admin Shell](/Users/les/Projects/mahavishnu/docs/) - Workflow orchestration shell
- [Session-Buddy MCP](/Users/les/Projects/session-buddy/docs/) - Session tracking service
- [Oneiric Configuration](/Users/les/Projects/oneiric/docs/CONFIG.md) - Configuration guide
