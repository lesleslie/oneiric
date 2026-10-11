---
status: active
role: canonical
kind: decision
date: 2026-10-11
last_reviewed: 2026-10-11
superseded_by: null
blocks_on: []
decision_date: 2026-10-11
topic: adapter-registry
---

# ADR 0002: Oneiric Adapter Contract — Single Canonical Specification

## Status

**Active** as of 2026-10-11. The full contract lives in
[`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md);
this ADR records the *decision* to make that spec canonical and the
context that motivated it.

## Context

The requirements for "what makes a Python class an Oneiric adapter" are
defined across five places today, none of which is canonical:

1. `oneiric/adapters/metadata.py:21` — the `AdapterMetadata` Pydantic
   model (the static schema).
2. `oneiric/adapters/bridge.py:25` — `AdapterBridge` (the runtime
   access pattern).
3. `oneiric/core/resolution.py:41` — the `Candidate` model + scoring
   algorithm (the discovery mechanism).
4. Module-level docstrings scattered across `mcp/adapter_registry.py`,
   `mcp/server.py:537-542`, and `adapters/bootstrap.py:160-170` (the
   lifecycle + registration story).
5. The README's "Adapter registry" table row (`README.md:79`).

New adapter authors have to grep across these to assemble the contract.
Past Dhara-cleanup work (see
`.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`) showed
that this scattering causes rot: docstrings drift apart over time and
operators following them end up implementing against a half-correct
picture (e.g. the deleted `mcp_pusher.py` POSTed to a non-existent
service).

The contract also has three pieces that are implicit, not stated
anywhere:

- **No abstract base class.** Adapter-ness is a registration contract
  satisfied by exposing `AdapterMetadata` + three async lifecycle
  methods. New adapter authors often reach for inheritance first.
- **Cross-component discovery path.** Other Bodai components discover
  Oneiric's adapter catalog through `mcp__oneiric__*` tools, not through
  import. This was implicit after the Dhara decomposition; the
  surfaces it but doesn't surface the *why*.
- **`REMOTE_MANIFEST` source path.** After the decomposition, this
  enum value's meaning shifted from "load from a separate substrate
  service" to "load from a signed YAML manifest via
  `oneiric remote-sync`". The enum value is still in
  `CandidateSource` but the meaning is not documented.

## Decision

Oneiric adapters are defined by **one canonical contract** that lives
in
[`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md).
The contract is satisfied by satisfying five sub-contracts:

| # | Sub-contract | Where enforced |
|---|---|---|
| 1 | Static declaration via class-level `AdapterMetadata` | `oneiric/adapters/metadata.py:21` |
| 2 | Three-method async lifecycle (`init` / `health` / `cleanup`) | `oneiric/adapters/bridge.py:44` |
| 3 | Factory reference (callable or `module: Class` string) | `oneiric/core/resolution.py:41` (Candidate.factory) |
| 4 | Pydantic `settings_model` | `oneiric/adapters/metadata.py:36` |
| 5 | Registered into the resolver's `"adapter"` domain | `oneiric/adapters/bootstrap.py:143` |

Additionally, the **cross-component discovery path** is canonical:

> Other Bodai components (Mahavishnu, Akosha, Crackerjack,
> Session-Buddy) discover adapters through Oneiric's MCP tools
> (`oneiric_list_adapters`, `oneiric_get_adapter`,
> `oneiric_get_adapter_health`, etc.). They do not import Oneiric
> directly. The Dhara MCP service that previously held the
> cross-ecosystem catalog has been decomposed and is no longer in the
> resolution path.

And the **`REMOTE_MANIFEST` `CandidateSource` value** is canonical:

> `REMOTE_MANIFEST` means "adapters declared in a remote YAML manifest,
> loaded into Oneiric's local JSON-backed registry via the
> `oneiric remote-sync` CLI." The manifest schema is at
> `docs/REMOTE_MANIFEST_SCHEMA.md`. There is no separate substrate
> HTTP service in the resolution path.

## Consequences

**What changes:**

- `README.md:79` and module docstrings in `mcp/adapter_registry.py`,
  `mcp/server.py`, and `adapters/bootstrap.py` cross-link to the
  canonical spec instead of restating the contract. (Docstring cleanup
  — see the 2026-10-11 Dhara cleanup decision note for parallel work.)
- The spec is the source of truth for new adapter authors. Adding a
  new adapter is now: read the spec → satisfy the five sub-contracts →
  register via `register_builtin_adapters` (or an entry point / remote
  manifest).

**What does NOT change:**

- `AdapterMetadata` field shape stays the same (already conforms to
  the spec).
- `AdapterBridge.use()` lifecycle stays the same.
- The resolver's scoring algorithm stays the same.
- The MCP tool surface (`oneiric_store_adapter`, etc.) stays the same.

**Trade-offs accepted:**

- One new file (`docs/specs/2026-10-11-adapter-contract-design.md`)
  adds to the docs surface, but the alternative — keeping the contract
  scattered across 5 docstrings — is what produced the rot that this
  ADR was created to fix.
- The spec is descriptive, not enforced by a runtime check. A
  future ADR may add a validator (analogous to
  `crackerjack`'s hook system) but that's out of scope here.

## Alternatives considered

- **Add an abstract `BaseAdapter` class with abstract methods.**
  Rejected: changes the inheritance pattern across ~50+ existing
  adapters and provides no runtime benefit. Registration-time
  validation in `bootstrap.py` is sufficient.
- **Keep the contract scattered across docstrings and add a
  validator.** Rejected: doesn't solve the new-author discovery
  problem. The spec + cross-links is the lower-friction option.
- **Embed the contract in code via type hints + a runtime validator
  invoked at adapter import time.** Deferred: see trade-offs. Could
  be a follow-up ADR if drift recurs.

## Validation

This ADR is correctly applied when:

- [ ] A new adapter author can read the spec and produce a working
      adapter without grepping the codebase.
- [ ] All existing built-in adapters in
      `oneiric/adapters/bootstrap.py::builtin_adapter_metadata()`
      conform to the spec (verified by reading 1-2 random samples).
- [ ] Cross-component consumers (Mahavishnu, Akosha, Crackerjack,
      Session-Buddy) call `mcp__oneiric__*` tools to discover
      adapters.

## References

- Full contract: [`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md)
- Parallel cleanup: [`.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`](../../.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md)
- Existing `AdapterMetadata` model: `oneiric/adapters/metadata.py:21`
- Existing `AdapterBridge`: `oneiric/adapters/bridge.py:25`
- Resolver scoring: `oneiric/core/resolution.py:217-279`
- Reference implementation: `oneiric/adapters/queue/redis_streams.py:74-86`