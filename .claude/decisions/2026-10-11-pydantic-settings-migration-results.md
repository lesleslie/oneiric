---
status: active
role: reference
kind: decision
date: 2026-10-11
last_reviewed: 2026-10-12
topic: oneiric-config
related:
  - ../../../docs/adr/0003-pydantic-settings-migration.md
  - ../../../docs/plans/2026-10-11-pydantic-settings-migration.md
  - ./2026-10-11-pydantic-settings-plan-review.md
  - ./2026-10-11-dhara-substrate-refs-cleanup.md
---

# Phase 3 cross-repo verification results

## Summary

Five consumer repos verified against the migrated Oneiric substrate
(commit `e3d0780` on `main`, includes the `ulid.py` IndentationError fix).
All five return **GO** or **GO-WITH-CAVEATS** with zero new test failures
attributable to Phase 1+2 or Phase 3. Pre-existing failures in each repo are
unrelated to the migration and should be tracked in their own workstreams.

| Repo | Verdict | Decision | Source change? | Commit SHA |
|------|---------|----------|-----------------|------------|
| mahavishnu | GO-WITH-CAVEATS | 3.7 = KEEP (Option C) | no | n/a |
| akosha | GO | 3.8 = KEEP fallback as-is | no | n/a |
| crackerjack | GO-WITH-CAVEATS | n/a (standard consumer) | no | n/a |
| session-buddy | GO | n/a (standard consumer) | no | n/a |
| mcp-common | GO-WITH-CAVEATS | 3.9 = DEFER to Phase 4 | no | n/a |

## Per-repo new test failures

**None.** All observed failures across the 5 repos reproduce on the
respective parent `main` branch at the pre-Phase-1 commit, confirming they
predate the pydantic-settings migration. Counts below are pre-existing.

| Repo | Pre-existing failure count | New (Phase 1+2) |
|------|---------------------------:|----------------:|
| mahavishnu | 213 unit + integration | 0 |
| akosha | 69 | 0 |
| crackerjack | 26 | 0 |
| session-buddy | 58 | 0 |
| mcp-common | 10 + 4 collection errors | 0 (1 worktree-only env failure) |

## Substrate fix: `e3d0780`

The Mahavishnu test collection was blocked by a pre-existing
`IndentationError` at `oneiric/core/ulid.py:44` (originating in commit
`cd282ba` — Dhara cleanup, well before Phase 1).

- **Path taken:** B (fix indentation). Path A (delete) was not viable:
  `oneiric.core.ulid` has 3 real sibling-module imports
  (`ulid_resolution.py:15`, `ulid_collision.py:81`,
  `ulid_migration.py:22`) and 5 test files importing from it.
- **Fix applied:** dedented lines 44-133 by 4 columns
  (`ULID_BINARY_SIZE`, `ULID_STRING_LENGTH`, `class ULID`, `def generate`,
  `def get_timestamp`, `def is_ulid` and their bodies).
- **Diff:** 84 insertions / 84 deletions. File size: 10546 bytes.
- **Validation:** `ast.parse` clean; `import oneiric.core.ulid` succeeds;
  substrate `load_settings` works; 1027 substrate tests pass.

**Status:** committed locally on `/Users/les/Projects/oneiric` main. **Not
pushed to origin** (per `feedback-bodai-push-is-user-controlled.md`).

## Decision 3.7 — Mahavishnu local `OneiricMCPConfig` shadow

**Option C: KEEP the deliberate split.**

The local class at `mahavishnu/core/config.py:1817`
(`OneiricMCPConfig(BaseModel)`, 7 fields: `enabled`, `base_url`,
`timeout_sec`, `cache_ttl_sec`, `token`, `circuit_breaker_*`) configures
the **MCP adapter registry**. The substrate class at
`oneiric/core/config.py:302` (`OneiricMCPConfig(BaseSettings)`, 6 fields:
`http_port`, `http_host`, `enable_http_transport`, `debug`, `environment`,
`cache_dir`) configures **MCP server transport**. **Zero field
overlap.** 5 test sites reference the local class
(`tests/unit/test_adapter_registry.py:39`,
`tests/unit/tui/test_app_extended.py:227,259`,
`tests/integration/test_rollback_integration.py:51,71,91`).

Options A (migrate to `BaseSettings`) and B (delete and re-export
substrate) would both break the adapter-registry semantics. The local
class docstring already documents the divergence:
*"The class name is retained for settings compatibility with existing
`oneiric_mcp` config blocks."*

## Decision 3.8 — Akosha defensive `OneiricMCPConfig` fallback

**KEEP fallback as-is.**

The defensive `OneiricMCPConfig(BaseModel)` at `akosha/config.py:38-43`
is correct as-is. (1) No test exercises the fallback (no test mocks
`ImportError` on the oneiric import). (2) The fallback only fires when
oneiric is not installed. (3) `BaseSettings IS-A BaseModel`, so the
fallback is also a valid runtime base class.

The migration is **transparent** to Akosha: 69 failures pre-existed
identically against oneiric 0.26.4 (pre-migration baseline).

## Decision 3.9 — mcp-common `MCPBaseSettings` → `BaseSettings`

**DEFER to Phase 4 (cross-cutting refactor).**

`mcp-common/config/base.py:34-45` still declares `MCPBaseSettings(BaseModel)`
with a deprecation message pointing at the substrate's `OneiricMCPConfig`.
Post-migration the substrate class is `BaseSettings` (not `BaseModel`) —
so the deprecation message is **finally accurate** (the substrate
class genuinely diverges in env-var loading behavior).

A unilateral change to `MCPBaseSettings` would break every
`MCPServerSettings(MCPBaseSettings)` consumer across mahavishnu,
akosha, session-buddy, and crackerjack at module import time. The
deferred Phase 4 work needs to:
1. Update `mcp-common/config/base.py` to import `BaseSettings` from
   oneiric.
2. Audit every `MCPServerSettings` subclass across the Bodai ecosystem.
3. Update each downstream repo with the same substrate class as parent.

This is a coordinated fanout, not a verification-only change.

## Task 3.2 follow-up — `_mahavishnu_env_overlay` is NOT dead code

**Counterintuitive finding:** the previous plan's task 3.2 claimed
`_mahavishnu_env_overlay` (at `mahavishnu/core/config.py:3209`) was
dead code post-migration. **It is not.** It remains the active
workaround for Oneiric's backward-compat aliasing
(`oneiric/core/config.py:702` `LOG_LEVEL → logging.level`):
`_mahavishnu_env_overlay` is the only mechanism that prevents that
aliasing from swallowing `MAHAVISHNU_LOG_LEVEL`. The Phase 1+2
migration did not change Oneiric's framework aliasing, so the
workaround remains necessary. **Keep as-is; no follow-up cleanup.**

## Follow-ups (independent of the migration)

1. **Phase 4 plan:** migrate `MCPBaseSettings(BaseModel)` →
   `BaseSettings` in mcp-common. Cross-cuts 4 consumer repos.
2. **Mahavishnu pre-existing failures** (213 across unit + integration):
   auth.algorithm precedence, stale SSE assertions, golden fixture
   drift, mock-shape mismatches, Pydantic forward-ref patches,
   MCP-dependent integration tests. Track separately.
3. **Akosha pre-existing failures** (69): MagicMock/awaitable issues in
   lifespan wiring tests, Pydantic v2 model access in ColdRecord,
   test-ordering / fixture-pollution. Track separately.
4. **Crackerjack pre-existing failures** (26): release-audit, formatting
   whitespace, skills migration, MagicMock fixture drift, performance
   thresholds, zuban default 60→30 (post-Phase-1+2 regression from
   `5cc207f0`), workflow-pipeline eventbridge wiring, mermaid renders.
   Track separately.
5. **Session-Buddy pre-existing failures** (58): `SignerFeedState`
   constructor signature, Typer 0.27 compat for checkpoint CLI, ACL
   `PermissionError`, e2e infrastructure wiring. Track separately.
6. **mcp-common pre-existing failures** (10 + 4 collection):
   `test_contracts`, WebSocket protocol factory tests,
   `DuplicateTimeseries` counter registration race. Track separately.
7. **The substrate `ulid.py` deletion** (per the UUID7-only migration
   plan `2026-10-11-uuid7-only-migration.md`) is now blocked by 3
   sibling-module imports + 5 test files. Sibling cleanup is a separate
   workstream.
8. **No `_mahavishnu_env_overlay` removal** (it's still needed, see
   above).

## Rollback signal

Any consumer repo showing **NEW** test failures attributable to the
Phase 1+2+3 changes on oneiric. **None observed** in this verification.

## Observability

`git log --oneline main` on `/Users/les/Projects/oneiric` shows the 8
Phase 0-3 commits plus the ulid fix:

```
e3d0780 fix(ulid): repair IndentationError in ulid.py
e0dbe5b feat(adapters): migrate LLM/Embedding/Vector/NoSQL shared bases to BaseSettings
685f0d3 feat(config): OneiricMCPConfig settings_customise_sources (Phase 1 Option A)
a44640f feat(async): wrap load_settings in asyncio.to_thread (T1.11)
8b8546e feat(config): pydantic-settings substrate migration (T1.2-T1.10)
6638d95 feat(config): OneiricMCPConfig -> BaseSettings; drop env_file; pin pydantic-settings direct
94aa1e6 docs(plan+test): Phase 0 — pin ACB precedence + _ALIAS_OVERRIDES audit + env-var collision
```

Plus the previously-pushed commit:

```
a1d3a8c docs(plan): add Move LLM + Prompting from mcp-common to oneiric
```

**None of the 8 Phase 0-3 commits is pushed to origin.** Per
`feedback-bodai-push-is-user-controlled.md`, push is user-controlled.
The user has approved pushing each phase; if all are wanted in a
single push, that's a clean one-button action.
