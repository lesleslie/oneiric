"""Helpers to register built-in adapter metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from oneiric.core.resolution import Resolver

from .cache import MemoryCacheAdapter, RedisCacheAdapter
from .database import MySQLDatabaseAdapter, PostgresDatabaseAdapter, SQLiteDatabaseAdapter
from .http import AioHTTPAdapter, HTTPClientAdapter
from .identity import Auth0IdentityAdapter
from .metadata import AdapterMetadata, register_adapter_metadata
from .monitoring import (
    LogfireMonitoringAdapter,
    OTLPObservabilityAdapter,
    SentryMonitoringAdapter,
)
from .queue import NATSQueueAdapter, RedisStreamsQueueAdapter
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


def builtin_adapter_metadata() -> List[AdapterMetadata]:
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
        HTTPClientAdapter.metadata,
        AioHTTPAdapter.metadata,
        PostgresDatabaseAdapter.metadata,
        MySQLDatabaseAdapter.metadata,
        SQLiteDatabaseAdapter.metadata,
        Auth0IdentityAdapter.metadata,
        EnvSecretAdapter.metadata,
        FileSecretAdapter.metadata,
        InfisicalSecretAdapter.metadata,
        GCPSecretManagerAdapter.metadata,
        AWSSecretManagerAdapter.metadata,
        LogfireMonitoringAdapter.metadata,
        OTLPObservabilityAdapter.metadata,
        SentryMonitoringAdapter.metadata,
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
