---
status: accepted
role: canonical
kind: decision
date: 2026-09-26
last_reviewed: 2026-09-26
superseded_by: null
blocks_on: []
decision_date: 2026-09-26
topic: deployability-discipline
---

# ADR 0001: Bodai Deployability Discipline — Standalone by Default, Enhanced by Installation

## Status

**Active** — awaiting per-component sign-offs (see [Sign-offs](#sign-offs)). The discipline is in force from this date for new code; existing code is subject to the [Migration Plan](#migration-plan) timeline.

## Context

The Bodai ecosystem (mahavishnu, akosha, session-buddy, crackerjack, oneiric, mcp-common) is composed of independent but cooperative packages. Today, several of those packages drift toward *coupled-by-default*: launching them in isolation throws `ConnectionError` to a peer that isn't running, modules do top-level `from akosha import …`, and pool selectors raise instead of degrading to a local-only fallback.

Three deployment realities drive the need for a written rule:

1. **Standalone use.** Operators routinely install *one* Bodai component for a single workload — Akosha as a vector store, Crackerjack as a quality gate in CI, Mahavishnu as a single-user orchestrator on a laptop. A first-class install must not require the operator to also install and run Session-Buddy + Akosha + Crackerjack before Mahavishnu will boot.

2. **Progressive enhancement.** The same component, when run alongside its peers, should *gain* capabilities — cross-pool routing through Session-Buddy, semantic pattern detection through Akosha, quality-gated routes through Crackerjack. The component does not lose its baseline; it adds an enhancement layer.

3. **Serverless + harness-agnostic deployment.** Cold-start on Lambda / Cloud Run / Fly / a developer laptop must work. The component must not assume a long-lived parent process, must not block on a peer that may be 200 ms away, and must not depend on a specific agent harness (Claude Code, Goose, Aider, Pi, raw curl) to function.

This ADR is the foundation-level discipline that the application-level ADRs (mahavishnu ADR 002 MCP-first, etc.) inherit. It is the *first* ADR in oneiric because oneiric is the package every Bodai core imports; the rule belongs here.

### Options Considered

#### Option 1: Strict Isolation — never import another Bodai core

- **Pros:** Maximally portable; clear rules.
- **Cons:** Forces every component to re-implement Session-Buddy's pool delegation, Akosha's vector store, Crackerjack's quality scorer. Massive duplication; defeats the purpose of an ecosystem.

#### Option 2: Coupled-by-default (current de facto state)

- **Pros:** Easy to write; one obvious code path.
- **Cons:** Install-on-laptop fails, serverless cold-starts hang, harness coupling leaks into core, single-component deployments require mocking half the ecosystem. Violates the user's standing rule against silent fallback (mahavishnu CLAUDE.md "Degraded mode").

#### Option 3: Standalone-by-default, enhanced-by-installation (CHOSEN)

- **Pros:** Each component boots and serves its baseline with zero peer dependencies. Capability detection at runtime turns on enhancements (cross-pool routing, semantic search, quality scoring) when peers are reachable. No mocks required for first-class use.
- **Cons:** Authors must internalize the lazy-import + capability-detect pattern. Existing coupled code must be migrated. New contributors may regress the rule without a guard.

## Decision

Every Bodai core component shall satisfy three composable rules. The rules compose: standalone (packaging) makes harness-agnostic (interface) meaningful; harness-agnostic makes serverless-deployable (runtime) realistic; serverless-deployable reinforces standalone by removing shared-process assumptions.

### Rule 1 — Standalone by Default (Progressive Enhancement)

A component MUST boot and provide its baseline functionality with only its own `[project.dependencies]` installed and no peer Bodai service reachable. When peers are reachable, the component MUST automatically enable enhancements; when they are not, it MUST continue serving the baseline — never raise, never silently fail, never block indefinitely.

Concrete obligations:

- **No top-level imports of other Bodai cores.** `from akosha import …`, `from session_buddy import …`, `from crackerjack import …`, `from mahavishnu import …` MUST NOT appear at module scope in production modules. Use lazy imports inside functions/methods.
- **Capability detection, not assertion.** Probe a peer via its published health endpoint (HTTP `GET <peer>/health`) or local socket on the canonical port (per `BODAI_REPO_REGISTRY.md`). Treat `2xx` + `{"status": "ok"}` as available; everything else (timeout, connection refused, 5xx, malformed JSON) is unavailable.
- **Graceful degradation over failure.** When a peer is unavailable, fall back to a documented baseline behavior (e.g. Mahavishnu's `affinity` pool selector falls back to `least_loaded` against local workers when Session-Buddy is down; Akosha's `pattern_search` falls back to local in-memory indices when Session-Buddy's reflection store is down). Never raise `ConnectionError` to the caller for a missing peer.
- **Optional dependency, not required.** When a peer is in the same wheel but functionally optional, list it in `[project.optional-dependencies]` for the consuming component, not in `[project.dependencies]`. Document the enhancement in the consuming component's README.

### Rule 2 — Harness-Agnostic Interface

A component's public surface MUST be reachable through at least one of: MCP, stdio JSON-RPC, HTTP REST/JSON, or CLI. The component MUST NOT depend on any specific agent harness SDK to function.

Concrete obligations:

- **No harness SDK imports in core paths.** `import anthropic`, `import openai`, `from claude_code import …`, harness-specific helper modules MUST NOT appear in the import graph of any code path reachable from the public surface, with the *single* explicit exception of `mahavishnu/workers/cloud_worker.py` and `mahavishnu/core/model_routing.py` (which are the LLM-calling surface by design).
- **MCP is the primary surface.** Per mahavishnu ADR 002, MCP is canonical. CLI and HTTP are second-class but must exist for harness-agnostic operation.
- **Configuration via env + layered YAML only.** No harness-supplied config object, no implicit globals from a host framework.

### Rule 3 — Serverless-Deployable Runtime

A component MUST be deployable to an ephemeral, stateless execution environment (Lambda, Cloud Run, Fly Machine, a fresh container) without code changes.

Concrete obligations:

- **No filesystem state outside `XDG_RUNTIME_DIR` or env-injected paths.** State directories MUST be configurable via `*_STATE_DIR` env vars; defaults resolve through `XDG_RUNTIME_DIR` or a tempdir, never a hardcoded `/var/lib/<pkg>`.
- **All configuration via env vars or layered YAML.** No hardcoded absolute paths. No reliance on a sibling config file living next to the wheel.
- **No long-lived child processes owned by the parent.** Subprocess pools, background threads that never exit, and shared-memory segments violate serverless. Long-running work is the *caller's* job (queue, worker, separate process); the component itself is short-lived per request.
- **Cold-boot budget ≤ 3 seconds** on a warm container. Import-heavy modules MUST defer work to first call (lazy init), not module load.
- **Externalize shared state.** If two instances must agree on something, that state lives in an external system (DB, object store, queue), not in the component's process memory. Single-instance local state (in-memory caches, scratch files in `XDG_RUNTIME_DIR`) is allowed.

## Rationale

1. **Install-on-laptop is the dominant onboarding path.** New users run *one* component to evaluate it. A first run that crashes because Session-Buddy is not running loses the user; a first run that boots and degrades invites the next step.

1. **Serverless is the deployment story for half the ecosystem.** Mahavishnu workers on RunPod, Akosha ingestion jobs on Cloud Run, Crackerjack in CI — all are ephemeral. Coupled startup violates the deployment target.

1. **Harness agnosticism is non-negotiable now.** The user runs Claude Code, Goose, and Pi interchangeably. A Bodai component that hardcodes Claude Code specifics is a Bodai component the user will eventually fork.

1. **Graceful degradation is cheaper than mocks.** Mocking Akosha for a Mahavishnu unit test is a tax on every contributor. Capability detection that returns "Akosha unreachable → use baseline" is a one-line check the runtime does anyway.

1. **The alternative is silent fallback.** The user's CLAUDE.md explicitly forbids silent fallback in mahavishnu ("Degraded mode: surface the unavailability"). This ADR codifies that posture across the whole ecosystem and turns it into a deployable property.

## Architecture

The capability-detection pattern is the load-bearing piece. Reference sketch:

```python
from __future__ import annotations
import os
import httpx
from functools import lru_cache

PEER_DEFAULT_PORTS = {
    "akosha": 8682,
    "session_buddy": 8678,
    "crackerjack": 8676,
    "mahavishnu": 8680,
}

@lru_cache(maxsize=1)
def peer_reachable(peer: str) -> bool:
    """Capability probe. Cached per process; re-probe on next cold start."""
    host = os.getenv(f"{peer.upper()}_HOST", "127.0.0.1")
    port = int(os.getenv(f"{peer.upper()}_PORT", PEER_DEFAULT_PORTS[peer]))
    try:
        r = httpx.get(f"http://{host}:{port}/health", timeout=0.5)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def with_akosha_enhancement(query: str) -> list[dict]:
    """Use Akosha when reachable, fall back to local index when not."""
    if peer_reachable("akosha"):
        # Lazy import: akosha is NOT a hard dep
        from akosha.client import AkoshaClient
        return AkoshaClient().semantic_search(query)
    return local_fallback_search(query)
```

Notes on the sketch:

- Lazy `from akosha.client import …` inside the function — Rule 1.
- Probe via published `/health` with a tight timeout (≤ 500 ms) — Rule 3.
- `@lru_cache` so we probe once per cold start, not per call — Rule 3 cold-boot budget.
- Fallback is in the same code path — Rule 1 "never raise for a missing peer."

## Migration Plan

For each existing Bodai core (mahavishnu, akosha, session-buddy, crackerjack):

1. **Audit phase.** Run `git grep -nE "^from (akosha|session_buddy|crackerjack|mahavishnu)" -- '*.py'` in the repo's production source. Each hit is a Rule 1 violation. Document the inventory.
2. **Lazy-import conversion.** Move each violation inside the smallest enclosing function. Add a per-package ADR-note link to this ADR as the rationale.
3. **Capability-detect adoption.** Replace each `await peer.method(...)` with a guarded `if peer_reachable(...): await peer.method(...)` + baseline fallback.
4. **Grep guard.** Add a CI step (a `git grep` check, a lint rule, or whatever fits the repo's existing pipeline) that re-runs the audit grep and fails the quality gate on any new top-level cross-Bodai import. The exact mechanism is left to the repo's maintainer.
5. **Serverless smoke test.** Add an integration test that boots the component in a fresh container with no peers reachable and asserts the public surface is responsive within 3 s.

## Enforcement

- **Per-repo enforcement.** Each Bodai core repo SHOULD add a CI step — a `git grep` check, a lint rule, or whatever fits the existing pipeline — that fails on new top-level cross-Bodai imports. The exact mechanism is left to each repo's maintainer; this ADR does not mandate a specific tool or hook.
- **Cross-repo audit.** A periodic Bodai-wide audit (cadence decided by the maintainers) reports per-repo Rule 1 / Rule 2 / Rule 3 compliance.
- **Cross-repo pointer.** Each application repo (mahavishnu, akosha, session-buddy, crackerjack, mcp-common) SHOULD add a one-paragraph `.claude/decisions/deployability-discipline.md` that references this ADR by path. The canonical text lives here, in oneiric.

## Exceptions

Explicit, time-bounded exceptions MUST be enumerated in the consuming component's ADR (or a dedicated `docs/adr/XXXX-<reason>.md`) and reviewed annually. Known acceptable patterns at the time of this writing:

### Intentional couplings (raise when peer unreachable)

- **MahavishnuPool + Session-Buddy delegation** — the `session_buddy` pool type is *defined* by coupling to Session-Buddy; it must raise `PoolConfigError` if Session-Buddy is unreachable, because the pool type has no baseline. This is the *only* currently-known intentional coupling; it is documented in `mahavishnu/docs/adr/004-adapter-architecture.md`.

### Lazy import patterns (raise when peer unavailable for a specific feature)

These three patterns emerged from the 2026-09-26 cross-repo audit (see [`docs/plans/2026-09-26-bodai-deployability-rule1-audit.md`](../plans/2026-09-26-bodai-deployability-rule1-audit.md)). All three are *compatible with* Rule 1 — Rule 1 prohibits top-level imports, not these structured lazy patterns.

1. **Adapter integration** — when a module's purpose is to integrate with a peer (e.g., `oneiric/adapters/vector/agentdb.py:76` integrating with `mcp_common`), the lazy import is acceptable as long as the import failure surfaces a specific exception class (`LifecycleError`, `IntegrationError`, etc.) with clear context about which peer was missing. Adapter cannot function without the peer; raising is correct. *Do NOT* silently degrade to a no-op — that's misleading for an adapter whose entire job is to provide that integration.

2. **Optional-peer with install guidance** — when the dep is OPTIONAL for the package but REQUIRED for a specific function (e.g., `session_buddy/sync.py:608` calling `akosha.processing.embeddings`), the lazy import is acceptable as long as the failure surfaces a friendly `ImportError` with install guidance (e.g., `"Install with: uv add akosha"`). The general-case consumer of the package is unaffected; only the specific feature that needs the peer surfaces the dependency. *Do NOT* swallow the error — the user explicitly opted into the feature and needs clear next steps.

3. **Module-level capability detection** — `FOO_AVAILABLE = importlib.util.find_spec("peer")` at module scope (e.g., `akosha/mcp/server.py:35` checking for `mcp_common.server`) is acceptable. `find_spec` checks if a module *can* be imported without actually loading it; it's the install-time counterpart to `peer_reachable()` (which is the runtime health check). Use to gate optional integration paths at module load, so a missing peer causes a graceful degradation rather than an `ImportError` mid-operation.

### Anti-patterns (still violations, even if lazy)

- **Lazy import inside a function that silently swallows `ImportError`** and returns a sentinel value — hides the dependency from the user. Use pattern 2 above instead (raise with install guidance).
- **`peer_reachable()` probe that raises `ConnectionError`** to the caller when the peer is unreachable — violates the "never raise for missing peer" rule of this ADR.
- **`try: import peer / except: pass` at module scope** — equivalent to a top-level import; if the import succeeds at module load it has the same effect. Use pattern 3 above if the goal is to skip optional integration.
- **Bare `import peer` in a class `__init__`** that doesn't gate behavior on success/failure — defeats the lazy-import benefit. Either raise with context (pattern 1) or check with `find_spec` first (pattern 3).

## Sign-offs

The discipline applies to every Bodai core component. Each component's maintainer must acknowledge before this ADR is treated as fully ratified for that component's codebase.

| Component | Maintainer | Status | Date |
|-----------|------------|--------|------|
| oneiric | @les (self) | Active | 2026-09-26 |
| mahavishnu | @les | Active | 2026-09-26 |
| akosha | @les | Active | 2026-09-26 |
| session-buddy | @les | Active | 2026-09-26 |
| crackerjack | @les | Active | 2026-09-26 |
| mcp-common | @les | Active | 2026-09-26 |

All 6 Bodai core components have signed off on 2026-09-26. Combined with the same-day audit (zero Rule 1 violations), the discipline is fully ratified.

## References

- mahavishnu ADR 002 — MCP-First Design (the harness-agnostic surface this ADR inherits)
- mahavishnu ADR 004 — Adapter Architecture (the Session-Buddy-pool exception above)
- `BODAI_REPO_REGISTRY.md` — canonical port map (drives the `PEER_DEFAULT_PORTS` table)
- oneiric `MCP_SERVER_CLI_STANDARD.md` — the CLI/HTTP surface every Bodai core inherits

## Revision History

- 2026-09-26 — Proposed. Drafted in oneiric worktree `.worktrees/adr-006-deployability-discipline` on branch `adr-006-deployability-discipline`.
