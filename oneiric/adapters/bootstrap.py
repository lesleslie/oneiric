"""Helpers to register built-in adapter metadata."""

from __future__ import annotations

from pathlib import Path

from oneiric.core.resolution import Resolver

from .cache import MemoryCacheAdapter, RedisCacheAdapter
from .database import (
    DuckDBDatabaseAdapter,
    MySQLDatabaseAdapter,
    PostgresDatabaseAdapter,
    SQLiteDatabaseAdapter,
)
from .dns import CloudflareDNSAdapter, GCDNSAdapter
from .dns.route53 import Route53DNSAdapter
from .embedding import (
    ONNXEmbeddingAdapter,
    OpenAIEmbeddingAdapter,
    SentenceTransformersAdapter,
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
)
from .secrets import (
    AWSSecretManagerAdapter,
    EnvSecretAdapter,
    FileSecretAdapter,
    GCPSecretManagerAdapter,
    InfisicalSecretAdapter,
)
from .storage import (
    AzureBlobStorageAdapter,
    GCSStorageAdapter,
    LocalStorageAdapter,
    S3StorageAdapter,
)
from .vector import PineconeAdapter, QdrantAdapter


def builtin_adapter_metadata() -> list[AdapterMetadata]:
    """Return metadata for built-in adapters shipped with Oneiric."""

    return [
        MemoryCacheAdapter.metadata,
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
        PineconeAdapter.metadata,
        QdrantAdapter.metadata,
        OpenAIEmbeddingAdapter.metadata,
        SentenceTransformersAdapter.metadata,
        ONNXEmbeddingAdapter.metadata,
        OpenAILLMAdapter.metadata,
        AnthropicLLM.metadata,
        Auth0IdentityAdapter.metadata,
        EnvSecretAdapter.metadata,
        FileSecretAdapter.metadata,
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
    """Register built-in adapters with the resolver."""

    adapters = builtin_adapter_metadata()
    register_adapter_metadata(
        resolver,
        package_name="oneiric.adapters",
        package_path=str(Path(__file__).parent),
        adapters=adapters,
    )
