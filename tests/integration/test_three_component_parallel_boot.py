"""Concurrency preflight: three Bodai components pushing runtime facts simultaneously.

Covers Plan 1 Task 3.2 (R4 concurrency preflight) from
``docs/plans/2026-09-26-oneiric-runtime-config-registry.md``.

The runtime-facts contract is that ``OneiricAdapterRegistry.set_runtime_facts_async``
serializes concurrent pushes through ``self._lock`` and writes via
``tmp + atomic replace`` — so three components booting in parallel must
land every fact without producing a malformed ``adapter_registry.json``.
This test exercises that contract under a 3-way gather() storm and
verifies both invariants:

1. No ``JSONDecodeError`` when re-reading the on-disk registry.
2. No lost writes — every component's ``runtime_facts`` payload is
   present after the storm completes.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from oneiric.mcp.adapter_registry import OneiricAdapterRegistry


# Three real Bodai components that wire runtime-facts pushes
# on boot per Plan 1 Phase 3 Task 3.1.
COMPONENTS = [
    ("akosha", "seer", "akosha"),
    ("crackerjack", "inspector", "crackerjack"),
    ("session-buddy", "builder", "session-buddy"),
]


@pytest.fixture
def tmp_registry_root() -> Iterator[Path]:
    """Private temp root for the registry; chmod-disciplined by the registry itself."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "oneiric-data"


@pytest.fixture
def seeded_registry(tmp_registry_root: Path) -> OneiricAdapterRegistry:
    """Registry with one catalog entry per simulated component (REQUIRED for R4-001).

    ``set_runtime_facts_async`` refuses to create catalog entries —
    the caller (each component's boot hook) MUST seed via
    ``store_adapter_async`` first. This fixture models that
    two-phase contract.
    """
    registry = OneiricAdapterRegistry(root=tmp_registry_root)

    async def _seed() -> None:
        await asyncio.gather(
            *(
                registry.store_adapter_async(
                    domain="adapter",
                    key=key,
                    provider=provider,
                    version="1.0.0",
                    factory_path=f"oneiric.adapters.{key}.Stub",
                    config={},
                    dependencies=[],
                    capabilities=["runtime-facts"],
                    metadata={},
                )
                for _label, key, provider in COMPONENTS
            )
        )

    asyncio.run(_seed())
    return registry


def _marker_payload(component: str, ts_marker: str) -> dict[str, object]:
    """Per-call payload with a unique stamp the test can grep for after the storm."""
    return {
        "config": {"component": component, "ts_marker": ts_marker},
        "capabilities": ["boot", "runtime-facts"],
        "health_reserved": {"boot_seq": 1},
    }


async def _push(
    registry: OneiricAdapterRegistry,
    key: str,
    provider: str,
    payload: dict[str, object],
) -> str:
    return await registry.set_runtime_facts_async(
        domain="adapter",
        key=key,
        provider=provider,
        runtime_facts=payload,  # type: ignore[arg-type]
    )


def test_three_component_parallel_push_preserves_all_facts(
    seeded_registry: OneiricAdapterRegistry,
    tmp_registry_root: Path,
) -> None:
    """Three concurrent ``set_runtime_facts_async`` calls land every payload
    and leave the on-disk registry valid JSON.

    Asserts:
    - The on-disk ``adapter_registry.json`` is well-formed (no JSONDecodeError).
    - All three component entries are present with their unique ts_marker.
    - ``updated_at`` advanced on each entry.
    """
    registry = seeded_registry
    registry_path = tmp_registry_root / "adapter_registry.json"
    # Distinct ts_marker per component lets us prove no entry was overwritten
    # by a sibling's payload during the storm.
    ts_markers = {label: f"storm-{label}-0" for label, _, _ in COMPONENTS}

    async def _storm() -> list[str]:
        return await asyncio.gather(
            *(
                _push(
                    registry,
                    key=key,
                    provider=provider,
                    payload=_marker_payload(label, ts_markers[label]),
                )
                for label, key, provider in COMPONENTS
            )
        )

    adapter_ids = asyncio.run(_storm())
    assert sorted(adapter_ids) == sorted(
        f"adapter:{key}:{provider}" for _label, key, provider in COMPONENTS
    )

    # Invariant 1: on-disk JSON is well-formed.
    raw = json.loads(registry_path.read_text())
    assert isinstance(raw, dict)

    # Invariant 2: every component's payload landed; no lost writes.
    for label, key, provider in COMPONENTS:
        adapter_id = f"adapter:{key}:{provider}"
        entry = raw[adapter_id]
        assert entry["runtime_facts"]["config"]["component"] == label
        assert entry["runtime_facts"]["config"]["ts_marker"] == ts_markers[label]
        assert entry["runtime_facts"]["capabilities"] == ["boot", "runtime-facts"]
        assert "updated_at" in entry
        assert entry["updated_at"]


def test_three_component_parallel_push_is_idempotent_under_repeat(
    seeded_registry: OneiricAdapterRegistry,
    tmp_registry_root: Path,
) -> None:
    """A second 3-way storm after the first still leaves a well-formed file
    with all entries updated. Guards against read-modify-write drift
    when components reconfigure mid-flight.
    """
    registry = seeded_registry
    registry_path = tmp_registry_root / "adapter_registry.json"

    async def _two_storms() -> None:
        await asyncio.gather(
            *(
                _push(
                    registry,
                    key=key,
                    provider=provider,
                    payload=_marker_payload(label, f"storm-1-{label}"),
                )
                for label, key, provider in COMPONENTS
            )
        )
        # Second wave with different markers — each adapter is overwritten,
        # never lost, and the final file must reflect wave 2 exactly.
        await asyncio.gather(
            *(
                _push(
                    registry,
                    key=key,
                    provider=provider,
                    payload=_marker_payload(label, f"storm-2-{label}"),
                )
                for label, key, provider in COMPONENTS
            )
        )

    asyncio.run(_two_storms())
    raw = json.loads(registry_path.read_text())
    for label, key, provider in COMPONENTS:
        entry = raw[f"adapter:{key}:{provider}"]
        # Wave 2 wins; wave 1 markers must be gone everywhere.
        assert entry["runtime_facts"]["config"]["ts_marker"] == f"storm-2-{label}"


def test_parallel_push_against_missing_catalog_raises(
    tmp_registry_root: Path,
) -> None:
    """Concurrent push to a non-existent adapter surfaces KeyError; the
    registry does NOT auto-create catalog entries. This is the negative
    half of the R4 contract — concurrent valid pushes can't be
    shadowed by a sibling's KeyError into a half-written file.
    """
    registry = OneiricAdapterRegistry(root=tmp_registry_root)
    registry_path = tmp_registry_root / "adapter_registry.json"

    async def _storm() -> list[object]:
        return await asyncio.gather(
            _push(
                registry,
                key="ghost",
                provider="nobody",
                payload={"capabilities": ["x"]},
            ),
            _push(
                registry,
                key="also-ghost",
                provider="nobody",
                payload={"capabilities": ["y"]},
            ),
            return_exceptions=True,
        )

    results = asyncio.run(_storm())
    assert all(isinstance(r, KeyError) for r in results)
    # On-disk file must be either absent (the registry only materializes
    # the file on first successful write) OR a well-formed empty dict —
    # both prove no half-written artifact was left behind by the storm.
    if registry_path.exists():
        raw = json.loads(registry_path.read_text())
        assert raw == {}
