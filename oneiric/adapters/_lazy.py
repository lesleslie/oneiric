"""Lazy package re-exports for the adapter families (PEP 562).

Every adapter family re-exports its concrete adapters from its package
``__init__``. Doing that eagerly meant importing one adapter pulled in
every sibling adapter in the family *and* every client library those
adapters need: ``oneiric.adapters.queue`` cost ~4 s (Kafka, RabbitMQ,
NATS, Pub/Sub, Cloud Tasks, LavinMQ) and ``oneiric.adapters.storage``
pulled in the cloud SDKs.

The tax was not optional for consumers. Python executes every parent
package's ``__init__`` on the way down, so a caller that imported a
single concrete adapter --
``from oneiric.adapters.queue.redis_streams import RedisStreamsQueueSettings``
-- still paid for the whole family. Claude Code hooks that publish one
bus event per tool call paid it on the tool-call critical path, adding
~3.4 s to every MCP tool call before the model could see the result.

The families now resolve their re-exports on first attribute access,
matching the pattern already used by ``oneiric.adapters.observability``.
Import *order* changes; behaviour does not -- the re-exported names
still resolve to the same objects.
"""

from __future__ import annotations

import importlib
from typing import Any


def resolve_lazy_export(
    module_name: str,
    name: str,
    exports: dict[str, tuple[str, str]],
    submodules: tuple[str, ...] = (),
) -> Any:
    """Resolve *name* from the submodule that provides it.

    Args:
        module_name: The importing package's ``__name__``.
        name: The attribute being resolved.
        exports: Mapping of exported name -> (module path, attribute name).
        submodules: Submodule names that stay reachable as attributes of
            the importing package.

    Returns:
        The resolved attribute.

    Raises:
        AttributeError: If *name* is neither a known export nor a known
            submodule of the importing package.
    """
    if name in submodules:
        return importlib.import_module(f"{module_name}.{name}")

    target = exports.get(name)
    if target is None:
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")

    module_path, attr_name = target
    value = getattr(importlib.import_module(module_path), attr_name)
    return value
