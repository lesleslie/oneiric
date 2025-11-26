"""Remote manifest loader and artifact fetcher."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import urllib.request
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from oneiric.core.config import RemoteSourceConfig, SecretsHook
from oneiric.core.logging import get_logger
from oneiric.core.resolution import Candidate, CandidateSource, Resolver

from .models import RemoteManifest, RemoteManifestEntry
from .metrics import (
    record_digest_checks_metric,
    record_remote_duration_metric,
    record_remote_failure_metric,
    record_remote_success_metric,
)
from .security import get_canonical_manifest_for_signing, verify_manifest_signature
from .telemetry import record_remote_failure, record_remote_success

logger = get_logger("remote")

VALID_DOMAINS = {"adapter", "service", "task", "event", "workflow"}

# Default HTTP timeout for remote fetches (30 seconds)
DEFAULT_HTTP_TIMEOUT = 30.0


@dataclass
class RemoteSyncResult:
    manifest: RemoteManifest
    registered: int
    duration_ms: float
    per_domain: Dict[str, int]
    skipped: int


class ArtifactManager:
    def __init__(self, cache_dir: str, verify_tls: bool = True) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.verify_tls = verify_tls

    def fetch(self, uri: str, sha256: Optional[str], headers: Dict[str, str]) -> Path:
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
        # Early path traversal detection before any processing
        if ".." in uri or (not sha256 and ("/" in uri or "\\" in uri)):
            # Check if it's a legitimate URL (starts with http:// or https://)
            if not uri.startswith(("http://", "https://", "file://")):
                raise ValueError(f"Path traversal attempt detected in URI: {uri}")

        # Sanitize filename to prevent path traversal
        if sha256:
            filename = sha256  # SHA256 is safe (hex string)
        else:
            # Sanitize filename from URI
            filename = Path(uri).name
            # Additional validation: ensure no path separators
            if "/" in filename or "\\" in filename or ".." in filename:
                raise ValueError(f"Invalid filename in URI: {uri}")

        destination = (self.cache_dir / filename).resolve()

        # CRITICAL: Verify destination is within cache_dir (prevent path traversal)
        cache_dir_resolved = self.cache_dir.resolve()
        if not destination.is_relative_to(cache_dir_resolved):
            raise ValueError(
                f"Path traversal attempt detected: {destination} "
                f"is not within cache directory {cache_dir_resolved}"
            )

        # Check if already cached
        if destination.exists():
            if sha256:
                _assert_digest(destination, sha256)
            return destination

        # Try local file first (only for legitimate file:// URIs or absolute paths)
        if uri.startswith("file://"):
            local_path = Path(uri[7:])  # Strip file:// prefix
        elif uri.startswith("/"):
            local_path = Path(uri)
        else:
            local_path = None

        if local_path and local_path.exists():
            data = local_path.read_bytes()
            destination.write_bytes(data)
            if sha256:
                _assert_digest(destination, sha256)
            return destination

        # Fetch via HTTP/HTTPS with timeout
        if not uri.startswith(("http://", "https://")):
            raise ValueError(f"Unsupported URI scheme (must be http://, https://, or file://): {uri}")

        request = urllib.request.Request(uri, headers=headers)
        context = None
        if not self.verify_tls:
            import ssl

            context = ssl._create_unverified_context()

        # Add timeout to prevent indefinite hangs
        with urllib.request.urlopen(request, context=context, timeout=DEFAULT_HTTP_TIMEOUT) as response:  # type: ignore[arg-type]
            tmp_fd, tmp_path = tempfile.mkstemp(dir=self.cache_dir, prefix="dl-")
            with os.fdopen(tmp_fd, "wb") as fh:
                fh.write(response.read())

        tmp_file = Path(tmp_path)
        if sha256:
            _assert_digest(tmp_file, sha256)
        tmp_file.rename(destination)
        return destination


async def sync_remote_manifest(
    resolver: Resolver,
    config: RemoteSourceConfig,
    *,
    secrets: Optional[SecretsHook] = None,
    manifest_url: Optional[str] = None,
) -> Optional[RemoteSyncResult]:
    """Fetch a remote manifest and register its entries against the resolver."""

    url = manifest_url or config.manifest_url
    if not url:
        logger.info("remote-skip", reason="no-manifest-url")
        return None
    if not config.enabled and not manifest_url:
        logger.info("remote-skip", reason="disabled")
        return None

    try:
        return await _run_sync(resolver, config, url, secrets)
    except Exception as exc:
        error = str(exc)
        record_remote_failure(config.cache_dir, error)
        record_remote_failure_metric(url=url, error=error)
        raise


async def remote_sync_loop(
    resolver: Resolver,
    config: RemoteSourceConfig,
    *,
    secrets: Optional[SecretsHook] = None,
    manifest_url: Optional[str] = None,
    interval_override: Optional[float] = None,
) -> None:
    """Continuously refresh remote manifest candidates based on refresh_interval."""

    url = manifest_url or config.manifest_url
    if not url:
        logger.info("remote-refresh-skip", reason="no-manifest-url")
        return
    interval = interval_override if interval_override is not None else config.refresh_interval
    if not interval:
        logger.info("remote-refresh-skip", reason="no-refresh-interval")
        return

    while True:
        await asyncio.sleep(interval)
        try:
            await _run_sync(resolver, config, url, secrets)
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
    secrets: Optional[SecretsHook],
) -> Optional[RemoteSyncResult]:
    headers = await _auth_headers(config, secrets)
    manifest_data = _fetch_text(url, headers, verify_tls=config.verify_tls)
    manifest = _parse_manifest(manifest_data)
    artifact_manager = ArtifactManager(config.cache_dir, verify_tls=config.verify_tls)

    registered = 0
    digest_checks = 0
    start = time.perf_counter()
    per_domain: Dict[str, int] = {}
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
            artifact_path = artifact_manager.fetch(entry.uri, entry.sha256, headers)
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


async def _auth_headers(config: RemoteSourceConfig, secrets: Optional[SecretsHook]) -> Dict[str, str]:
    token = config.auth.token
    if not token and config.auth.secret_id and secrets:
        token = await secrets.get(config.auth.secret_id)
    if not token:
        return {}
    return {config.auth.header_name: token}


def _fetch_text(url: str, headers: Dict[str, str], *, verify_tls: bool) -> str:
    local_path = Path(url)
    if local_path.exists():
        return local_path.read_text()
    request = urllib.request.Request(url, headers=headers)
    context = None
    if not verify_tls:
        import ssl

        context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, context=context, timeout=DEFAULT_HTTP_TIMEOUT) as response:  # type: ignore[arg-type]
        payload = response.read().decode("utf-8")
    return payload


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


def _candidate_from_entry(entry: RemoteManifestEntry, artifact_path: Optional[Path]) -> Candidate:
    metadata = dict(entry.metadata)
    metadata.update(
        {
            "remote_uri": entry.uri,
            "artifact_path": str(artifact_path) if artifact_path else None,
            "version": entry.version,
            "source": "remote",
        }
    )
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


def _assert_digest(path: Path, expected: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected.lower():
        raise ValueError(f"Digest mismatch for {path}: expected {expected}, got {digest}")


def _validate_entry(entry: RemoteManifestEntry) -> Optional[str]:
    """Comprehensive validation of remote manifest entry.

    Validates domain, key format, provider, factory format, and bounds.
    """
    from oneiric.core.security import (
        validate_factory_string,
        validate_key_format,
        validate_priority_bounds,
        validate_stack_level_bounds,
    )

    # Domain validation
    if entry.domain not in VALID_DOMAINS:
        return f"unsupported domain '{entry.domain}'"

    # Key validation (prevent path traversal)
    if not entry.key:
        return "missing key"
    is_valid, error = validate_key_format(entry.key)
    if not is_valid:
        return f"invalid key: {error}"

    # Provider validation
    if not entry.provider:
        return "missing provider"
    is_valid, error = validate_key_format(entry.provider)
    if not is_valid:
        return f"invalid provider: {error}"

    # Factory validation (format only, security check happens in resolve_factory)
    if not entry.factory:
        return "missing factory"
    is_valid, error = validate_factory_string(entry.factory)
    if not is_valid:
        return f"invalid factory: {error}"

    # Priority bounds checking
    if entry.priority is not None:
        is_valid, error = validate_priority_bounds(entry.priority)
        if not is_valid:
            return error

    # Stack level bounds checking
    if entry.stack_level is not None:
        is_valid, error = validate_stack_level_bounds(entry.stack_level)
        if not is_valid:
            return error

    # URI validation (if present) - prevent path traversal
    if entry.uri and entry.uri.startswith(".."):
        return f"URI contains path traversal: {entry.uri}"

    return None
