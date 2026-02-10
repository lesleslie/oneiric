# Oneiric Operational Modes Implementation Plan

## Overview

Implement progressive complexity operational modes (Lite and Standard) for Oneiric, similar to other ecosystem projects (Session-Buddy, Mahavishnu, Akosha, Dhruva).

## Objectives

1. **Reduce setup complexity** - New users can start with minimal configuration
2. **Progressive enhancement** - Add features as needed, not all at once
3. **Clear tradeoffs** - Each mode has well-defined capabilities and limitations
4. **Easy migration** - Clear path from Lite to Standard mode

## Mode Comparison

| Feature | Lite Mode | Standard Mode |
|---------|-----------|---------------|
| **Setup Time** | < 2 min | ~ 5 min |
| **Config Source** | Local files only | Local + Remote |
| **Remote Resolution** | No | Yes |
| **Cloud Backup** | No | Yes |
| **Manifest Sync** | Manual only | Auto-sync with watch |
| **Signature Verification** | Optional | Required |
| **External Services** | Zero dependencies | Optional Dhruva remote |
| **Best For** | Development, Testing, CI/CD | Production, Multi-server |

## Phase 1: Create Mode System

### 1.1 Base Mode Interface

**File**: `oneiric/modes/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ModeConfig:
    """Configuration for an operational mode."""
    name: str
    remote_enabled: bool
    signature_required: bool
    manifest_sync_enabled: bool
    cloud_backup_enabled: bool
    # Additional settings
    additional_settings: dict[str, Any]

class OperationMode(ABC):
    """Abstract base class for operational modes."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Get mode name."""
        ...

    @abstractmethod
    def get_config(self) -> ModeConfig:
        """Get mode configuration."""
        ...

    def validate_environment(self) -> list[str]:
        """Validate environment supports this mode."""
        return []

    def get_startup_message(self) -> str:
        """Get startup message."""
        return f"Starting Oneiric in {self.name} mode..."
```

### 1.2 Lite Mode

**File**: `oneiric/modes/lite.py`

- **Remote Resolution**: Disabled
- **Signature Verification**: Optional
- **Manifest Sync**: Manual only
- **Cloud Backup**: Disabled
- **External Dependencies**: Zero

### 1.3 Standard Mode

**File**: `oneiric/modes/standard.py`

- **Remote Resolution**: Enabled
- **Signature Verification**: Required
- **Manifest Sync**: Auto-sync with watch
- **Cloud Backup**: Enabled (optional)
- **External Dependencies**: Dhruva (optional)

### 1.4 Mode Registry

**File**: `oneiric/modes/__init__.py`

```python
def create_mode(mode_name: str, config: OneiricSettings) -> OperationMode:
    """Create mode instance by name."""
    mode_classes = {
        "lite": LiteMode,
        "standard": StandardMode,
    }
    # ...
```

## Phase 2: Create Configuration Files

### 2.1 Lite Mode Config

**File**: `config/lite.yaml`

```yaml
app:
  name: "oneiric"
  environment: "dev"

remote:
  enabled: false
  signature_required: false
  refresh_interval: null

profile:
  name: "lite"
  remote_enabled: false
  inline_manifest_only: true
  watchers_enabled: true
  supervisor_enabled: false
```

### 2.2 Standard Mode Config

**File**: `config/standard.yaml`

```yaml
app:
  name: "oneiric"
  environment: "production"

remote:
  enabled: true
  signature_required: true
  refresh_interval: 300.0
  manifest_url: null  # Set via CLI or env

profile:
  name: "standard"
  remote_enabled: true
  inline_manifest_only: false
  watchers_enabled: true
  supervisor_enabled: true
```

## Phase 3: CLI Integration

### 3.1 Add Mode Option

**File**: `oneiric/cli.py`

```python
@app.command()
def start(
    mode: str = typer.Option("lite", "--mode", "-m", help="Operational mode (lite, standard)"),
    manifest_url: str = typer.Option(None, "--manifest-url", "-u", help="Remote manifest URL (standard mode)"),
    # ... existing options
):
    """Start Oneiric in the specified mode."""
    # Load mode-specific configuration
    # Apply mode settings
    # Display startup message
```

### 3.2 Mode Detection

```python
def detect_mode() -> str:
    """Detect operational mode from environment."""
    return os.getenv("ONEIRIC_MODE", "lite").lower()
```

## Phase 4: Create Startup Script

**File**: `scripts/dev-start.sh`

```bash
#!/bin/bash
MODE=${1:-lite}

case $MODE in
  lite)
    echo "Starting Oneiric in lite mode..."
    oneiric start --mode=lite
    ;;
  standard)
    echo "Starting Oneiric in standard mode..."
    oneiric start --mode=standard "${@:2}"
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [lite|standard] [options...]"
    exit 1
    ;;
esac
```

## Phase 5: Documentation

### 5.1 Operational Modes Guide

**File**: `docs/guides/operational-modes.md`

Sections:
- Overview of modes
- Feature comparison matrix
- Lite mode setup
- Standard mode setup
- Migration guide (Lite → Standard)
- Troubleshooting

### 5.2 Update README

Add section to `README.md`:

```markdown
## Operational Modes

Oneiric supports two operational modes for progressive complexity:

### Lite Mode (Default)

```bash
oneiric start --mode=lite
```

- Zero external dependencies
- Local configuration only
- Manual manifest loading
- < 2 minute setup

### Standard Mode

```bash
oneiric start --mode=standard --manifest-url=https://example.com/manifest.yaml
```

- Remote manifest resolution
- Auto-sync with watch
- Signature verification required
- ~ 5 minute setup

See [Operational Modes Guide](docs/guides/operational-modes.md) for details.
```

## Success Criteria

- [ ] Lite mode works (local only, zero dependencies)
- [ ] Standard mode works (remote resolution enabled)
- [ ] CLI integration complete (--mode option)
- [ ] Startup script created (`scripts/dev-start.sh`)
- [ ] Documentation created (`docs/guides/operational-modes.md`)
- [ ] Tests added for mode system
- [ ] README updated with mode section
- [ ] Migration guide documented

## Implementation Order

1. **Phase 1**: Create mode system (base.py, lite.py, standard.py, __init__.py)
2. **Phase 2**: Create configuration files (lite.yaml, standard.yaml)
3. **Phase 3**: CLI integration (add --mode option)
4. **Phase 4**: Create startup script (dev-start.sh)
5. **Phase 5**: Documentation (operational-modes.md, README update)
6. **Testing**: Add unit tests for mode system
7. **Validation**: Test both modes end-to-end

## Notes

- Mode-specific settings override defaults from `OneiricSettings`
- Environment variable `ONEIRIC_MODE` can set default mode
- Mode configuration uses existing `RuntimeProfileConfig` pattern
- Backward compatibility: existing configs work as "standard" mode
- Signature verification in lite mode is optional (security warning)
