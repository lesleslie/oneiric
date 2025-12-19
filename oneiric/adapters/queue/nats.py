"""NATS queue adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - optional dependency typing
    from nats.aio.msg import Msg
else:  # pragma: no cover - runtime guard
    Msg = Any
from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

MessageHandler = Callable[[Msg], Awaitable[None]]


def _load_nats() -> Any:
    try:
        import nats as nats_lib
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise LifecycleError(
            "nats-not-installed: install optional extra 'oneiric[queue-nats]' to use "
            "NATSQueueAdapter"
        ) from exc
    return nats_lib


class NATSQueueSettings(BaseModel):
    servers: list[str] = Field(
        default_factory=lambda: ["nats://127.0.0.1:4222"],
        description="List of NATS servers to connect to.",
    )
    name: str = Field(
        default="oneiric-nats", description="Client name reported to servers."
    )
    queue: str = Field(
        default="oneiric", description="Default queue group for subscriptions."
    )
    connect_timeout: float = Field(
        default=2.0, gt=0.0, description="Connection timeout in seconds."
    )
    ping_interval: float = Field(
        default=2.0, gt=0.0, description="Ping interval in seconds."
    )
    max_reconnect_attempts: int = Field(
        default=60, ge=-1, description="Maximum reconnect attempts (-1 for infinite)."
    )
    reconnect_time_wait: float = Field(
        default=1.0, gt=0.0, description="Delay between reconnect attempts in seconds."
    )
    tls: bool = Field(
        default=False, description="Enable TLS for connections when true."
    )


class NATSQueueAdapter(EnsureClientMixin):
    metadata = AdapterMetadata(
        category="queue",
        provider="nats",
        factory="oneiric.adapters.queue.nats:NATSQueueAdapter",
        capabilities=["queue", "pubsub"],
        stack_level=25,
        priority=320,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=False,
        settings_model=NATSQueueSettings,
    )

    def __init__(
        self,
        settings: NATSQueueSettings | None = None,
        *,
        client: nats.NATS | None = None,
    ) -> None:
        self._settings = settings or NATSQueueSettings()
        self._client: nats.NATS | None = client
        self._owns_client = client is None
        self._logger = get_logger("adapter.queue.nats").bind(
            domain="adapter",
            key="queue",
            provider="nats",
        )

    async def init(self) -> None:
        if not self._client:
            nats_lib = _load_nats()
            self._client = await nats_lib.connect(
                servers=self._settings.servers,
                name=self._settings.name,
                connect_timeout=self._settings.connect_timeout,
                ping_interval=self._settings.ping_interval,
                max_reconnect_attempts=self._settings.max_reconnect_attempts,
                reconnect_time_wait=self._settings.reconnect_time_wait,
                tls=self._settings.tls,
            )
        self._logger.info(
            "adapter-init", adapter="nats", servers=self._settings.servers
        )

    async def health(self) -> bool:
        client = self._client
        return bool(client and client.is_connected)

    async def cleanup(self) -> None:
        if self._client and self._owns_client:
            try:
                await self._client.drain()
                await self._client.close()
            finally:
                self._client = None
        self._logger.info("adapter-cleanup-complete", adapter="nats")

    async def publish(
        self, subject: str, payload: bytes, *, headers: dict[str, str] | None = None
    ) -> None:
        client = self._ensure_client("nats-client-not-initialized")
        await client.publish(subject, payload, headers=headers)
        self._logger.debug("queue-publish", subject=subject, size=len(payload))

    async def subscribe(
        self,
        subject: str,
        *,
        queue: str | None = None,
        cb: MessageHandler | None = None,
    ) -> Any:
        if not cb:
            raise LifecycleError("nats-subscription-callback-required")
        client = self._ensure_client("nats-client-not-initialized")
        queue_name = queue or self._settings.queue
        sub = await client.subscribe(subject, queue=queue_name, cb=cb)
        self._logger.debug("queue-subscribe", subject=subject, queue=queue_name)
        return sub

    async def request(
        self, subject: str, payload: bytes, *, timeout: float | None = None
    ) -> Msg:
        client = self._ensure_client("nats-client-not-initialized")
        response = await client.request(
            subject, payload, timeout=timeout or self._settings.connect_timeout
        )
        return response
