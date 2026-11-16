from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coredis import Redis  # ty: ignore[import-not-found]

    from oneiric.adapters.metadata import AdapterMetadata
    from oneiric.adapters.queue.redis_streams import (
        RedisStreamsQueueAdapter,
        RedisStreamsQueueSettings,
    )
    from oneiric.core.resolution import Resolver


def builtin_adapter_metadata() -> list[AdapterMetadata]:
    """Every adapter the resolver can pick, with its metadata.

    The family imports live here rather than at module scope. Importing
    them eagerly made ``import oneiric.adapters.bootstrap`` cost ~2.3 s,
    because it pulled in every adapter family and each one's client
    libraries. Callers that only want :func:`queued_publisher` -- the
    Claude Code hooks that publish one bus event per tool call -- paid
    that tax on the tool-call critical path for no reason.
    """
    # Lazy import keeps the oneiric cold-start path from pulling the
    # bifrost module on every run (3-agent F8 fix: stay inside the
    # single ``oneiric.adapters`` package namespace).
    from .cache import (
        MemoryCacheAdapter,
        PersistentKVCacheAdapter,
        RedisCacheAdapter,
    )
    from .database import (
        DuckDBDatabaseAdapter,
        MySQLDatabaseAdapter,
        PostgresDatabaseAdapter,
        SQLiteDatabaseAdapter,
    )
    from .dns import CloudflareDNSAdapter, GCDNSAdapter
    from .dns.route53 import Route53DNSAdapter
    from .embedding import (
        OpenAIEmbeddingAdapter,
    )
    from .file_transfer import (
        FTPFileTransferAdapter,
        HTTPArtifactAdapter,
        HTTPSUploadAdapter,
        SCPFileTransferAdapter,
        SFTPFileTransferAdapter,
    )
    from .graph import ArangoDBGraphAdapter, DuckDBPGQAdapter, Neo4jGraphAdapter
    from .http import AioHTTPAdapter, HTTPClientAdapter
    from .identity import Auth0IdentityAdapter
    from .llm import AnthropicLLM, OpenAILLMAdapter
    from .llm.bifrost import BifrostLLMRouter
    from .messaging import (
        APNSPushAdapter,
        FCMPushAdapter,
        MailgunAdapter,
        SendGridAdapter,
        SlackAdapter,
        TeamsAdapter,
        TwilioAdapter,
        WebhookAdapter,
        WebPushAdapter,
    )
    from .monitoring import (
        LogfireMonitoringAdapter,
        OTLPObservabilityAdapter,
        SentryMonitoringAdapter,
    )
    from .nosql.dynamodb import DynamoDBAdapter
    from .nosql.firestore import FirestoreAdapter
    from .nosql.mongodb import MongoDBAdapter
    from .queue import (
        CloudTasksQueueAdapter,
        LavinMQQueueAdapter,
        NATSQueueAdapter,
        PubSubQueueAdapter,
        RedisStreamsQueueAdapter,
    )
    from .secrets import (
        AWSSecretManagerAdapter,
        EnvSecretAdapter,
        FileSecretAdapter,
        GCPSecretManagerAdapter,
        InfisicalSecretAdapter,
        KeyringSecretAdapter,
    )
    from .storage import (
        AzureBlobStorageAdapter,
        GCSStorageAdapter,
        LocalStorageAdapter,
        S3StorageAdapter,
    )
    from .vector import AgentDBAdapter, PgvectorAdapter, PineconeAdapter, QdrantAdapter

    return [
        MemoryCacheAdapter.metadata,
        PersistentKVCacheAdapter.metadata,
        RedisCacheAdapter.metadata,
        LocalStorageAdapter.metadata,
        S3StorageAdapter.metadata,
        GCSStorageAdapter.metadata,
        AzureBlobStorageAdapter.metadata,
        RedisStreamsQueueAdapter.metadata,
        NATSQueueAdapter.metadata,
        CloudTasksQueueAdapter.metadata,
        PubSubQueueAdapter.metadata,
        # priority=330 — above redis-streams (300). Registered so it is
        # reachable by explicit opt-in (`use("queue", provider="lavinmq")`),
        # NOT so it can win by priority: `settings/oneiric.yaml` pins
        # ("adapter", "queue") to redis-streams, and `override_score` is
        # the first element of the scoring tuple. See
        # docs/plans/2026-11-08-lavinmq-provider-pinning.md.
        LavinMQQueueAdapter.metadata,
        HTTPClientAdapter.metadata,
        AioHTTPAdapter.metadata,
        PostgresDatabaseAdapter.metadata,
        MySQLDatabaseAdapter.metadata,
        SQLiteDatabaseAdapter.metadata,
        DuckDBDatabaseAdapter.metadata,
        AgentDBAdapter.metadata,
        PgvectorAdapter.metadata,
        PineconeAdapter.metadata,
        QdrantAdapter.metadata,
        OpenAIEmbeddingAdapter.metadata,
        OpenAILLMAdapter.metadata,
        AnthropicLLM.metadata,
        Auth0IdentityAdapter.metadata,
        EnvSecretAdapter.metadata,
        FileSecretAdapter.metadata,
        KeyringSecretAdapter.metadata,
        InfisicalSecretAdapter.metadata,
        GCPSecretManagerAdapter.metadata,
        AWSSecretManagerAdapter.metadata,
        LogfireMonitoringAdapter.metadata,
        OTLPObservabilityAdapter.metadata,
        SentryMonitoringAdapter.metadata,
        SendGridAdapter.metadata,
        MailgunAdapter.metadata,
        TwilioAdapter.metadata,
        SlackAdapter.metadata,
        TeamsAdapter.metadata,
        WebhookAdapter.metadata,
        WebPushAdapter.metadata,
        APNSPushAdapter.metadata,
        FCMPushAdapter.metadata,
        MongoDBAdapter.metadata,
        DynamoDBAdapter.metadata,
        FirestoreAdapter.metadata,
        Neo4jGraphAdapter.metadata,
        ArangoDBGraphAdapter.metadata,
        DuckDBPGQAdapter.metadata,
        CloudflareDNSAdapter.metadata,
        GCDNSAdapter.metadata,
        Route53DNSAdapter.metadata,
        FTPFileTransferAdapter.metadata,
        SFTPFileTransferAdapter.metadata,
        SCPFileTransferAdapter.metadata,
        HTTPArtifactAdapter.metadata,
        HTTPSUploadAdapter.metadata,
        BifrostLLMRouter.metadata,
    ]


def register_builtin_adapters(resolver: Resolver) -> None:
    """Register every built-in adapter's metadata with *resolver*."""
    from .metadata import register_adapter_metadata

    adapters = builtin_adapter_metadata()
    register_adapter_metadata(
        resolver,
        package_name="oneiric.adapters",
        package_path=str(Path(__file__).parent),
        adapters=adapters,
    )


def queued_publisher(
    *,
    settings: RedisStreamsQueueSettings | None = None,
    redis_client: Redis | None = None,
) -> RedisStreamsQueueAdapter:
    """Canonical factory for the bodai.hooks.* bus channel.

    Returns a RedisStreamsQueueAdapter configured with default settings
    (or an operator-supplied override). Caller is responsible for awaiting
    ``await adapter.init()`` before first publish/subscribe.

    This is the canonical entry point for hook-bus publishers (Mahavishnu's
    ``bodai_hook_bridge._publish`` and downstream consumers). Underlying
    adapter: ``oneiric.adapters.queue.redis_streams``.

    The adapter import is local to the factory: this function is the only
    thing the bus publishers need from this module, and importing it at
    module scope made every hook publish pay for the whole adapter
    catalogue.
    """
    from .queue.redis_streams import RedisStreamsQueueAdapter

    return RedisStreamsQueueAdapter(settings=settings, redis_client=redis_client)
