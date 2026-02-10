# Oneiric Operational Modes - Quick Reference

## Quick Start

```bash
# Lite mode (default, local only)
./scripts/dev-start.sh lite

# Standard mode (remote resolution)
./scripts/dev-start.sh standard --manifest-url https://example.com/manifest.yaml

# Using environment variable
export ONEIRIC_MODE=standard
oneiric start
```

## Mode Comparison

| Feature | Lite | Standard |
|---------|------|----------|
| Setup Time | < 2 min | ~ 5 min |
| Remote Resolution | No | Yes |
| Signature Required | Optional | Required |
| Manifest Sync | Manual | Auto |
| External Dependencies | Zero | Dhruva (optional) |
| Best For | Development, Testing | Production, Teams |

## Files Created

**Core Implementation:**
- `oneiric/modes/base.py` - Base interface
- `oneiric/modes/lite.py` - Lite mode
- `oneiric/modes/standard.py` - Standard mode
- `oneiric/modes/utils.py` - Utility functions
- `oneiric/modes/__init__.py` - Mode registry

**Configuration:**
- `config/lite.yaml` - Lite mode config
- `config/standard.yaml` - Standard mode config

**Scripts & Tests:**
- `scripts/dev-start.sh` - Startup script
- `tests/unit/test_modes.py` - Unit tests (32 tests)

**Documentation:**
- `docs/guides/operational-modes.md` - User guide
- `OPERATIONAL_MODES_COMPLETE.md` - Implementation summary

## Usage Examples

```python
# Programmatic usage
from oneiric.modes import create_mode, apply_mode_to_settings
from oneiric.core.config import OneiricSettings

settings = OneiricSettings()
mode = create_mode("standard")
settings = apply_mode_to_settings(settings, mode)
```

## Test Results

```bash
cd /Users/les/Projects/oneiric
python -m pytest tests/unit/test_modes.py -v
# Result: 32 passed in ~5.5 seconds
```

## Environment Variables

```bash
ONEIRIC_MODE=lite                    # Mode selection
ONEIRIC_REMOTE__ENABLED=true         # Enable remote
ONEIRIC_REMOTE__MANIFEST_URL=<url>   # Manifest URL
ONEIRIC_REMOTE__SIGNATURE_REQUIRED=true  # Require signatures
```

## Success Criteria

- ✅ Lite mode works (local only, zero dependencies)
- ✅ Standard mode works (remote resolution)
- ✅ Configuration files created
- ✅ Utility functions implemented
- ✅ Startup script created
- ✅ Documentation complete
- ✅ Tests passing (32/32)

## Status: COMPLETE

All phases implemented and tested. Ready for use.
