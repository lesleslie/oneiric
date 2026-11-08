---
title: Restore the two red test groups left by the 0.35.0 bump
description: Two independent test groups were red before this work — three tests in tests/adapters/test_redis_cache.py failed in fixture setup because fakeredis 2.40.0 cannot walk the closure redis-py 8.2.0b1 now captures, and two assertions in tests/unit/test_version_consistency.py failed because the 0.34.0 -> 0.35.0 bump did not re-sync the two doc version stamps. Both trace to the same commit (0470be3). Fixes the dependency by holding redis on a stable release via a targeted uv prerelease-package override, and syncs the doc stamps down to the already-committed pyproject version.
audience: oneiric maintainer
created: 2026-11-08
status: active
role: implementation
topic: testing
date: 2026-11-08
last_reviewed: 2026-11-08
superseded_by: null
blocks_on: []
---

# Restore the two red test groups left by the 0.35.0 bump

**Date:** 2026-11-08
**Status:** in progress
**Affects:** `pyproject.toml`, `uv.lock`, `docs/CLI_REFERENCE.md`, `CLAUDE.md`
**Consumers:** the oneiric test suite; every developer running `uv sync`

## Problem

Two test groups were red before this work. They have **no common
mechanism**, but they do share a **common trigger**: commit `0470be3
chore: bump version to 0.35.0` bumped `pyproject.toml` to 0.35.0 and
refreshed `uv.lock`, and that one commit is what broke both.

| Group | Failures | Failure mode |
|---|---|---|
| `tests/adapters/test_redis_cache.py` | 3 of 5 | `AttributeError` in fixture setup — `FakeRedis()` cannot be constructed |
| `tests/unit/test_version_consistency.py` | 2 of 5 | Doc version stamps still say `0.34.0`; `pyproject.toml` says `0.35.0` |

### Root cause 1 — fakeredis cannot walk redis-py 8.2.0b1's closure

Every one of the three failures fails the same way, in fakeredis's client
construction rather than in the code under test:

```
fakeredis/_clients/_setup.py:25: in _get_args_to_warn
    closure = method.__closure__
E   AttributeError: 'method_descriptor' object has no attribute '__closure__'
```

The chain, traced end to end:

1. redis-py 8.2.0b1 changed `deprecated_args` to build its call-time
   keyword check via `_get_warn_check`, which returns a **builtin method
   descriptor** — `redis/utils.py:253`:

   ```python
   return min_idx, _DictKeys.isdisjoint, names
   ```

2. The `wrapper` closure inside `deprecated_args` captures that
   descriptor, so `Redis.__init__.__closure__` transitively contains
   `dict_keys.isdisjoint` — a C-level `method_descriptor`, not a Python
   function.

3. fakeredis 2.40.0 discovers which arguments redis-py has deprecated by
   walking that closure. `_get_args_to_warn` recurses into **every**
   callable it finds in a closure cell and dereferences `method.__closure__`:

   ```python
   closure = method.__closure__
   if closure is None:
       return set()
   ...
   elif callable(value):
       res.update(_get_args_to_warn(value))
   ```

   A `method_descriptor` has no `__closure__` attribute *at all* — so the
   guard on line 26 never runs, and line 25 raises `AttributeError`
   instead of returning `None`.

Both the sync and async `Redis.__init__` are affected, so
`fakeredis.aioredis.FakeRedis` — the async client these tests use — cannot
be constructed at all.

**Scope of the incompatibility.** `_DictKeys`/`isdisjoint` is **new in
8.2.0b1**. Verified by inspecting the release wheels directly: the symbol
is absent from redis 7.3.1, 7.4.1, 8.0.0, 8.0.1 and 8.1.0. Every stable
release through 8.1.0 is unaffected.

**No upstream fix exists.** fakeredis 2.40.0 (uploaded 2026-10-14) is the
newest release on PyPI; the guard against `method_descriptor` has to land
upstream first.

**What let the beta in.** `[tool.uv] prerelease = "allow"` in
`pyproject.toml` — a repo-wide setting — admitted redis 8.2.0b1, a
four-day-old pre-release, when the stable 8.1.0 was available and
satisfying.

### Root cause 2 — the bump did not re-sync the doc stamps

`tests/unit/test_version_consistency.py` pins two doc surfaces to
`pyproject.toml`:

| Surface | Line | Said | Should say |
|---|---|---|---|
| `docs/CLI_REFERENCE.md` | 16 | `0.34.0` | `0.35.0` |
| `CLAUDE.md` | 11 | `0.34.0` | `0.35.0` |

`0470be3` bumped `pyproject.toml` to 0.35.0 but did not update either
stamp. The prior bump did this correctly — commit `dca1600 fix(docs): sync
the version stamps to 0.34.0` — so this is drift introduced by an
incomplete bump, not a broken guard.

The direction matters: **`pyproject.toml` is the source of truth and is
already at 0.35.0.** The fix syncs the docs *down* to the committed
version. No version number is bumped here; the bump is the operator's.

## Scope

- Hold `redis` on a stable release so fakeredis can construct its client.
- Sync the two doc version stamps to the already-committed 0.35.0.
- **Not** in scope: bumping the version (the operator's), changing the
  repo-wide `prerelease = "allow"` policy, patching fakeredis in
  site-packages, or editing the tests to avoid the broken path.

## Design

### Dependency fix — a targeted uv override, not a version bound

uv supports a **per-package** prerelease policy that overrides the global
one. Adding it to `[tool.uv]`:

```toml
prerelease-package = { redis = "disallow" }
```

This expresses the intent exactly — *redis specifically takes no
pre-releases* — while leaving `prerelease = "allow"` intact for every
other package. It is also durable: it is a persistent setting, so every
future `uv lock` keeps redis stable without needing the flag again.

The alternative — a version bound like `redis<8.2.0` — does **not** work.
Under PEP 440, `8.2.0b1 < 8.2.0`, so a `<8.2.0` bound still admits the
beta. Only an exact pin, a `<8.2.0b1` bound, or a prerelease policy
actually excludes it; the policy is the one that states the real rule.

Measured blast radius — `uv lock --dry-run` reports exactly one change:

```
Update redis v8.2.0b1 -> v8.1.0
```

Nothing else in the 318-package graph moves. The repo-wide
`prerelease = "allow"` was left alone deliberately: switching it to
`if-necessary` also resolves redis to 8.1.0, but it changes resolution
policy for every dependency in the repo, which is a much wider change
than this fix warrants.

### Doc fix — mirror the established precedent

`dca1600` changed **only** the `**Version:**` line in
`docs/CLI_REFERENCE.md`, deliberately leaving the adjacent
`**Last Updated:** 2026-09-09` stamp alone — that date records when the
document's *content* was last reviewed, not when a mechanical version sync
happened. This change follows the same precedent.

## Integration Contract

- **Triggered from:** `uv lock` / `uv sync` reading `[tool.uv]` in
  `pyproject.toml`; `tests/unit/test_version_consistency.py` reading
  `pyproject.toml`, `docs/CLI_REFERENCE.md` and `CLAUDE.md`.
- **Returns to / updates:** `uv.lock` (one version line, plus the
  `redis` requirement hash); `docs/CLI_REFERENCE.md:16`; `CLAUDE.md:11`.
- **Demonstrable by:** `./.venv/bin/pytest tests/adapters/test_redis_cache.py tests/unit/test_version_consistency.py --no-cov`
  — 10 passed, 0 failed (was 5 failed / 5 passed).
- **Rollback signal:** `tests/adapters/test_redis_cache.py` fails again
  with `AttributeError: 'method_descriptor' object has no attribute
  '__closure__'` after any `uv lock` (meaning the override stopped
  applying), or `tests/unit/test_version_consistency.py` fails after the
  next version bump (meaning that bump skipped the stamps again).
- **Observability added:** none at runtime. Group 1's guard is
  fakeredis's own test suite; group 2's guard is the pre-existing
  `test_version_consistency.py`, which is exactly the mechanism that
  caught the drift.

## Integration Notes

- The fix is a **resolution** change, not a code change. Nothing in
  `oneiric/` is touched — the failure was always in the test
  infrastructure's dependency graph.
- `redis` remains a **transitive** dependency (pulled in by
  `fakeredis>=2.21.0`, which requires `redis>=4.3`). It is not added as a
  direct dependency; the uv override acts on the resolution, so no new
  requirement appears in `[project]`.
- The override should be **removed once fakeredis ships the fix**
  (<https://github.com/cunla/fakeredis-py/issues>). Until then it is
  load-bearing: deleting it lets uv resolve redis 8.2.0b1 again and the
  three tests go red.
- `redis 8.2.0b1` was only ever a resolution artifact of the
  2026-11-08 lock refresh. No released oneiric artifact shipped with it.
- Blast radius across the repo: `tests/adapters/test_redis_cache.py` is
  the **only** file that imports the real `fakeredis` package. Every
  other "FakeRedis" in the tree (`tests/adapters/cache/test_redis_mock.py`,
  `tests/adapters/queue/test_redis_streams_mock.py`,
  `tests/adapters/cache/test_multitier_cache.py`,
  `tests/test_coverage_gaps.py`) is a hand-rolled local stub class and is
  unaffected.

## Rollout

1. Add the targeted uv prerelease override to `pyproject.toml`. ✅ done
2. Re-lock and sync the venv; confirm redis resolves to 8.1.0. ✅ done
3. Sync the two doc version stamps to 0.35.0. ✅ done
4. Verify both groups green, then the full suite. ✅ done
5. Record the changelog entry. ✅ done

## Rollback

- **Dependency:** delete the `prerelease-package` line from
  `pyproject.toml` and re-lock — but expect the three
  `test_redis_cache.py` failures to return, because uv will resolve
  redis 8.2.0b1 again.
- **Docs:** restore `0.34.0` in the two stamp locations.

## Non-Goals

- Upgrading or patching fakeredis.
- Changing the repo-wide `prerelease = "allow"` policy.
- Bumping the oneiric version (the operator's call).
- Re-auditing the `**Last Updated:**` stamp in `docs/CLI_REFERENCE.md`
  or the `4218 tests passing` count in `CLAUDE.md` — neither is asserted
  by the consistency guard, and both are outside the two red groups.
