"""Remote manifest loader and artifact fetcher."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from oneiric.core.config import RemoteSourceConfig, SecretsHook
from oneiric.core.logging import get_logger
from oneiric.core.resiliency import CircuitBreaker, CircuitBreakerOpen, run_with_retry
from oneiric.core.resolution import Candidate, CandidateSource, Resolver

from .metrics import (
    record_digest_checks_metric,
    record_remote_duration_metric,
    record_remote_failure_metric,
    record_remote_success_metric,
)
from .models import RemoteManifest, RemoteManifestEntry
from .security import get_canonical_manifest_for_signing, verify_manifest_signature
from .telemetry import record_remote_failure, record_remote_success

logger = get_logger("remote")

VALID_DOMAINS = {"adapter", "action", "service", "task", "event", "workflow"}

# Default HTTP timeout for remote fetches (30 seconds)
DEFAULT_HTTP_TIMEOUT = 30.0

_REMOTE_BREAKERS: dict[str, CircuitBreaker] = {}


def _breaker_key(url: str, cache_dir: str) -> str:
    return f"{cache_dir}:{url}"


def _breaker_for(config: RemoteSourceConfig, url: str) -> CircuitBreaker:
    key = _breaker_key(url, config.cache_dir)
    breaker = _REMOTE_BREAKERS.get(key)
    if breaker is None:
        breaker = CircuitBreaker(
            name=f"remote:{url}",
            failure_threshold=config.circuit_breaker_threshold,
            recovery_time=config.circuit_breaker_reset,
        )
        _REMOTE_BREAKERS[key] = breaker
    return breaker


@dataclass
class RemoteSyncResult:
    manifest: RemoteManifest
    registered: int
    duration_ms: float
    per_domain: dict[str, int]
    skipped: int


def _local_path_from_url(url: str) -> Path | None:
    if url.startswith("file://"):
        return Path(url[7:])
    path = Path(url)
    if path.exists():
        return path
    return None


class ArtifactManager:
    def __init__(
        self,
        cache_dir: str,
        verify_tls: bool = True,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.verify_tls = verify_tls
        self.timeout = timeout

    async def fetch(
        self, uri: str, sha256: str | None, headers: dict[str, str]
    ) -> Path:
        """Fetch artifact with path traversal protection and timeout.

        Args:
            uri: URI to fetch (HTTP/HTTPS or local file path)
            sha256: Expected SHA256 digest (optional)
            headers: HTTP headers for request

        Returns:
            Path to cached artifact

        Raises:
            ValueError: If path traversal detected or digest mismatch
        """
        # Validate and sanitize URI
        self._validate_uri(uri)
        filename = self._get_safe_filename(uri, sha256)
        destination = self._get_destination_path(filename)

        # Return cached file if available
        if destination.exists():
            if sha256:
                _assert_digest(destination, sha256)
            return destination

        # Try local file first
        local_result = self._try_local_file(uri, destination, sha256)
        if local_result:
            return local_result

        # Fetch from remote HTTP/HTTPS
        return await self._fetch_remote_file(uri, destination, sha256, headers)

    def _validate_uri(self, uri: str) -> None:
        """Validate URI for security issues."""
        if not uri:
            raise ValueError("URI cannot be empty")

        # Block path traversal attempts
        if ".." in uri and not uri.startswith(("http://", "https://", "file://")):
            raise ValueError(f"Path traversal attempt detected in URI: {uri}")

        # Block absolute paths unless they're file:// URLs
        if uri.startswith("/") and not uri.startswith("file://"):
            raise ValueError(f"Path traversal attempt detected in URI: {uri}")

        # Block relative paths with directory separators
        if not uri.startswith(("http://", "https://", "file://")):
            # Check for directory traversal characters
            if "/" in uri or "\\" in uri:
                raise ValueError(f"Path traversal attempt detected in URI: {uri}")

    def _get_safe_filename(self, uri: str, sha256: str | None) -> str:
        """Get safe filename from URI or SHA256."""
        if sha256:
            return sha256  # SHA256 is safe (hex string)

        # Sanitize filename from URI
        filename = Path(uri).name
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"Path traversal attempt detected in URI: {uri}")
        return filename

    def _get_destination_path(self, filename: str) -> Path:
        """Get validated destination path within cache directory."""
        destination = (self.cache_dir / filename).resolve()
        cache_dir_resolved = self.cache_dir.resolve()

        # CRITICAL: Verify destination is within cache_dir
        if not destination.is_relative_to(cache_dir_resolved):
            raise ValueError(
                f"Path traversal attempt detected: {destination} "
                f"is not within cache directory {cache_dir_resolved}"
            )

        return destination

    def _try_local_file(
        self, uri: str, destination: Path, sha256: str | None
    ) -> Path | None:
        """Try to fetch from local file system."""
        # Only handle file:// URIs (absolute paths are blocked in validation)
        if not uri.startswith("file://"):
            return None

        local_path = Path(uri[7:])

        # Copy local file to cache
        if local_path.exists():
            data = local_path.read_bytes()
            destination.write_bytes(data)
            if sha256:
                _assert_digest(destination, sha256)
            return destination

        return None

    async def _fetch_remote_file(
        self, uri: str, destination: Path, sha256: str | None, headers: dict[str, str]
    ) -> Path:
        """Fetch file from remote HTTP/HTTPS URL."""
        # Validate URI scheme
        if not uri.startswith(("http://", "https://")):
            raise ValueError(
                f"Unsupported URI scheme (must be http://, https://, or file://): {uri}"
            )

        # Download to temporary file
        tmp_file = await self._download_to_temp_file(uri, headers)

        # Verify digest and rename
        try:
            if sha256:
                _assert_digest(tmp_file, sha256)
            tmp_file.rename(destination)
            return destination
        except Exception:
            tmp_file.unlink(missing_ok=True)
            raise

    async def _download_to_temp_file(self, uri: str, headers: dict[str, str]) -> Path:
        """Download URI to temporary file."""
        tmp_file: Path | None = None
        try:
            async with httpx.AsyncClient(
                verify=self.verify_tls,
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                async with client.stream("GET", uri, headers=headers) as response:
                    response.raise_for_status()
                    with tempfile.NamedTemporaryFile(
                        dir=self.cache_dir,
                        prefix="dl-",
                        delete=False,
                    ) as fh:
                        tmp_file = Path(fh.name)
                        async for chunk in response.aiter_bytes():
                            fh.write(chunk)
        except Exception:
            if tmp_file is not None:
                tmp_file.unlink(missing_ok=True)
            raise

        assert tmp_file is not None  # For type checkers
        return tmp_file


async def sync_remote_manifest(
    resolver: Resolver,
    config: RemoteSourceConfig,
    *,
    secrets: SecretsHook | None = None,
    manifest_url: str | None = None,
) -> RemoteSyncResult | None:
    """Fetch a remote manifest and register its entries against the resolver."""

    url = manifest_url or config.manifest_url
    if not url:
        logger.info("remote-skip", reason="no-manifest-url")
        return None
    if not config.enabled and not manifest_url:
        logger.info("remote-skip", reason="disabled")
        return None

    breaker = _breaker_for(config, url)
    try:
        return await breaker.call(
            lambda: _run_sync(
                resolver,
                config,
                url,
                secrets,
                retry_attempts=config.max_retries,
                retry_base_delay=config.retry_base_delay,
                retry_max_delay=config.retry_max_delay,
                retry_jitter=config.retry_jitter,
            )
        )
    except CircuitBreakerOpen as exc:
        logger.warning(
            "remote-sync-circuit-open",
            url=url,
            retry_after=exc.retry_after,
        )
        return None
    except Exception as exc:
        error = str(exc)
        record_remote_failure(config.cache_dir, error)
        record_remote_failure_metric(url=url, error=error)
        raise


async def remote_sync_loop(
    resolver: Resolver,
    config: RemoteSourceConfig,
    *,
    secrets: SecretsHook | None = None,
    manifest_url: str | None = None,
    interval_override: float | None = None,
) -> None:
    """Continuously refresh remote manifest candidates based on refresh_interval."""

    url = manifest_url or config.manifest_url
    if not url:
        logger.info("remote-refresh-skip", reason="no-manifest-url")
        return
    interval = (
        interval_override if interval_override is not None else config.refresh_interval
    )
    if not interval:
        logger.info("remote-refresh-skip", reason="no-refresh-interval")
        return

    breaker = _breaker_for(config, url)
    while True:
        await asyncio.sleep(interval)
        try:
            await breaker.call(
                lambda: _run_sync(
                    resolver,
                    config,
                    url,
                    secrets,
                    retry_attempts=config.max_retries,
                    retry_base_delay=config.retry_base_delay,
                    retry_max_delay=config.retry_max_delay,
                    retry_jitter=config.retry_jitter,
                )
            )
        except CircuitBreakerOpen as exc:
            logger.warning(
                "remote-refresh-circuit-open",
                url=url,
                retry_after=exc.retry_after,
            )
            continue
        except Exception as exc:  # pragma: no cover - log and continue
            error = str(exc)
            logger.error(
                "remote-refresh-error",
                url=url,
                error=error,
            )
            record_remote_failure(config.cache_dir, error)
            record_remote_failure_metric(url=url, error=error)


async def _run_sync(
    resolver: Resolver,
    config: RemoteSourceConfig,
    url: str,
    secrets: SecretsHook | None,
    *,
    retry_attempts: int,
    retry_base_delay: float,
    retry_max_delay: float,
    retry_jitter: float,
) -> RemoteSyncResult | None:
    headers = await _auth_headers(config, secrets)
    manifest_data = await run_with_retry(
        lambda: _fetch_text(url, headers, verify_tls=config.verify_tls),
        attempts=retry_attempts,
        base_delay=retry_base_delay,
        max_delay=retry_max_delay,
        jitter=retry_jitter,
    )
    manifest = _parse_manifest(manifest_data)
    artifact_manager = ArtifactManager(config.cache_dir, verify_tls=config.verify_tls)

    registered = 0
    digest_checks = 0
    start = time.perf_counter()
    per_domain: dict[str, int] = {}
    skipped = 0
    for entry in manifest.entries:
        error = _validate_entry(entry)
        if error:
            skipped += 1
            logger.warning(
                "remote-entry-invalid",
                domain=entry.domain,
                key=entry.key,
                provider=entry.provider,
                error=error,
            )
            continue
        artifact_path = None
        if entry.uri:
            artifact_path = await run_with_retry(
                lambda: artifact_manager.fetch(entry.uri, entry.sha256, headers),
                attempts=retry_attempts,
                base_delay=retry_base_delay,
                max_delay=retry_max_delay,
                jitter=retry_jitter,
            )
        if entry.sha256:
            digest_checks += 1
        candidate = _candidate_from_entry(entry, artifact_path)
        resolver.register(candidate)
        registered += 1
        per_domain[entry.domain] = per_domain.get(entry.domain, 0) + 1
    source = manifest.source or "remote"
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "remote-sync-complete",
        url=url,
        registered=registered,
        source=source,
        duration_ms=duration_ms,
        digest_checks=digest_checks,
        per_domain=per_domain,
        skipped=skipped,
    )
    record_remote_success(
        config.cache_dir,
        source=source,
        registered=registered,
        duration_ms=duration_ms,
        digest_checks=digest_checks,
        per_domain=per_domain,
        skipped=skipped,
    )
    record_remote_success_metric(source=source, url=url, registered=registered)
    record_remote_duration_metric(url=url, source=source, duration_ms=duration_ms)
    record_digest_checks_metric(url=url, count=digest_checks)
    return RemoteSyncResult(
        manifest=manifest,
        registered=registered,
        duration_ms=duration_ms,
        per_domain=per_domain,
        skipped=skipped,
    )


async def _auth_headers(
    config: RemoteSourceConfig, secrets: SecretsHook | None
) -> dict[str, str]:
    token = config.auth.token
    if not token and config.auth.secret_id and secrets:
        token = await secrets.get(config.auth.secret_id)
    if not token:
        return {}
    return {config.auth.header_name: token}


async def _fetch_text(url: str, headers: dict[str, str], *, verify_tls: bool) -> str:
    local_path = _local_path_from_url(url)
    if local_path:
        return local_path.read_text()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Unsupported manifest URL: {url}")
    async with httpx.AsyncClient(
        verify=verify_tls,
        timeout=DEFAULT_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def _parse_manifest(text: str, *, verify_signature: bool = True) -> RemoteManifest:
    """Parse and optionally verify remote manifest.

    Args:
        text: Raw manifest text (JSON or YAML)
        verify_signature: Whether to verify signature (default: True)

    Returns:
        Parsed RemoteManifest

    Raises:
        ValueError: If manifest is invalid or signature verification fails
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Remote manifest must be a mapping at the top level.")

    # Verify signature if present and verification enabled
    if verify_signature and data.get("signature"):
        signature = data.get("signature")
        algorithm = data.get("signature_algorithm", "ed25519")

        if algorithm != "ed25519":
            raise ValueError(f"Unsupported signature algorithm: {algorithm}")

        # Get canonical form for verification
        canonical = get_canonical_manifest_for_signing(data)

        # Verify signature
        is_valid, error = verify_manifest_signature(canonical, signature)
        if not is_valid:
            raise ValueError(f"Signature verification failed: {error}")

        logger.info("manifest-signature-verified", algorithm=algorithm)

    elif verify_signature and not data.get("signature"):
        # No signature present - log warning but allow (for backward compatibility)
        logger.warning(
            "manifest-unsigned",
            recommendation="Enable signature verification for production use",
        )

    return RemoteManifest(**data)


def _candidate_from_entry(
    entry: RemoteManifestEntry, artifact_path: Path | None
) -> Candidate:
    """Convert manifest entry to Candidate with full metadata propagation (Stage 4 enhancement)."""
    # Build metadata dictionary
    metadata = _build_candidate_metadata(entry, artifact_path)

    # Filter out None values
    metadata = {key: value for key, value in metadata.items() if value is not None}

    return Candidate(
        domain=entry.domain,
        key=entry.key,
        provider=entry.provider,
        priority=entry.priority,
        stack_level=entry.stack_level,
        factory=entry.factory,
        metadata=metadata,
        source=CandidateSource.REMOTE_MANIFEST,
    )


def _build_candidate_metadata(
    entry: RemoteManifestEntry, artifact_path: Path | None
) -> dict[str, Any]:
    """Build complete metadata dictionary for candidate."""
    metadata = entry.metadata.copy()

    # Add core metadata
    _add_core_metadata(metadata, entry, artifact_path)

    # Add domain-specific metadata
    _add_adapter_metadata(metadata, entry)
    _add_action_metadata(metadata, entry)
    _add_dependency_metadata(metadata, entry)
    _add_platform_metadata(metadata, entry)
    _add_documentation_metadata(metadata, entry)
    _add_event_metadata(metadata, entry)
    _add_dag_metadata(metadata, entry)

    return metadata


def _add_core_metadata(
    metadata: dict[str, Any], entry: RemoteManifestEntry, artifact_path: Path | None
) -> None:
    """Add core metadata fields."""
    metadata.update(
        {
            "remote_uri": entry.uri,
            "artifact_path": str(artifact_path) if artifact_path else None,
            "version": entry.version,
            "source": "remote",
        }
    )


def _add_adapter_metadata(metadata: dict[str, Any], entry: RemoteManifestEntry) -> None:
    """Add adapter-specific metadata."""
    if entry.capabilities:
        metadata["capabilities"] = entry.capability_names
        metadata["capability_descriptors"] = entry.capability_payloads()
    if entry.owner:
        metadata["owner"] = entry.owner
    metadata["requires_secrets"] = entry.requires_secrets
    if entry.settings_model:
        metadata["settings_model"] = entry.settings_model


def _add_action_metadata(metadata: dict[str, Any], entry: RemoteManifestEntry) -> None:
    """Add action-specific metadata."""
    metadata["side_effect_free"] = entry.side_effect_free
    if entry.timeout_seconds is not None:
        metadata["timeout_seconds"] = entry.timeout_seconds
    if entry.retry_policy:
        metadata["retry_policy"] = entry.retry_policy


def _add_dependency_metadata(
    metadata: dict[str, Any], entry: RemoteManifestEntry
) -> None:
    """Add dependency constraint metadata."""
    if entry.requires:
        metadata["requires"] = entry.requires
    if entry.conflicts_with:
        metadata["conflicts_with"] = entry.conflicts_with


def _add_platform_metadata(
    metadata: dict[str, Any], entry: RemoteManifestEntry
) -> None:
    """Add platform constraint metadata."""
    if entry.python_version:
        metadata["python_version"] = entry.python_version
    if entry.os_platform:
        metadata["os_platform"] = entry.os_platform


def _add_documentation_metadata(
    metadata: dict[str, Any], entry: RemoteManifestEntry
) -> None:
    """Add documentation metadata."""
    if entry.license:
        metadata["license"] = entry.license
    if entry.documentation_url:
        metadata["documentation_url"] = entry.documentation_url


def _add_event_metadata(metadata: dict[str, Any], entry: RemoteManifestEntry) -> None:
    """Add event-specific metadata."""
    if entry.event_topics:
        metadata["topics"] = entry.event_topics
    if entry.event_max_concurrency is not None:
        metadata["max_concurrency"] = entry.event_max_concurrency
    if entry.event_filters:
        metadata["filters"] = entry.event_filters
    if entry.event_priority is not None:
        metadata["event_priority"] = entry.event_priority
    if entry.event_fanout_policy:
        metadata["fanout_policy"] = entry.event_fanout_policy


def _add_dag_metadata(metadata: dict[str, Any], entry: RemoteManifestEntry) -> None:
    """Add DAG metadata."""
    if entry.dag:
        metadata["dag"] = entry.dag


def _assert_digest(path: Path, expected: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected.lower():
        raise ValueError(
            f"Digest mismatch for {path}: expected {expected}, got {digest}"
        )


def _validate_entry(entry: RemoteManifestEntry) -> str | None:
    """Comprehensive validation of remote manifest entry.

    Validates domain, key format, provider, factory format, and bounds.
    """
    from oneiric.core.security import (
        validate_factory_string,
        validate_key_format,
        validate_priority_bounds,
        validate_stack_level_bounds,
    )

    # Validate basic fields
    if error := _validate_domain(entry):
        return error
    if error := _validate_key_field(entry, validate_key_format):
        return error
    if error := _validate_provider_field(entry, validate_key_format):
        return error
    if error := _validate_factory_field(entry, validate_factory_string):
        return error

    # Validate bounds
    if error := _validate_bounds(
        entry, validate_priority_bounds, validate_stack_level_bounds
    ):
        return error

    # Validate URI
    if error := _validate_uri_field(entry):
        return error

    return None


def _validate_domain(entry: RemoteManifestEntry) -> str | None:
    """Validate domain field."""
    if entry.domain not in VALID_DOMAINS:
        return f"unsupported domain '{entry.domain}'"
    return None


def _validate_key_field(entry: RemoteManifestEntry, validate_key_format) -> str | None:
    """Validate key field."""
    if not entry.key:
        return "missing key"
    is_valid, error = validate_key_format(entry.key)
    if not is_valid:
        return f"invalid key: {error}"
    return None


def _validate_provider_field(
    entry: RemoteManifestEntry, validate_key_format
) -> str | None:
    """Validate provider field."""
    if not entry.provider:
        return "missing provider"
    is_valid, error = validate_key_format(entry.provider)
    if not is_valid:
        return f"invalid provider: {error}"
    return None


def _validate_factory_field(
    entry: RemoteManifestEntry, validate_factory_string
) -> str | None:
    """Validate factory field."""
    if not entry.factory:
        return "missing factory"
    is_valid, error = validate_factory_string(entry.factory)
    if not is_valid:
        return f"invalid factory: {error}"
    return None


def _validate_bounds(
    entry: RemoteManifestEntry, validate_priority_bounds, validate_stack_level_bounds
) -> str | None:
    """Validate priority and stack level bounds."""
    # Priority bounds
    if entry.priority is not None:
        is_valid, error = validate_priority_bounds(entry.priority)
        if not is_valid:
            return error

    # Stack level bounds
    if entry.stack_level is not None:
        is_valid, error = validate_stack_level_bounds(entry.stack_level)
        if not is_valid:
            return error

    return None


def _validate_uri_field(entry: RemoteManifestEntry) -> str | None:
    """Validate URI field for path traversal."""
    if entry.uri and entry.uri.startswith(".."):
        return f"URI contains path traversal: {entry.uri}"
    return None
