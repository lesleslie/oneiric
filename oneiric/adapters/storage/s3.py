"""S3-backed storage adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.adapters.storage.utils import is_not_found_error
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class S3StorageSettings(BaseModel):
    """Settings for the S3-backed storage adapter."""

    bucket: str
    region: str | None = Field(default=None)
    endpoint_url: str | None = Field(default=None)
    profile_name: str | None = Field(default=None)
    access_key_id: str | None = Field(default=None)
    secret_access_key: str | None = Field(default=None)
    session_token: str | None = Field(default=None)
    healthcheck_key: str | None = Field(
        default=None,
        description="Optional key to fetch during health checks for deeper coverage.",
    )
    use_accelerate_endpoint: bool = Field(
        default=False,
        description="Enable S3 accelerate endpoints when true.",
    )


class S3StorageAdapter(EnsureClientMixin):
    """Async S3 adapter powered by aioboto3 clients."""

    metadata = AdapterMetadata(
        category="storage",
        provider="s3",
        factory="oneiric.adapters.storage.s3:S3StorageAdapter",
        capabilities=["blob", "stream", "delete", "bucket"],
        stack_level=25,
        priority=400,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=S3StorageSettings,
    )

    def __init__(
        self,
        settings: S3StorageSettings,
        *,
        client: Any | None = None,
        client_factory: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._client_factory = client_factory
        self._client_cm: Any | None = None
        self._logger = get_logger("adapter.storage.s3").bind(
            domain="adapter",
            key="storage",
            provider="s3",
            bucket=settings.bucket,
        )

    async def init(self) -> None:
        if self._client:
            return
        if self._client_factory:
            self._client = await self._client_factory()
            return
        try:
            import aioboto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:  # pragma: no cover - defensive
            raise LifecycleError("aioboto3-missing") from exc

        session_kwargs: dict[str, Any] = {}
        if self._settings.profile_name:
            session_kwargs["profile_name"] = self._settings.profile_name
        if self._settings.region:
            session_kwargs["region_name"] = self._settings.region
        session = aioboto3.Session(**session_kwargs)
        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "endpoint_url": self._settings.endpoint_url,
            "use_accelerate_endpoint": self._settings.use_accelerate_endpoint,
            "aws_access_key_id": self._settings.access_key_id,
            "aws_secret_access_key": self._settings.secret_access_key,
            "aws_session_token": self._settings.session_token,
            "config": Config(signature_version="s3v4"),
        }
        client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
        self._client_cm = session.client(**client_kwargs)
        self._client = await self._client_cm.__aenter__()
        self._logger.info("adapter-init", adapter="s3-storage")

    async def health(self) -> bool:
        client = self._ensure_client("s3-client-not-initialized")
        try:
            await client.head_bucket(Bucket=self._settings.bucket)
            if self._settings.healthcheck_key:
                await client.head_object(
                    Bucket=self._settings.bucket, Key=self._settings.healthcheck_key
                )
            return True
        except Exception as exc:  # pragma: no cover - network error path
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._client_cm:
            await self._client_cm.__aexit__(None, None, None)
        self._client = None
        self._client_cm = None
        self._logger.info("adapter-cleanup-complete", adapter="s3-storage")

    async def upload(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> None:
        client = self._ensure_client("s3-client-not-initialized")
        await client.put_object(
            Bucket=self._settings.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def download(self, key: str) -> bytes | None:
        client = self._ensure_client("s3-client-not-initialized")
        try:
            response = await client.get_object(Bucket=self._settings.bucket, Key=key)
        except Exception as exc:
            if is_not_found_error(
                exc,
                codes={"NoSuchKey", "404"},
                messages=("NoSuchKey", "404"),
            ):
                return None
            raise
        body = response["Body"]
        data = await body.read()
        await body.close()
        return data

    async def delete(self, key: str) -> None:
        client = self._ensure_client("s3-client-not-initialized")
        await client.delete_object(Bucket=self._settings.bucket, Key=key)

    async def list(self, prefix: str = "") -> list[str]:
        client = self._ensure_client("s3-client-not-initialized")
        continuation: str | None = None
        items: list[str] = []
        while True:
            kwargs = {
                "Bucket": self._settings.bucket,
                "Prefix": prefix,
            }
            if continuation:
                kwargs["ContinuationToken"] = continuation
            response = await client.list_objects_v2(**kwargs)
            for obj in response.get("Contents", []):
                key = obj.get("Key")
                if key:
                    items.append(key)
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
            if not continuation:
                break
        return items
