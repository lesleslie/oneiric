---
status: active
role: canonical
kind: decision
date: 2026-11-16
last_reviewed: 2026-11-16
superseded_by:
blocks_on: []
decision_date: 2026-11-16
topic: oneiric-import-cost
---

# ADR 0004: Adapter packages resolve their re-exports lazily

## Status

**Active** as of 2026-11-16. Implemented in
`oneiric/adapters/__init__.py`, the fifteen adapter-family packages, and
`oneiric/adapters/bootstrap.py`; covered by
`tests/adapters/test_lazy_imports.py`.

## Context

Importing `oneiric.adapters` cost **~3 s**:

```
oneiric.adapters                              3.94 s
oneiric.adapters.queue                        4.26 s
oneiric.adapters.bootstrap                    2.33 s
oneiric.adapters.queue.redis_streams          2.85 s
```

Two mechanisms produced that, and both were invisible from the call site.

**The parent package imported the resolution stack.**
`oneiric/adapters/__init__.py` eagerly imported `bootstrap`, which
imported `core.config`, which imported `mcp.config`, which imported
`oneiric.mcp` — the whole stack, to re-export seven names.

**Every family imported all of its adapters.** `oneiric/adapters/queue/`
imported the Kafka, RabbitMQ, NATS, Pub/Sub, Cloud Tasks and LavinMQ
adapters alongside the Redis Streams one, so each one's client library
came with it. `oneiric/adapters/bootstrap.py` then imported *every*
family at module scope — sixty adapter classes — because
`builtin_adapter_metadata()` needs their `.metadata`.

The tax was not optional for consumers. Python executes every parent
package's `__init__` on the way down, so a caller that imported one
concrete adapter still paid for its whole family:

```python
from oneiric.adapters.queue.redis_streams import RedisStreamsQueueSettings
```

ran the `oneiric.adapters` and `oneiric.adapters.queue` package
inits first.

**Who was paying.** Mahavishnu's Claude Code hooks publish one event to
the Oneiric bus per tool call, and the publish path goes through
`oneiric.adapters.bootstrap.queued_publisher`. The two `PostToolUse`
hooks therefore cost **3.05 s** and **3.49 s** each, on the tool-call
critical path, before the model could see a tool result. Per MCP tool
call that was **6.5 s** of import time.

## Decision rule

Adapter packages resolve their re-exports on first attribute access
(PEP 562), and modules that exist only to re-export import nothing at
module scope.

- `oneiric/adapters/__init__.py` re-exports its seven names lazily.
- Each family package re-exports its adapters lazily, via the shared
  `oneiric/adapters/_lazy.py` resolver. The names are still listed in
  `__all__` and still resolve to the same objects.
- `oneiric/adapters/bootstrap.py` imports the adapter families inside
  `builtin_adapter_metadata()`, the one function that needs them, and
  imports the Redis Streams adapter inside `queued_publisher()`. Its
  type-only imports live under `TYPE_CHECKING`.
- Re-exports that a family package's `__all__` advertises must resolve.
  `oneiric.adapters.queue` advertised `LavinMQQueueSettings`, which never
  existed — the class is `LavinMQSettings` — so
  `from oneiric.adapters.queue import LavinMQQueueSettings` raised
  ImportError. The advertised name now resolves to the class.

**The rule for new code:** a package `__init__` that re-exports a
submodule's names imports that submodule lazily. A module that exists
only to aggregate other modules' exports imports nothing eagerly.

**What did not change.** Import *order* changed; behaviour did not. The
re-exported names resolve to the same objects, and no module in the
adapter tree has an import-time side effect — `register_builtin_adapters`
is an explicit call, not a side effect of importing the package.

## Consequences

```
oneiric.adapters                              3.94 s -> 0.22 s
oneiric.adapters.queue                        4.26 s -> 0.17 s
oneiric.adapters.bootstrap                    2.33 s -> 0.17 s
oneiric.adapters.storage                      1.73 s -> 0.23 s
oneiric.adapters.llm                          1.14 s -> 0.20 s
```

Mahavishnu's hooks, against this tree: `jot-post-tool-use` 3.05 s →
**1.07 s**, `bodai-activity-post-tool-use` 3.49 s → **1.28 s** — 6.5 s
→ **2.35 s** per MCP tool call.

The remaining ~1.5 s in `oneiric.adapters.queue.redis_streams` is the
adapter's own dependencies (`coredis` ~0.57 s, `structlog` ~0.5 s via
`oneiric.core.logging`, `opentelemetry`, `pydantic`). Those are real
requirements of the Redis Streams adapter, not import-graph waste, so
they are the floor for a caller that actually uses that adapter.

**Release.** The fix lands in oneiric; consumers pick it up on the next
oneiric release. Mahavishnu pins oneiric, so its hooks keep the old
cost until the pin moves.

## Alternatives rejected

- **Publish directly to Redis from the hook.** Would skip the adapter,
  but it duplicates the envelope shape and the stream contract in a
  second place, and the adapter is the documented entry point
  (`queued_publisher`). The cost is in the import graph, not in the
  adapter.
- **Narrow the hook's `mcp__*` matcher.** Reduces how often the cost is
  paid, but not how much, and it silently changes which events reach the
  bus.
- **Make the publish asynchronous in the hook.** Plausible follow-up: the
  publish is already fire-and-forget, so moving it off the critical path
  entirely is legitimate. Deferred here because the import graph is the
  root cause and it is worth fixing at the root.
