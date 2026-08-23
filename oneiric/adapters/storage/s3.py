from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.adapters.storage.error_detection import is_not_found_error
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

# S3 user-defined metadata keys are restricted to this character set per the
# S3 spec. Total user metadata is capped at 2 KB per object; values are
# always stored as UTF-8 strings.
_METADATA_KEY_RE = re.compile(r"^[A-Za-z0-9!\-_.*'()]+$")
_MAX_USER_METADATA_BYTES = 2048


class S3StorageSettings(BaseModel):
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
    metadata = AdapterMetadata(
        category="storage",
        provider="s3",
        factory="oneiric.adapters.storage.s3: S3StorageAdapter",
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
        except (OSError, RuntimeError) as exc:  # pragma: no cover - network error path
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._client_cm:
            await self._client_cm.__aexit__(None, None, None)
        self._client = None
        self._client_cm = None
        self._logger.info("adapter-cleanup-complete", adapter="s3-storage")

    async def upload(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        client = self._ensure_client("s3-client-not-initialized")
        put_kwargs: dict[str, Any] = {
            "Bucket": self._settings.bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
        }
        if metadata:
            sanitized = self._sanitize_metadata(metadata)
            put_kwargs["Metadata"] = sanitized
        await client.put_object(**put_kwargs)

    def _sanitize_metadata(self, metadata: dict[str, str]) -> dict[str, str]:
        """Validate user-defined metadata against S3 constraints.

        S3 limits user metadata keys to ``[A-Za-z0-9!-_.*'()]`` and total
        encoded metadata to 2048 bytes. Raise ``LifecycleError`` on
        violation so misconfigured callers fail fast at upload time
        rather than at retrieval.
        """
        total_bytes = 0
        sanitized: dict[str, str] = {}
        for key, value in metadata.items():
            if not _METADATA_KEY_RE.match(key):
                raise LifecycleError(
                    f"s3-metadata-invalid-key: {key!r} must match "
                    f"{_METADATA_KEY_RE.pattern!r}"
                )
            if not isinstance(value, str):
                raise LifecycleError(
                    f"s3-metadata-invalid-value: {key!r} must be str, got "
                    f"{type(value).__name__}"
                )
            encoded = value.encode("utf-8")
            total_bytes += len(key.encode("utf-8")) + len(encoded)
            sanitized[key] = value
        if total_bytes > _MAX_USER_METADATA_BYTES:
            raise LifecycleError(
                f"s3-metadata-too-large: {total_bytes} > "
                f"{_MAX_USER_METADATA_BYTES} bytes"
            )
        return sanitized

    async def exists(self, key: str) -> bool:
        """Return True iff ``key`` exists in the bucket.

        Uses ``head_object`` (cheap, no body transfer) and treats 404 /
        ``NoSuchKey`` as ``False``. Any other exception propagates —
        callers should expect transient AWS errors (5xx) to surface.
        """
        client = self._ensure_client("s3-client-not-initialized")
        try:
            await client.head_object(Bucket=self._settings.bucket, Key=key)
        except Exception as exc:
            if is_not_found_error(
                exc,
                codes={"NoSuchKey", "NotFound", "404"},
                messages=("NoSuchKey", "Not Found", "404"),
            ):
                return False
            raise
        return True

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

    async def list(self, prefix: str = "") -> list[str]:  # ty: ignore[invalid-type-form] — ty resolves `list` to the method in scope
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
