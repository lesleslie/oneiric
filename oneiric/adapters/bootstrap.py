from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from oneiric.core.resolution import Resolver

if TYPE_CHECKING:
    from coredis import Redis

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
from .metadata import AdapterMetadata, register_adapter_metadata
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
    NATSQueueAdapter,
    PubSubQueueAdapter,
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
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
from .vector import AgentDBAdapter, PineconeAdapter, QdrantAdapter


def builtin_adapter_metadata() -> list[AdapterMetadata]:
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
        HTTPClientAdapter.metadata,
        AioHTTPAdapter.metadata,
        PostgresDatabaseAdapter.metadata,
        MySQLDatabaseAdapter.metadata,
        SQLiteDatabaseAdapter.metadata,
        DuckDBDatabaseAdapter.metadata,
        AgentDBAdapter.metadata,
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
    ]


def register_builtin_adapters(resolver: Resolver) -> None:
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

    Per docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md
    §4.13.1 — this is the canonical entry point for hook-bus publishers
    (Mahavishnu's ``bodai_hook_bridge._publish`` and downstream consumers).
    Underlying adapter: ``oneiric.adapters.queue.redis_streams``.

    Refs: docs/audits/2026-09-15-decomposition-final-review.md §2.1 W1
    """
    return RedisStreamsQueueAdapter(settings=settings, redis_client=redis_client)
