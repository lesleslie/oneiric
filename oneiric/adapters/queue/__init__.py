"""Lazy-loaded queue adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need -- Kafka, RabbitMQ, NATS, Pub/Sub, Cloud
Tasks and LavinMQ -- which cost ~4 s. A consumer importing a single
concrete adapter paid that tax too, because Python executes every parent
package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.queue import RedisStreamsQueueAdapter`` still
works and ``import oneiric.adapters.queue`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "CloudTasksQueueAdapter",
    "CloudTasksQueueSettings",
    "KafkaQueueAdapter",
    "KafkaQueueSettings",
    "LavinMQQueueAdapter",
    "LavinMQQueueSettings",
    "LavinMQSettings",
    "NATSQueueAdapter",
    "NATSQueueSettings",
    "Protocol",
    "PubSubQueueAdapter",
    "PubSubQueueSettings",
    "RabbitMQQueueAdapter",
    "RabbitMQQueueSettings",
    "RedisStreamsQueueAdapter",
    "RedisStreamsQueueSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.queue.cloudtasks import (
        CloudTasksQueueAdapter,
        CloudTasksQueueSettings,
    )
    from oneiric.adapters.queue.kafka import KafkaQueueAdapter, KafkaQueueSettings
    from oneiric.adapters.queue.lavinmq import (
        LavinMQQueueAdapter,
        LavinMQSettings,
        Protocol,
    )
    from oneiric.adapters.queue.nats import NATSQueueAdapter, NATSQueueSettings
    from oneiric.adapters.queue.pubsub import (
        PubSubQueueAdapter,
        PubSubQueueSettings,
    )
    from oneiric.adapters.queue.rabbitmq import (
        RabbitMQQueueAdapter,
        RabbitMQQueueSettings,
    )
    from oneiric.adapters.queue.redis_streams import (
        RedisStreamsQueueAdapter,
        RedisStreamsQueueSettings,
    )

    # ``__all__`` has advertised "LavinMQQueueSettings" since the family
    # was added, but the class is named ``LavinMQSettings`` -- so
    # ``from oneiric.adapters.queue import LavinMQQueueSettings`` raised
    # ImportError. The alias is spelled out here so the advertised name
    # resolves; ``LavinMQSettings`` stays available under its own name.
    LavinMQQueueSettings = LavinMQSettings


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "CloudTasksQueueAdapter": (
        "oneiric.adapters.queue.cloudtasks",
        "CloudTasksQueueAdapter",
    ),
    "CloudTasksQueueSettings": (
        "oneiric.adapters.queue.cloudtasks",
        "CloudTasksQueueSettings",
    ),
    "KafkaQueueAdapter": ("oneiric.adapters.queue.kafka", "KafkaQueueAdapter"),
    "KafkaQueueSettings": ("oneiric.adapters.queue.kafka", "KafkaQueueSettings"),
    "LavinMQQueueAdapter": ("oneiric.adapters.queue.lavinmq", "LavinMQQueueAdapter"),
    # See the TYPE_CHECKING note: the advertised name is an alias.
    "LavinMQQueueSettings": ("oneiric.adapters.queue.lavinmq", "LavinMQSettings"),
    "LavinMQSettings": ("oneiric.adapters.queue.lavinmq", "LavinMQSettings"),
    "NATSQueueAdapter": ("oneiric.adapters.queue.nats", "NATSQueueAdapter"),
    "NATSQueueSettings": ("oneiric.adapters.queue.nats", "NATSQueueSettings"),
    "Protocol": ("oneiric.adapters.queue.lavinmq", "Protocol"),
    "PubSubQueueAdapter": ("oneiric.adapters.queue.pubsub", "PubSubQueueAdapter"),
    "PubSubQueueSettings": ("oneiric.adapters.queue.pubsub", "PubSubQueueSettings"),
    "RabbitMQQueueAdapter": (
        "oneiric.adapters.queue.rabbitmq",
        "RabbitMQQueueAdapter",
    ),
    "RabbitMQQueueSettings": (
        "oneiric.adapters.queue.rabbitmq",
        "RabbitMQQueueSettings",
    ),
    "RedisStreamsQueueAdapter": (
        "oneiric.adapters.queue.redis_streams",
        "RedisStreamsQueueAdapter",
    ),
    "RedisStreamsQueueSettings": (
        "oneiric.adapters.queue.redis_streams",
        "RedisStreamsQueueSettings",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported adapter on first attribute access (PEP 562)."""
    from oneiric.adapters._lazy import resolve_lazy_export

    value = resolve_lazy_export(__name__, name, _LAZY_EXPORTS)
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
