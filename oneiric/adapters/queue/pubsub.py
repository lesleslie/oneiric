"""Google Cloud Pub/Sub adapter used for DAG triggers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class PubSubQueueSettings(BaseModel):
    """Settings for Pub/Sub topic + optional subscription."""

    project_id: str
    topic: str
    subscription: str | None = Field(
        default=None,
        description="Optional subscription name for pull/ack operations.",
    )
    default_attributes: dict[str, str] = Field(default_factory=dict)
    ordering_key: str | None = None
    max_messages: int = Field(default=10, ge=1)


class PubSubQueueAdapter:
    """Adapter that publishes workflow triggers to Pub/Sub topics."""

    metadata = AdapterMetadata(
        category="queue",
        provider="pubsub",
        factory="oneiric.adapters.queue.pubsub:PubSubQueueAdapter",
        capabilities=["queue", "fanout", "events"],
        stack_level=40,
        priority=410,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=PubSubQueueSettings,
    )

    def __init__(
        self,
        settings: PubSubQueueSettings,
        *,
        publisher_client: Any | None = None,
        subscriber_client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._publisher_client = publisher_client
        self._subscriber_client = subscriber_client
        self._owns_publisher = publisher_client is None
        self._owns_subscriber = (
            subscriber_client is None and settings.subscription is not None
        )
        self._topic_path: str | None = None
        self._subscription_path: str | None = None
        self._logger = get_logger("adapter.queue.pubsub").bind(
            domain="adapter",
            key="queue",
            provider="pubsub",
        )

    async def init(self) -> None:
        if self._publisher_client is None:
            try:
                from google.cloud import pubsub_v1
            except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
                raise LifecycleError("google-cloud-pubsub-missing") from exc
            self._publisher_client = pubsub_v1.PublisherClient()
        if self._subscriber_client is None and self._settings.subscription:
            try:
                from google.cloud import pubsub_v1
            except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
                raise LifecycleError("google-cloud-pubsub-missing") from exc
            self._subscriber_client = pubsub_v1.SubscriberClient()

        publisher = self._ensure_publisher()
        self._topic_path = publisher.topic_path(
            self._settings.project_id, self._settings.topic
        )

        if self._settings.subscription and self._subscriber_client:
            self._subscription_path = self._subscriber_client.subscription_path(
                self._settings.project_id,
                self._settings.subscription,
            )

        self._logger.info("pubsub-adapter-init", topic=self._topic_path)

    async def cleanup(self) -> None:
        if self._publisher_client and self._owns_publisher:
            close = getattr(self._publisher_client, "close", None)
            if close:
                close()
        if self._subscriber_client and self._owns_subscriber:
            close = getattr(self._subscriber_client, "close", None)
            if close:
                close()
        self._publisher_client = None
        self._subscriber_client = None

    async def health(self) -> bool:
        publisher = self._ensure_publisher()
        topic_path = self._ensure_topic_path()
        try:
            await asyncio.to_thread(publisher.get_topic, topic_path)
            return True
        except Exception as exc:  # pragma: no cover - upstream path
            self._logger.warning("pubsub-health-failed", error=str(exc))
            return False

    async def enqueue(self, data: Mapping[str, Any]) -> str:
        publisher = self._ensure_publisher()
        topic_path = self._ensure_topic_path()
        payload = json.dumps(data).encode("utf-8")
        publish_kwargs = self._settings.default_attributes.copy()
        if self._settings.ordering_key:
            publish_kwargs["ordering_key"] = self._settings.ordering_key
        publish_future = publisher.publish(
            topic_path,
            payload,
            **publish_kwargs,
        )
        message_id = await asyncio.to_thread(publish_future.result)
        return message_id

    async def read(self, *, count: int | None = None) -> list[dict[str, Any]]:
        subscription_path = self._subscription_path
        subscriber = self._subscriber_client
        if not subscription_path or not subscriber:
            raise LifecycleError("pubsub-subscription-not-configured")
        max_messages = count or self._settings.max_messages
        response = await asyncio.to_thread(
            subscriber.pull,
            request={"subscription": subscription_path, "max_messages": max_messages},
        )
        return [
            {
                "message_id": received_message.message.message_id,
                "data": received_message.message.data,
                "attributes": dict(received_message.message.attributes),
                "ack_id": received_message.ack_id,
            }
            for received_message in getattr(response, "received_messages", [])
        ]

    async def ack(self, message_ids: list[str]) -> int:
        if not message_ids:
            return 0
        subscription_path = self._subscription_path
        subscriber = self._subscriber_client
        if not subscription_path or not subscriber:
            raise LifecycleError("pubsub-subscription-not-configured")
        await asyncio.to_thread(
            subscriber.acknowledge,
            request={"subscription": subscription_path, "ack_ids": message_ids},
        )
        return len(message_ids)

    async def pending(self, **_: Any) -> list[dict[str, Any]]:
        if not self._subscription_path:
            return []
        return [{"subscription": self._subscription_path}]

    def _ensure_publisher(self) -> Any:
        if not self._publisher_client:
            raise LifecycleError("pubsub-publisher-not-initialized")
        return self._publisher_client

    def _ensure_topic_path(self) -> str:
        if not self._topic_path:
            raise LifecycleError("pubsub-topic-path-missing")
        return self._topic_path
