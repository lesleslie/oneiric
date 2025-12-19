## Protocol Implementation Plan (Oneiric)

### Scope

Introduce Protocols for the following areas where duck-typing or `Any` is used:
- Secrets provider contract (used by `SecretsHook`).
- Activity store abstraction (used by `ServiceSupervisor` and bridges).
- Workflow checkpoint + execution persistence stores.
- Task handler contract (`run(...)`).
- Event handler contract (`handle(...)`).
- Queue adapter surface used by workflows (`enqueue(...)`).
- Bridge handles (`AdapterHandle.instance`, `DomainHandle.instance`) via domain-specific Protocols.

### Goals

- Make runtime expectations explicit without changing behavior.
- Enable alternate implementations (pluggable stores, adapters).
- Improve static typing and testability (fakes/mocks without inheritance).

### Concrete Protocol Set (Examples)

The following are intended as minimal, stable contracts that match current usage.
Default to domain-local modules (for example, `oneiric/runtime/protocols.py` or
`oneiric/domains/protocols.py`). Place protocols in `oneiric/core/` only when
they apply across multiple domains.

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from oneiric.runtime.activity import DomainActivity
from oneiric.runtime.events import EventEnvelope


class SecretsProviderProtocol(Protocol):
    async def get_secret(self, secret_id: str) -> str | None: ...


class SecretsCacheProtocol(Protocol):
    async def invalidate_cache(self) -> None: ...
    async def clear_cache(self) -> None: ...
    async def refresh(self) -> None: ...


class ActivityStoreProtocol(Protocol):
    def get(self, domain: str, key: str) -> DomainActivity: ...
    def all_for_domain(self, domain: str) -> dict[str, DomainActivity]: ...
    def set(self, domain: str, key: str, state: DomainActivity) -> None: ...
    def snapshot(self) -> dict[str, dict[str, DomainActivity]]: ...


class WorkflowCheckpointStoreProtocol(Protocol):
    def load(self, workflow_key: str) -> dict[str, Any]: ...
    def save(self, workflow_key: str, checkpoint: Mapping[str, Any]) -> None: ...
    def clear(self, workflow_key: str) -> None: ...


class WorkflowExecutionStoreProtocol(Protocol):
    def start_run(self, workflow_key: str, run_id: str, started_at: str) -> None: ...
    def finish_run(
        self, run_id: str, status: str, ended_at: str, error: str | None = None
    ) -> None: ...
    def start_node(self, run_id: str, node_key: str, started_at: str) -> None: ...
    def finish_node(
        self,
        run_id: str,
        node_key: str,
        status: str,
        ended_at: str,
        attempts: int | None = None,
        error: str | None = None,
    ) -> None: ...
    def load_run(self, run_id: str) -> dict[str, Any] | None: ...
    def load_nodes(self, run_id: str) -> list[dict[str, Any]]: ...


class TaskHandlerProtocol(Protocol):
    async def run(self, payload: dict[str, Any] | None = None) -> Any: ...


class EventHandlerProtocol(Protocol):
    async def handle(self, envelope: EventEnvelope) -> Any: ...


class QueueAdapterProtocol(Protocol):
    async def enqueue(self, payload: dict[str, Any]) -> str: ...
```

Notes:
- Keep optional lifecycle methods (init/health/cleanup) in existing ABCs for now.
- Secrets cache invalidation uses a separate `SecretsCacheProtocol` so providers
  can opt in without affecting the base secrets contract.
- Protocols are async-only; sync implementations should be updated or wrapped.
- Protocols are for static typing by default; avoid runtime `isinstance` checks
  unless a specific error-reporting benefit is identified.

### Integration Points (How Protocols Slot In)

1. Secrets hook
   - File: `oneiric/core/config.py`
   - Replace `Any` provider usage with `SecretsProviderProtocol`.
   - `SecretsCacheProtocol` is only used for optional cache hooks.
   - Keep existing runtime `getattr` checks; the Protocol is for typing.

2. Activity store
   - Files: `oneiric/runtime/activity.py`, `oneiric/runtime/supervisor.py`,
     `oneiric/adapters/bridge.py`, `oneiric/domains/base.py`
   - Annotate `activity_store` parameters with `ActivityStoreProtocol`.
   - `DomainActivityStore` already matches the protocol.

3. Workflow persistence stores
   - Files: `oneiric/runtime/checkpoints.py`, `oneiric/runtime/durable.py`,
     `oneiric/domains/workflows.py`, `oneiric/runtime/orchestrator.py`
   - Accept `WorkflowCheckpointStoreProtocol` and
     `WorkflowExecutionStoreProtocol` where used.
   - Existing SQLite implementations remain unchanged.

4. Task handler contract
   - File: `oneiric/domains/workflows.py`
   - Type the `handle.instance` for task handlers as `TaskHandlerProtocol`.

5. Event handler contract
   - Files: `oneiric/domains/events.py`, `oneiric/runtime/events.py`
   - Type handler instances to `EventHandlerProtocol` in `_build_handler`.

6. Queue adapter surface
   - File: `oneiric/domains/workflows.py`
   - Type `handle.instance` as `QueueAdapterProtocol` when invoking `enqueue`.

7. Bridge handles
   - Files: `oneiric/adapters/bridge.py`, `oneiric/domains/base.py`
   - Option A: Keep `instance: Any` and add generic type parameters so
     bridge usage can be typed at call sites.
   - Option B: Introduce specific protocol-typed handles per domain
     (e.g., `QueueHandle`, `TaskHandle`) if the API surface is small.

### Implementation Steps

1. Add new protocol modules in the relevant domain packages (runtime/domains/
   adapters). Only place shared protocols in `oneiric/core/`.
2. Define the minimal Protocols listed above, with comments on intent.
3. Update typing annotations in:
   - `oneiric/core/config.py`
   - `oneiric/runtime/supervisor.py`
   - `oneiric/adapters/bridge.py`
   - `oneiric/domains/base.py`
   - `oneiric/domains/events.py`
   - `oneiric/domains/workflows.py`
   - `oneiric/runtime/checkpoints.py`
   - `oneiric/runtime/durable.py`
4. Optionally add Protocol-specific type aliases for domain handles or `AdapterHandle`.
5. Run type checks locally (zuban; pyright is legacy) and fix drift.

### Testing + Validation

- Unit tests can introduce lightweight fakes that match Protocols without subclassing.
- Run:
  - `uv run pytest`
  - `uv run python -m oneiric.cli --demo list --domain adapter`
  - `uv run python -m oneiric.cli orchestrate --manifest docs/sample_remote_manifest.yaml --refresh-interval 120`

### Open Questions

- Should any cross-domain protocols be centralized in `oneiric/core/`, or can
  we keep all protocols scoped to their owning domain packages?
- Where do runtime `isinstance(..., Protocol)` checks provide clear value
  (for example, adapter registration debug mode), and where should we stay
  purely static?

### Appendix: Proposed Protocol Locations

- `SecretsProviderProtocol`, `SecretsCacheProtocol`: `oneiric/core/protocols.py`
- `ActivityStoreProtocol`: `oneiric/runtime/protocols.py`
- `WorkflowCheckpointStoreProtocol`: `oneiric/runtime/protocols.py`
- `WorkflowExecutionStoreProtocol`: `oneiric/runtime/protocols.py`
- `TaskHandlerProtocol`: `oneiric/domains/protocols.py`
- `EventHandlerProtocol`: `oneiric/domains/protocols.py`
- `QueueAdapterProtocol`: `oneiric/adapters/queue/protocols.py`
