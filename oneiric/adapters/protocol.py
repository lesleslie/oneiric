"""Structural contract for an Oneiric adapter.

This module defines the :class:`OneiricAdapter` Protocol — the
substrate's structural type for adapters. Conformance is by duck
typing; an adapter is *an* Oneiric adapter if it satisfies this
Protocol. No inheritance required.

Location
--------
This Protocol lives in the Oneiric package because:

* The :class:`~oneiric.adapters.metadata.AdapterMetadata` Pydantic
  model it references is defined here. Locality of reference.
* Oneiric is a substrate library usable by non-Bodai projects (e.g.
  standalone Python apps). Putting the Protocol here means those
  projects get the contract for free without taking a Bodai-ecosystem
  dependency.

Scope
-----
The Protocol captures the *structural shape* every Oneiric adapter must
satisfy:

1. A class-level ``metadata`` attribute holding an
   :class:`AdapterMetadata` instance.
2. Three async lifecycle methods: ``init``, ``health``, ``cleanup``.

The full contract — settings_model, factory resolution, registry
participation, capability filtering, cross-component discovery — is
enforced at registration time by
:class:`~oneiric.core.resolution.Resolver` and
:class:`~oneiric.mcp.adapter_registry.OneiricAdapterRegistry`. This
Protocol is the static surface those systems rely on.

See ``docs/specs/2026-10-11-adapter-contract-design.md`` for the full
contract, including anti-patterns and reference implementations.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from .metadata import AdapterMetadata


@runtime_checkable
class OneiricAdapter(Protocol):
    """Structural contract every Oneiric adapter satisfies.

    An adapter is a Python class that:

    * declares a class-level ``AdapterMetadata`` instance as ``metadata``
    * implements ``async init(self) -> None`` to warm up clients/pools
    * implements ``async health(self) -> bool`` for liveness checks
    * implements ``async cleanup(self) -> None`` to release resources

    Conformance is structural. No inheritance from this Protocol is
    required; a class qualifies by having the right shape.

    Type-checkers verify conformance at static-analysis time (mypy /
    pyright / ty). At runtime, ``isinstance(obj, OneiricAdapter)``
    works because the Protocol is ``@runtime_checkable`` — but the
    check is *shallow by design*: ``runtime_checkable`` only verifies
    attribute presence (does the class have a ``metadata`` attribute?
    does the instance have ``init``/``health``/``cleanup``?), not
    method signatures, return types, or that ``metadata`` is an
    ``AdapterMetadata`` instance. The full contract is enforced when
    the adapter is registered with the resolver (``Resolver.register``
    / ``register_builtin_adapters`` / remote manifests) and at
    :meth:`AdapterBridge.use` time.
    """

    metadata: ClassVar[AdapterMetadata]
    """Class-level :class:`AdapterMetadata` instance.

    Declares the slot the adapter fills (``category``), its identity
    within the slot (``provider``), its capabilities, its factory
    reference, its settings model, and its priority/stack_level for
    resolution scoring.
    """

    async def init(self) -> None:
        """Warm up clients and open connection pools.

        Called once per resolution (when the adapter is selected by
        :meth:`oneiric.adapters.bridge.AdapterBridge.use`). Must
        tolerate being called multiple times across hot-swap cycles.

        Raise :class:`oneiric.core.lifecycle.LifecycleError` on
        unrecoverable setup failure. Do NOT raise for transient
        issues; the resolver retries.
        """
        ...

    async def health(self) -> bool:
        """Return ``True`` if healthy, ``False`` if degraded.

        **Never raise from this method.** The monitoring layer relies
        on ``bool``; raising would surface as a 5xx instead of a
        degraded state. Catch transport errors inside, log a warning,
        return ``False``.

        The method is invoked by ``OneiricAdapterRegistry.check_adapter_health_async``
        and (transitively) by every cross-component consumer that asks
        Oneiric for the adapter's health.
        """
        ...

    async def cleanup(self) -> None:
        """Release clients, close pools, drop locks.

        Called on bridge shutdown and before hot-swap. Idempotent — the
        resolver may call this after a partial ``init`` failure during
        recovery. After cleanup, ``init`` may be called again on the
        same instance.
        """
        ...


__all__ = ["OneiricAdapter"]
