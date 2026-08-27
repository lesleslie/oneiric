from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from opentelemetry import metrics, trace
from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.adapters.storage.error_detection import is_not_found_error
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

# Streaming-specific OTel counters (ADR 015 v4 Phase 3). The abort counter
# keeps ``{backend, principal_short}`` as low-cardinality labels and surfaces
# the precise ``abort_reason`` (e.g. cancelled vs exception) as a span
# attribute only, so cardinality stays bounded while operators can still
# pivot from a metric spike to the originating span.
_STREAMING_METER = metrics.get_meter("oneiric.storage.streaming")
_S3_MULTIPART_ABORT_COUNTER = _STREAMING_METER.create_counter(
    name="s3_multipart_abort_total",
    unit="1",
    description=(
        "S3 multipart upload aborts by backend and principal. "
        "abort_reason is recorded as a span attribute, not a label."
    ),
)


def _record_s3_multipart_abort(
    *, backend: str, principal_short: str, reason: str, bytes_uploaded: int
) -> None:
    """Emit s3_multipart_abort_total counter + record reason on current span."""
    _S3_MULTIPART_ABORT_COUNTER.add(
        1, attributes={"backend": backend, "principal_short": principal_short}
    )
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("abort_reason", reason)
        span.set_attribute("bytes_uploaded_before_abort", bytes_uploaded)


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

    async def save_stream(
        self,
        key: str,
        chunk_reader: Callable[[], Iterator[bytes]],
        *,
        metadata: dict[str, str] | None = None,
    ) -> int:
        """Stream chunks to S3 via multipart upload with abort on partial failure.

        Per ADR 015 v4 Phase 3 spec: ``chunk_reader`` is a sync
        ``Callable[[], Iterator[bytes]]`` so callers can iterate the body
        from any source (tar pipe, file reader) without binding it to the
        event loop. The async client drives ``CreateMultipartUpload`` ->
        ``UploadPart`` -> ``CompleteMultipartUpload``; on any
        ``BaseException`` (including ``asyncio.CancelledError``) we issue
        ``AbortMultipartUpload`` so orphan parts do not accrue storage
        cost. ``s3_multipart_abort_total{backend, principal_short}`` is
        emitted on every abort; ``abort_reason`` lives on the span to
        keep label cardinality bounded.
        """
        client = self._ensure_client("s3-client-not-initialized")
        bucket = self._settings.bucket
        # _principal_short is attached at adapter wiring time when running
        # under the orchestrator; fall back to ``unknown`` so metric labels
        # stay populated for non-orchestrator deployments.
        principal_short = getattr(self, "_principal_short", "unknown")

        upload_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if metadata:
            upload_kwargs["Metadata"] = self._sanitize_metadata(metadata)

        upload_id: str | None = None
        bytes_uploaded = 0
        try:
            create_resp = await client.create_multipart_upload(**upload_kwargs)
            upload_id = create_resp["UploadId"]
            parts: list[dict[str, Any]] = []
            part_number = 1
            for chunk in chunk_reader():
                if not chunk:
                    continue
                upload_resp = await client.upload_part(
                    Bucket=bucket,
                    Key=key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=chunk,
                )
                parts.append({"PartNumber": part_number, "ETag": upload_resp["ETag"]})
                bytes_uploaded += len(chunk)
                part_number += 1
            await client.complete_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            self._logger.info(
                "s3-stream-save",
                key=key,
                bytes=bytes_uploaded,
                parts=len(parts),
                metadata_keys=len(metadata) if metadata else 0,
            )
            return bytes_uploaded
        except BaseException as exc:
            reason = (
                "cancelled" if isinstance(exc, asyncio.CancelledError) else "exception"
            )
            if upload_id is not None:
                try:
                    await client.abort_multipart_upload(
                        Bucket=bucket, Key=key, UploadId=upload_id
                    )
                except Exception as abort_exc:  # pragma: no cover - best effort
                    self._logger.warning(
                        "s3-multipart-abort-failed",
                        key=key,
                        error=str(abort_exc),
                    )
            _record_s3_multipart_abort(
                backend="s3",
                principal_short=principal_short,
                reason=reason,
                bytes_uploaded=bytes_uploaded,
            )
            raise

    def load_stream(
        self,
        key: str,
        *,
        chunk_size: int = 65536,
    ) -> Callable[[], Iterator[bytes]]:
        """Return a callable that yields S3 object body chunks.

        Uses a sync ``boto3`` client (lazy-created from the underlying
        AWS session) so the body can be iterated synchronously without
        bridging async -> sync at the consumer. The callable produces a
        fresh ``Iterator[bytes]`` on each invocation.

        Raises ``LifecycleError`` if the object is missing (mirrors the
        ``LifecycleError`` contract used by the local adapter).
        """
        bucket = self._settings.bucket
        sync_client = self._build_sync_client()
        # Probe existence upfront so the caller gets the same error shape
        # as the local adapter (LifecycleError) instead of an aioboto3
        # # BotoCoreError leaking out of the callable on iteration.
        try:
            sync_client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            if is_not_found_error(
                exc,
                codes={"NoSuchKey", "NotFound", "404"},
                messages=("NoSuchKey", "Not Found", "404"),
            ):
                raise LifecycleError("s3-storage-key-not-found") from exc
            raise

        def reader() -> Iterator[bytes]:
            response = sync_client.get_object(Bucket=bucket, Key=key)
            try:
                body = response["Body"]
                while True:
                    chunk = body.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                response["Body"].close()

        return reader

    def _build_sync_client(self) -> Any:
        """Lazily build a sync ``boto3`` client from the same session.

        The async aioboto3 client cannot yield a streaming body synchronously,
        so the streaming load path needs a sync counterpart. We reuse the
        session kwargs (region, profile, endpoint URL, accelerate, creds) so
        callers see consistent auth/endpoint config across both clients.
        """
        cached = getattr(self, "_sync_client", None)
        if cached is not None:
            return cached
        try:
            import boto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:  # pragma: no cover - defensive
            raise LifecycleError("boto3-missing") from exc

        session_kwargs: dict[str, Any] = {}
        if self._settings.profile_name:
            session_kwargs["profile_name"] = self._settings.profile_name
        if self._settings.region:
            session_kwargs["region_name"] = self._settings.region
        session = boto3.session.Session(**session_kwargs)

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
        self._sync_client = session.client(**client_kwargs)
        return self._sync_client
