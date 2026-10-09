---
status: active
role: implementation
date: 2026-10-05
last_reviewed: 2026-10-05
topic: routing-composition
title: "Migrate Oneiric CLI/MCP loader from ~/.oneiric/settings.yaml to Oneiric XDG loader"

---

# Migrate Oneiric CLI/MCP loader from `~/.oneiric/settings.yaml` to the XDG loader

## 1. Outcome

`oneiric.cli.mcp` and `scripts/launch_mcp.py` read their config through `oneiric.core.config.load_settings()` — the same XDG-compliant loader already used by `main.py`, `oneiric.runtime.watchers`, and every downstream Bodai consumer. The legacy `~/.oneiric/settings.yaml` path is dropped outright (no deprecation window — this is pre-1.0 software and per `feedback-no-backwards-compat-pre-1.0.md` we replace, not extend).

Concretely: a single `ONEIRIC_OBSERVABILITY__CONNECTION_STRING=...` env var or a `~/.config/oneiric/local.yaml` `observability:` section will reach both the Oneiric MCP server and any other Bodai consumer that calls `load_settings(project_name="oneiric")`. No more two-source-of-truth.

## 2. Goals

1. `oneiric.cli.mcp` reads `auth:` via `load_settings()` instead of `load_yaml_auth_section()` + hand-rolled path resolution.
2. `scripts/launch_mcp.py` stops hardcoding `~/.oneiric/settings.yaml` in its typer `--settings-path` default.
3. `OneiricSettings` exposes the auth section as a typed `OneiricMCPAuthConfig` Pydantic field so a `load_settings()` call returns it with full type validation (closes the `extra="allow"` gap).

## 3. Non-Goals

- **Adding new configuration keys.** This is a pure loader migration — no new fields, no new defaults.
- **Unifying the `OneiricMCPAuthConfig` env-var contract** (`ONEIRIC_AUTH_*`) with the `OneiricSettings` nested env-var contract (`ONEIRIC_*__*`). Out of scope; tracked separately if pursued.
- **Migrating `mahavishnu`/`akosha`/`session-buddy` config loaders** — they already use `load_settings()`.
- **Deleting `~/.oneiric/settings.yaml` from this machine** — the operator's `.bak.legacy-2026-09-27.bak` and live file are theirs to manage. The CLI just stops reading it.
- **Fixing `auth.service_name` (dead key, hardcoded in `load_auth_config` line 117)** — out of scope. Pre-existing inertness, not introduced by this migration.

## 4. Current Findings

### 4.1 The two parallel config paths

| Surface | Loader | Path |
|---------|--------|------|
| `main.py:38` | `oneiric.core.config.load_settings()` | XDG + project + env (10 layers, per `oneiric/core/config.py:316-516`) |
| `oneiric/cli/mcp.py:45` + `:99` | `DEFAULT_SETTINGS_PATH = Path.home() / ".oneiric" / "settings.yaml"` then `load_yaml_auth_section()` | Single hardcoded path |
| `scripts/launch_mcp.py:193-194` | typer default `str(Path.home() / ".oneiric" / "settings.yaml")` | Same hardcoded path |

`main.py` (the Python CLI) was migrated to `load_settings()` already. The MCP-side CLI and the launchd-friendly wrapper were NOT migrated and still read the legacy file.

### 4.2 What's in the legacy `~/.oneiric/settings.yaml`

```yaml
auth:                 # loaded by load_yaml_auth_section() → OneiricMCPAuthConfig
  enabled: false
  service_name: oneiric
  providers: {}

selections: {}        # NOT consumed anywhere
provider_settings: {} # NOT consumed anywhere
options:
  workflow:
    queue_category: "queue"  # NOT consumed anywhere
```

The CLI only ever reads the `auth:` block. The `selections:` / `provider_settings:` / `options.workflow.queue_category:` keys are 100% inert — `resolver_settings_from_config()` (`oneiric/core/config.py:519-532`) reads `settings.adapters.selections` etc., never the top-level. They are leftover from a pre-`OneiricSettings` CLI shape that was deleted in `ff93919 chore(oneiric): delete legacy aiohttp substrate server (REQ-008)`.

### 4.3 What `OneiricSettings` already covers

Per `oneiric/core/config.py:274-313`:

- `app`, `adapters`, `services`, `tasks`, `events`, `workflows`, `actions`, `secrets`, `remote`, `logging`, `lifecycle`, `plugins`, `profile`, `runtime_paths`, `runtime_supervisor`, `observability` — all represented as typed nested fields.
- `auth` — **NOT** represented as a typed field. Currently exposed only via `extra="allow"` (line 278) as an unvalidated dict.
- `mcp` (server host/port/cache-dir) — **NOT** nested. A separate `OneiricMCPConfig` model exists (`oneiric/core/config.py:259-271`) with `env_prefix="ONEIRIC_MCP_"`, but it is not nested under `OneiricSettings`. Decision: do NOT nest it. The MCP server reads `OneiricMCPConfig` directly from env vars (`ONEIRIC_MCP_*`) and never sees the legacy YAML file.

### 4.4 Why this hasn't been migrated already

`git log -S DEFAULT_SETTINGS_PATH` shows the constant was added in `a33cb5a feat(oneiric/cli): add oneiric mcp subcommand (REQ-007)` and never removed. No stashes, no migration-related branches. The `~/.oneiric/settings.yaml.legacy-2026-09-27.bak` is unrelated to this work — it's a timestamped backup of the live file (created before the `2e916ea` TRY004 fix or the `cf89f25` RuntimeError fix on `load_yaml_auth_section`). The "legacy" in the filename is misleading. We get a clean slate.

## 5. Requirements

### 4.4 Why this hasn't been migrated already

`git log -S DEFAULT_SETTINGS_PATH` shows the constant was added in `a33cb5a feat(oneiric/cli): add oneiric mcp subcommand (REQ-007)` and never removed. No stashes, no migration-related branches. The `~/.oneiric/settings.yaml.legacy-2026-09-27.bak` is unrelated to this work — it's a timestamped backup of the live file (created before the `2e916ea` TRY004 fix or the `cf89f25` RuntimeError fix on `load_yaml_auth_section`). The "legacy" in the filename is misleading. We get a clean slate.

## 5. Requirements

```yaml
requirements:
  - id: REQ-CLI-XDG-001
    title: "CLI uses load_settings()"
  - id: REQ-CLI-XDG-002
    title: "OneiricSettings.auth is typed OneiricMCPAuthConfig"
  - id: REQ-CLI-XDG-003
    title: "launch_mcp.py drops --settings-path"
  - id: REQ-CLI-XDG-004
    title: "Behavior tests for XDG loader"
```

## 6. Implementation Phases

### Phase 1: Recon (no code change)

**Goal:** Produce a precise list of every key the legacy `~/.oneiric/settings.yaml` supports and which Pydantic field (if any) it maps to.

**Tasks:**
- `git grep -n "auth\." oneiric/mcp/config.py` — read `OneiricMCPAuthConfig` and `load_auth_config` to enumerate the auth-section shape.
- `cat ~/.oneiric/settings.yaml` against the field list to produce a coverage matrix.
- `python -c "from oneiric.core.config import load_settings; print(load_settings().model_dump_json(indent=2))"` from `~/Projects/oneiric` to capture the effective config when the loader is invoked fresh.
- (Bonus) If a colleague has a customized legacy file (not in this repo), enumerate it too.

**Exit criteria:**
- A `docs/plans/2026-10-05-oneiric-cli-loader-xdg-migration/recon.md` (or inline section) listing every legacy key and its target Pydantic field, with "GAP" markers where no target exists.

#### Integration Contract

- **Triggered from**: Pre-plan reconnaissance — no user-triggered entry point.
- **Returns to / updates**: `docs/plans/2026-10-05-oneiric-cli-loader-xdg-migration.md` §5 Requirements table and §9 ReMark Section.
- **Demonstrable by**: `cat docs/plans/2026-10-05-oneiric-cli-loader-xdg-migration.md | grep -c "GAP"` returns a non-zero count if gaps remain.
- **Rollback signal**: None — this phase writes only to docs.
- **Observability added**: None.

### Phase 2: Schema completeness (fulfills REQ-CLI-XDG-002)

**Goal:** `OneiricSettings.auth` is a typed `OneiricMCPAuthConfig` so the `auth:` block from any XDG or project layer is validated, not just stashed in `__pydantic_extra__`.

**Tasks:**
- Add `auth: OneiricMCPAuthConfig = Field(default_factory=OneiricMCPAuthConfig)` to `OneiricSettings` in `oneiric/core/config.py` (after the existing nested fields).
- Import `OneiricMCPAuthConfig` from `oneiric.mcp.config` (currently lives there, line 60). Verify the import doesn't create a cycle — `oneiric/core/config.py` is the foundational config module, `oneiric/mcp/config.py` may import from core but not vice-versa.
- If a cycle exists: move `OneiricMCPAuthConfig` to `oneiric/core/auth_config.py` and re-export from `oneiric/mcp/config.py` for backwards-compat within the `oneiric.mcp` package.
- Confirm `cd ~/Projects/oneiric && .venv/bin/python -c "from oneiric.core.config import load_settings; s=load_settings(); print(type(s.auth).__name__, s.auth.enabled)"` prints `OneiricMCPAuthConfig False`.
- Verify `pydantic_extra` no longer contains an `auth` key after the change.

**Exit criteria:**
- `s.auth` is a `OneiricMCPAuthConfig` instance, not a dict.
- `pydantic_extra` is empty (or contains only documented legacy keys like `selections`/`provider_settings`/`options` if those are kept on the model — they're dead code but harmless).
- All existing `pytest` tests that touch `load_settings()` pass.

#### Integration Contract

- **Triggered from**: `oneiric.core.config.load_settings()` invoked by every consumer (CLI, MCP server, downstream Bodai repos).
- **Returns to / updates**: `OneiricSettings.auth` is typed; `pydantic_extra` shrinks.
- **Demonstrable by**: `cd ~/Projects/oneiric && .venv/bin/python -c "from oneiric.core.config import load_settings; s=load_settings(); assert type(s.auth).__name__ == 'OneiricMCPAuthConfig'"` exits 0.
- **Rollback signal**: `load_settings()` raises `ValidationError` on first boot — `git revert` Phase 2 commit.
- **Observability added**: None — schema change is internal.

### Phase 3: CLI loader swap (fulfills REQ-CLI-XDG-001)

**Goal:** `oneiric.cli.mcp` reads config from `load_settings()`.

**Tasks:**
- Replace `DEFAULT_SETTINGS_PATH = Path.home() / ".oneiric" / "settings.yaml"` (`oneiric/cli/mcp.py:45`) with a function `_resolve_settings_layer()` that returns a `OneiricSettings` instance via `load_settings(project_name="oneiric", project_root=Path(__file__).resolve().parent.parent.parent)`.
- Replace `_load_auth_from_settings()` (`oneiric/cli/mcp.py:105-116`) with a function that reads `settings.auth` directly and wraps it in the existing `OneiricMCPAuthConfig.from_env()` for the env-var overlay contract.
- Update the `_resolve_settings_path()` function (`:95-112`) to either (a) return the path of the highest-priority existing layer, or (b) be deprecated in favor of `load_settings()`. Decision: option (b); remove the function entirely.
- Update the CLI `--settings-path` arg (`:224`) to advertise the XDG-canonical default.

**Exit criteria:**
- `oneiric.cli.mcp` no longer references `~/.oneiric/settings.yaml` (verified with `grep`).
- `cd ~/Projects/oneiric && .venv/bin/python -c "from oneiric.cli.mcp import _resolve_settings_layer; print(_resolve_settings_layer().auth)"` returns a populated `OneiricMCPAuthConfig`.

#### Integration Contract

- **Triggered from**: `oneiric mcp start|status|health|stop` (the four subcommands that call `_load_auth_from_settings()`).
- **Returns to / updates**: `OneiricSettings.auth` and `OneiricSettings.mcp` carry the values; the legacy path is no longer read at CLI startup.
- **Demonstrable by**: `cd ~/Projects/oneiric && .venv/bin/python -c "import os; os.environ['ONEIRIC_AUTH_ENABLED']='true'; from oneiric.cli.mcp import _resolve_settings_layer; assert _resolve_settings_layer().auth.enabled is True"` exits 0.
- **Rollback signal**: `oneiric mcp start` fails with `AttributeError` on missing `_resolve_settings_layer` — `git revert` Phase 3 commit.
- **Observability added**: Existing `_load_auth_from_settings` logs `auth-config-loaded` on success and `error` on failure (per `oneiric/mcp/config.py:115`). No new metrics.

### Phase 4: launch_mcp.py typer default (fulfills REQ-CLI-XDG-003)

**Goal:** `scripts/launch_mcp.py` no longer hardcodes `~/.oneiric/settings.yaml`.

**Tasks:**
- Replace the typer default at `scripts/launch_mcp.py:193-194` with `None` and have the loader fall back to `load_settings()` when `--settings-path` is omitted.
- Drop the explicit `--settings-path` argument entirely if no caller uses it (the only known caller is the launchd plist, and the plist should be updated to drop it).
- Update `scripts/launch_mcp.py:10` (the comment about the launchd plist) to reflect the new path-or-no-path behavior.

**Exit criteria:**
- `grep "settings.yaml" scripts/launch_mcp.py` returns no occurrences outside docstrings/comments.
- `bash scripts/launch_mcp.py --help` no longer advertises a `--settings-path` argument (or shows a non-legacy default).

#### Integration Contract

- **Triggered from**: `bash scripts/launch_mcp.py` invoked directly or via the launchd plist `com.mcp.oneiric`.
- **Returns to / updates**: No new persisted state; the wrapper now hands the launched MCP server a `OneiricSettings` instance.
- **Demonstrable by**: `bash scripts/launch_mcp.py --help` exits 0 and does not mention `~/.oneiric/settings.yaml`.
- **Rollback signal**: Wrapper exits 1 with a path-resolution error — `git revert` Phase 4 commit.
- **Observability added**: Existing wrapper logs `launch-config-loaded` style messages (per `oneiric/cli/mcp.py` pattern). No new metrics.

### Phase 5: Tests (fulfills REQ-CLI-XDG-005)

**Goal:** Behavior pinned against the new XDG loader.

**Tasks:**
- Add `tests/unit/test_cli_xdg_loader.py` covering:
  - XDG layer override reaches `OneiricSettings.auth`.
  - Project layer `settings/oneiric.yaml` is loaded.
  - Env var `ONEIRIC_AUTH_ENABLED=true` reaches `OneiricSettings.auth.enabled`.
- Add `tests/integration/test_oneiric_mcp_starts_via_xdg.py` spinning up `oneiric mcp start` against a fixture XDG directory and asserting `port 8681` is bound.
- Confirm `crackerjack run -p fast_hooks` still passes (ruff/mypy/ty/basic tests).

**Exit criteria:**
- `pytest tests/unit/test_cli_xdg_loader.py tests/integration/test_oneiric_mcp_starts_via_xdg.py -v` exits 0.
- `crackerjack run -v` exits 0.

#### Integration Contract

- **Triggered from**: CI test run, manually triggered via `pytest`.
- **Returns to / updates**: Test artifacts in `tests/unit/` and `tests/integration/`.
- **Demonstrable by**: `pytest tests/unit/test_cli_xdg_loader.py::test_xdg_layer_override -v` exits 0.
- **Rollback signal**: Test failure → fix the code under test, not the test.
- **Observability added**: None — tests are operational signals.

### Phase 6: Docs

**Goal:** Operators and downstream consumers find the new path.

**Tasks:**
- Update `oneiric/README.md` to reference `~/.config/oneiric/local.yaml` (XDG) as the canonical path.
- Update `docs/CONFIGURATION.md` (or its oneiric equivalent) with the loader precedence list.
- Add an entry to `docs/plans/PLAN_INDEX.md` once the plan is no longer `draft`.
- Drop the now-stale comment in `~/.config/oneiric/local.yaml` about the loader GAP (the gap is closed by this migration).

**Exit criteria:**
- `grep -r "~/.oneiric/settings.yaml" oneiric/` returns no prescriptive references (only `migration_guide` style mentions are OK).
- `PLAN_INDEX.md` lists `2026-10-05-oneiric-cli-loader-xdg-migration.md` with status `active`.

#### Integration Contract

- **Triggered from**: Plan promotion to `active` and to `shipped`.
- **Returns to / updates**: `PLAN_INDEX.md` table; `oneiric/README.md` and `docs/CONFIGURATION.md`.
- **Demonstrable by**: `grep -A1 "2026-10-05" oneiric/docs/plans/PLAN_INDEX.md` returns the entry.
- **Rollback signal**: None — docs changes have no rollback beyond `git revert`.
- **Observability added**: None.

## 7. Required Code Changes

- [ ] `oneiric/core/config.py` — add `auth: OneiricMCPAuthConfig` field to `OneiricSettings`. Resolve any import-cycle by relocating `OneiricMCPAuthConfig` to `oneiric/core/auth_config.py`. Fulfils REQ-CLI-XDG-002.
- [ ] `oneiric/cli/mcp.py` — replace `_load_auth_from_settings()` with a function that reads `settings.auth` (typed `OneiricMCPAuthConfig`) and wraps it in `OneiricMCPAuthConfig.from_env()`. Remove `DEFAULT_SETTINGS_PATH`, `_resolve_settings_path`, `load_yaml_auth_section` import, and the `--settings-path` typer arg. Fulfils REQ-CLI-XDG-001.
- [ ] `scripts/launch_mcp.py` — drop the `--settings-path` typer arg entirely. Update the line 10 launchd-plist comment. Fulfils REQ-CLI-XDG-003.
- [ ] `tests/unit/test_cli_xdg_loader.py` (new) — XDG/project/env coverage of `OneiricSettings.auth`. Fulfils REQ-CLI-XDG-004.
- [ ] `tests/integration/test_oneiric_mcp_starts_via_xdg.py` (new) — end-to-end start against XDG fixture. Fulfils REQ-CLI-XDG-004.
- [ ] `oneiric/mcp/config.py` — drop `load_yaml_auth_section()` if no other caller. Re-export `OneiricMCPAuthConfig` from its new home.
- [ ] `~/Library/LaunchAgents/com.mcp.oneiric.plist` — drop `--settings-path` arg.
- [ ] `oneiric/README.md`, `docs/CONFIGURATION.md`, `docs/plans/PLAN_INDEX.md` — docs updates.

## 8. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|----------------|------------------|---------------------|
| `cd ~/Projects/oneiric && .venv/bin/python -c "from oneiric.core.config import load_settings; s=load_settings(); assert type(s.auth).__name__ == 'OneiricMCPAuthConfig'"` | exit 0 | terminal |
| `cd ~/Projects/oneiric && .venv/bin/python -c "import os; os.environ['ONEIRIC_AUTH_ENABLED']='true'; from oneiric.core.config import load_settings; assert load_settings().auth.enabled is True"` | exit 0 | terminal |
| `grep -n "DEFAULT_SETTINGS_PATH\|load_yaml_auth_section" oneiric/cli/mcp.py oneiric/mcp/config.py` | no hits in production code | terminal |
| `grep "settings.yaml" scripts/launch_mcp.py` | no occurrences outside docstrings/comments | terminal |
| `pytest tests/unit/test_cli_xdg_loader.py -v` | all green | terminal |
| `pytest tests/integration/test_oneiric_mcp_starts_via_xdg.py -v` | all green | terminal |
| `crackerjack run -v` | 11/11 comprehensive hooks pass | terminal |
| `ONEIRIC_AUTH_ENABLED=true oneiric mcp status` | status reads "enabled: True" without restart-required | terminal |
| `launchctl list \| grep oneiric` | still running, port 8681 still bound | terminal |
| `curl -s http://127.0.0.1:8681/health` | 200 OK | terminal |

## 9. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Import cycle: `oneiric.core.config` would import `oneiric.mcp.config` to get `OneiricMCPAuthConfig`, but `oneiric.mcp.config` may already import from core | Medium | Phase 2 detects via trial import; if cycle, move `OneiricMCPAuthConfig` to `oneiric/core/auth_config.py` and re-export from `oneiric/mcp/config.py` for backward compatibility within that package |
| `load_settings()` exposes the typed `OneiricMCPAuthConfig` differently than `load_yaml_auth_section()` did — e.g., `from_env()` semantics now fire through pydantic-settings instead of `OneiricMCPAuthConfig.from_env()` | Medium | Phase 3 keeps `OneiricMCPAuthConfig.from_env()` as the env-var overlay source of truth; CLI calls `settings.auth` first, then `from_env(raw_overrides)` |
| Launchd plist passes `--settings-path ~/.oneiric/settings.yaml` and breaks after wrapper change | Low | Phase 4 updates the plist explicitly. Phase 5 integration test confirms plist still works after update. |
| Operator has `~/.oneiric/settings.yaml` with a key not in `OneiricMCPAuthConfig` (e.g. `auth.service_name`) — `load_settings()` raises `ValidationError` (typed `auth` is strict) | Low | Pre-1.0 software per `feedback-no-backwards-compat-pre-1.0.md`. Document in Phase 6; operator can drop the inert keys manually. |
| `OneiricMCPAuthConfig` is a `@dataclass`, not a Pydantic BaseModel — pydantic-settings may not preserve it through deep_merge cleanly | Medium | Phase 2 trial: confirm `load_settings().auth asdict()` equals a manually-constructed `OneiricMCPAuthConfig(enabled=False)` |

## 10. Decision Rule

Ship when:

1. Phases 1-5 are complete and `crackerjack run -v` passes 11/11.
2. The launchd plist is updated, plist still works.

**Out of scope for "ship now"**: unifying env-var conventions across `ONEIRIC_AUTH_*` vs. `ONEIRIC_MCP_*`, fixing the dead `auth.service_name` (hardcoded in `load_auth_config`), deleting `~/.oneiric/settings.yaml` from operator machines.

## References

- `oneiric/core/config.py:316-516` — `load_settings()` XDG loader
- `oneiric/cli/mcp.py:45, 95-116` — current hardcoded legacy path
- `scripts/launch_mcp.py:10, 193-194` — wrapper's hardcoded default
- `oneiric/mcp/config.py:25` — `load_yaml_auth_section()` (the function being replaced)
- `oneiric/main.py:38` — the correctly-migrated CLI surface (reference for Phase 3)
- `mahavishnu/docs/plans/TEMPLATE.md` — Integration Contract template (canonical pattern)
- `~/.claude/CLAUDE.md` § "Plans / specs path preference" — `docs/plans/YYYY-MM-DD-<feature-name>.md` is the canonical path
- `~/.claude/CLAUDE.md` § "feedback-no-backwards-compat-pre-1.0.md" — replace not extend; no deprecation windows

## Status Lifecycle

This plan starts as `draft, planning`. Promote to `active, in-progress` once Phase 1 is complete. Promote to `shipped, complete` once Phases 1-6 are merged and the launchd plist is verified.
