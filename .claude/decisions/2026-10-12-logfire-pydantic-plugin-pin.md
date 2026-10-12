---
status: active
role: implementation
kind: decision
date: 2026-10-12
last_reviewed: 2026-10-12
topic: oneiric-config
related:
  - ./2026-10-11-pydantic-settings-migration-results.md
---

# logfire + pydantic-plugin compatibility pin

## Context

`uv run crackerjack gitignore sync` was emitting two related failures
in the oneiric venv:

1. `UserWarning: ImportError while loading the 'logfire-plugin' Pydantic
   plugin, this plugin will not be installed.` — emitted by
   `pydantic/plugin/_schema_validator.py:40`.
2. `ImportError: cannot import name '_clean_attribute_value' from
   'opentelemetry.attributes'` — root cause of the plugin-load failure.

### The chain

```
import pydantic
  └─ pydantic.plugin._loader.get_plugins()           [_loader.py:22]
       └─ scans entry_points for group="pydantic"   [_loader.py:41]
            └─ finds logfire-sdk's entry point:
               logfire-plugin = logfire.integrations.pydantic:plugin
                 └─ entry_point.load()
                      └─ import logfire.integrations.pydantic
                           └─ import logfire
                                └─ import opentelemetry.sdk.metrics
                                     └─ measurement.py:11
                                          from opentelemetry.attributes import _clean_attribute_value
                                          ImportError
```

### Why the venv broke

- `uv.lock` has `opentelemetry-api==1.44.0`, `opentelemetry-sdk==1.44.0`,
  `logfire==6.0.0b5` — **internally consistent**. SDK 1.44.0's
  `measurement.py` does not import `_clean_attribute_value` (confirmed
  by downloading the wheel and inspecting).
- The venv had `opentelemetry-sdk==1.45.1` and `logfire==6.0.0b8` —
  **drifted from the lock**. SDK 1.45.1's `measurement.py:11` imports
  `_clean_attribute_value`, which was renamed to
  `_clean_extended_attribute_value` upstream before API 1.44.0 shipped.
  The 6.0.0b* betas of logfire were pinned against bleeding-edge OTel
  and never picked up the rename.
- `uv run`'s pre-invocation sync is supposed to reconcile the venv with
  the lock but did not in this case (drift persisted). Use
  `uv sync --frozen` for explicit reconciliation.

### What Bodai source code does

`grep -rn "_clean_attribute_value\|_clean_attribute\|_clean_extended_attribute"`
across all 6 Bodai repos (`oneiric`, `mahavishnu`, `akosha`,
`session-buddy`, `crackerjack`, `mcp-common`): **zero hits** in our
source. Every Bodai import of `opentelemetry.attributes` only pulls
`BoundedAttributes` (public class). The ecosystem is compliant with
public OTel API; the broken import lives entirely in third-party
packages.

## Decision

1. **Pin `logfire` below 6.0** in `pyproject.toml`:
   ```toml
   "monitoring-logfire" = [
       "logfire>=4.37.0,<6.0",
   ]
   ```
   logfire 5.1.1 (resolved by `uv lock`) works cleanly with the locked
   `opentelemetry-sdk==1.44.0` and `opentelemetry-api==1.44.0` pair.
   Bump the upper bound when logfire ships a stable 6.x that fixes
   the OTel skew.

2. **Keep `monitoring-logfire` as an opt-in group.** Default `uv sync`
   does NOT install logfire. Users who want logfire instrumentation
   opt in via `uv sync --group monitoring-logfire`. The
   `LogfireMonitoringAdapter` code already does the correct try/except
   guard at `oneiric/adapters/monitoring/logfire.py:14-17`, so a missing
   package raises `LifecycleError("logfire-not-installed")` at init,
   not at import.

3. **Document the escape hatch** for environments where logfire is
   installed but its pydantic integration is unwanted:
   ```bash
   export PYDANTIC_DISABLE_PLUGINS=logfire-plugin
   ```
   Pydantic reads this env var at
   `pydantic/plugin/_loader.py:27` and skips matching plugins
   (lines 32, 45). Setting it to `1` disables all plugins; setting it
   to a comma-separated list disables specific named plugins.

4. **Document the OTel SDK pin lower bound** indirectly: the current
   pin `opentelemetry-sdk>=1.42.1,<no upper>` will need an upper bound
   added if a future SDK release re-introduces a renamed-symbol skew.
   For now, the SDK/API pair in the lock is stable.

## Verification

### Default flow (no logfire opted in)

```bash
cd /Users/les/Projects/oneiric
uv sync --frozen
uv run python -W error::UserWarning -c "import pydantic"
# OK: pydantic loaded clean — no logfire-plugin warning
```

### Opt-in flow (logfire enabled)

```bash
cd /Users/les/Projects/oneiric
uv sync --frozen --group monitoring-logfire
uv run python -W error::UserWarning -c "import pydantic"
# OK: pydantic loaded clean — no logfire-plugin warning
uv run python -c "from opentelemetry.sdk.metrics import MeterProvider"
# OK: OTel SDK metrics imports clean
uv run python -c "import logfire"
# OK: logfire 5.1.1 imports clean
```

### Manual recipe for the escape hatch

```bash
cd /Users/les/Projects/oneiric
uv sync --frozen --group monitoring-logfire
PYDANTIC_DISABLE_PLUGINS=logfire-plugin uv run python -c "import pydantic"
# OK: pydantic loaded clean; logfire plugin suppressed
```

## Rollback signal

Any of:
- `UserWarning: ImportError while loading the 'logfire-plugin' Pydantic plugin`
  re-emerges at pydantic import time.
- `ImportError: cannot import name '_clean_attribute_value' from
  'opentelemetry.attributes'` re-emerges at SDK metrics import.
- `uv.lock` shows `logfire>=6.0` or `opentelemetry-sdk>=1.45` without
  a verified fix.

Action: re-read this note, check `pyproject.toml` for an unexpected
bump, run `uv lock --check` to confirm lock/pyproject agreement,
re-apply `uv sync --frozen`.

## Observability

- `uv lock` shows `Updated logfire v6.0.0b5 -> v5.1.1` once (proof of
  the fix landing).
- `uv.lock` shows `logfire-cli` and `logfire-sdk` removed (5.x is
  monolithic).
- The pydantic warning can be elevated to a hard error for CI:
  `python -W error::UserWarning -c "import pydantic"` — used in the
  verification recipe above.

## Related

- Plan: `docs/plans/2026-10-11-pydantic-settings-migration.md`
- Decision: `./2026-10-11-pydantic-settings-migration-results.md`