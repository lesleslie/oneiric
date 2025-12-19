"""Redis Streams queue adapter."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - optional dependency typing
    from coredis import Redis
    from coredis.exceptions import RedisError, ResponseError
else:  # pragma: no cover - runtime guard
    Redis = None
    RedisError = Exception
    ResponseError = Exception
from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class RedisStreamsQueueSettings(BaseModel):
    """Settings for the Redis Streams adapter."""

    stream: str = Field(
        default="oneiric-queue", description="Stream key backing the queue."
    )
    group: str = Field(default="oneiric", description="Consumer group name.")
    consumer: str = Field(
        default="oneiric-consumer", description="Consumer name for read operations."
    )
    url: str = Field(
        default="redis://localhost:6379/0", description="Redis connection URL."
    )
    block_ms: int = Field(
        default=1000,
        ge=0,
        description="Default block duration for reads (milliseconds).",
    )
    maxlen: int | None = Field(
        default=None,
        ge=1,
        description="Approximate stream max length enforced on enqueue.",
    )
    auto_create_group: bool = Field(
        default=True, description="Whether to create the consumer group if missing."
    )
    consumer_buffer_size: int = Field(
        default=1, ge=1, description="Default XREADGROUP count value."
    )
    healthcheck_timeout: float = Field(
        default=2.0, gt=0.0, description="Timeout for health PING probes (seconds)."
    )


class RedisStreamsQueueAdapter(EnsureClientMixin):
    """Queue adapter backed by Redis Streams consumer groups."""

    metadata = AdapterMetadata(
        category="queue",
        provider="redis-streams",
        factory="oneiric.adapters.queue.redis_streams:RedisStreamsQueueAdapter",
        capabilities=["queue", "pubsub", "fanout"],
        stack_level=20,
        priority=300,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=RedisStreamsQueueSettings,
    )

    def __init__(
        self,
        settings: RedisStreamsQueueSettings | None = None,
        *,
        redis_client: Redis | None = None,
    ) -> None:
        self._settings = settings or RedisStreamsQueueSettings()
        self._client: Redis | None = redis_client
        self._owns_client = redis_client is None
        self._logger = get_logger("adapter.queue.redis_streams").bind(
            domain="adapter",
            key="queue",
            provider="redis-streams",
            stream=self._settings.stream,
            group=self._settings.group,
        )

    async def init(self) -> None:
        if not self._client:
            if Redis is None:  # pragma: no cover - optional dependency
                raise LifecycleError(
                    "coredis-not-installed: install optional extra 'oneiric[cache]' "
                    "to use RedisStreamsQueueAdapter"
                )
            self._client = Redis.from_url(self._settings.url)
        if self._settings.auto_create_group:
            try:
                await self._client.xgroup_create(
                    self._settings.stream,
                    self._settings.group,
                    id="0",
                    mkstream=True,
                )
                self._logger.info(
                    "queue-group-created",
                    stream=self._settings.stream,
                    group=self._settings.group,
                )
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise
        await self._ensure_ping()
        self._logger.info("adapter-init", adapter="redis-streams-queue")

    async def health(self) -> bool:
        try:
            await self._ensure_ping()
            return True
        except RedisError as exc:
            self._logger.warning("adapter-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._client and self._owns_client:
            try:
                await self._close_client_connection()
                await self._disconnect_connection_pool()
            finally:
                self._client = None
        self._logger.info("adapter-cleanup-complete", adapter="redis-streams-queue")

    async def _close_client_connection(self) -> None:
        """Close the Redis client connection if available."""
        if close := getattr(self._client, "close", None):
            if inspect.isawaitable(maybe := close()):
                await maybe

    async def _disconnect_connection_pool(self) -> None:
        """Disconnect the connection pool if available."""
        if pool := getattr(self._client, "connection_pool", None):
            if disconnect := getattr(pool, "disconnect", None):
                if inspect.isawaitable(maybe := disconnect()):
                    await maybe

    async def enqueue(self, data: Mapping[str, Any]) -> str:
        client = self._ensure_client("redis-streams-client-not-initialized")
        kwargs: dict[str, Any] = {}
        if self._settings.maxlen is not None:
            kwargs["maxlen"] = self._settings.maxlen
            kwargs["approximate"] = True
        message_id = await client.xadd(self._settings.stream, data, **kwargs)
        self._logger.debug(
            "queue-enqueue", stream=self._settings.stream, message_id=message_id
        )
        return message_id

    async def read(
        self, *, count: int | None = None, block_ms: int | None = None
    ) -> list[dict[str, Any]]:
        client = self._ensure_client("redis-streams-client-not-initialized")
        block = block_ms if block_ms is not None else self._settings.block_ms
        entries = await client.xreadgroup(
            self._settings.group,
            self._settings.consumer,
            streams={self._settings.stream: ">"},
            count=count or self._settings.consumer_buffer_size,
            block=block,
        )
        return self._format_entries(entries)

    async def ack(self, message_ids: Sequence[str]) -> int:
        client = self._ensure_client("redis-streams-client-not-initialized")
        if not message_ids:
            return 0
        acked = await client.xack(
            self._settings.stream, self._settings.group, *message_ids
        )
        self._logger.debug("queue-ack", stream=self._settings.stream, count=acked)
        return acked

    async def pending(self, *, count: int = 10) -> list[dict[str, Any]]:
        client = self._ensure_client("redis-streams-client-not-initialized")
        response = await client.xpending_range(
            self._settings.stream,
            self._settings.group,
            min="-",
            max="+",
            count=count,
        )
        return [
            {
                "message_id": entry[0],
                "consumer": entry[1],
                "delivery_count": entry[2],
                "idle": entry[3],
            }
            for entry in response
        ]

    async def _ensure_ping(self) -> None:
        client = self._ensure_client("redis-streams-client-not-initialized")
        await asyncio.wait_for(
            client.ping(), timeout=self._settings.healthcheck_timeout
        )

    def _format_entries(self, entries: Iterable[Any]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for stream_key, messages in entries or []:
            if stream_key != self._settings.stream:
                continue
            for message_id, payload in messages:
                formatted.append(
                    {
                        "message_id": message_id,
                        "payload": payload,
                    }
                )
        return formatted
