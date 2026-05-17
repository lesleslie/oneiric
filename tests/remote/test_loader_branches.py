from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.core.config import RemoteAuthConfig, RemoteSourceConfig
from oneiric.core.resolution import CandidateSource, Resolver
from oneiric.core.resiliency import CircuitBreakerOpen
from oneiric.remote.loader import (
    _auth_headers,
    _candidate_from_entry,
    _extract_signatures,
    _fetch_text,
    _local_path_from_url,
    _parse_manifest,
    _validate_signature_timing,
    sync_remote_manifest,
)
from oneiric.remote.models import RemoteManifestEntry


def test_local_path_from_url_accepts_local_paths(tmp_path) -> None:
    local_file = tmp_path / "manifest.yaml"
    local_file.write_text("source: local\nentries: []\n")

    resolved = _local_path_from_url(
        str(local_file),
        allow_file_uris=True,
        allowed_file_uri_roots=[str(tmp_path)],
    )

    assert resolved == local_file


@pytest.mark.asyncio
async def test_auth_headers_supports_token_and_secrets_hook() -> None:
    direct = RemoteSourceConfig(
        auth=RemoteAuthConfig(header_name="X-Token", token="direct-token")
    )
    assert await _auth_headers(direct, None) == {"X-Token": "direct-token"}

    class SecretsHook:
        async def get(self, secret_id: str) -> str:
            assert secret_id == "secret-id"
            return "hook-token"

    secret = RemoteSourceConfig(
        auth=RemoteAuthConfig(header_name="X-Auth", secret_id="secret-id")
    )
    assert await _auth_headers(secret, SecretsHook()) == {"X-Auth": "hook-token"}

    assert await _auth_headers(RemoteSourceConfig(), None) == {}


@pytest.mark.asyncio
async def test_fetch_text_reads_local_file_and_rejects_unsupported_scheme(tmp_path) -> None:
    local_file = tmp_path / "manifest.yaml"
    local_file.write_text("source: local\nentries: []\n")

    text = await _fetch_text(
        str(local_file),
        headers={},
        verify_tls=True,
        allow_file_uris=True,
        allowed_file_uri_roots=[str(tmp_path)],
    )

    assert "source: local" in text

    with pytest.raises(ValueError, match="Unsupported manifest URL"):
        await _fetch_text(
            "ftp://example.com/manifest.yaml",
            headers={},
            verify_tls=True,
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )


def test_extract_signatures_handles_dict_entries() -> None:
    signatures, algorithms = _extract_signatures(
        {
            "signatures": [
                {"signature": "abc", "algorithm": "ed25519"},
                {"algorithm": "skip-me"},
                "raw-signature",
            ],
            "signature": "top-level",
            "signature_algorithm": "ed25519",
        }
    )

    assert signatures == ["abc", "raw-signature", "top-level"]
    assert algorithms == ["ed25519", "ed25519", "ed25519"]


def test_validate_signature_timing_requires_expiry_and_signed_at() -> None:
    expiry_policy = RemoteSourceConfig(signature_require_expiry=True)

    with pytest.raises(ValueError, match="expires_at"):
        _validate_signature_timing(
            {"signed_at": "2000-01-01T00:00:00+00:00"},
            expiry_policy,
        )

    age_policy = RemoteSourceConfig(
        signature_required=True, signature_max_age_seconds=1
    )
    with pytest.raises(ValueError, match="signed_at"):
        _validate_signature_timing(
            {
                "signed_at": None,
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            age_policy,
        )


def test_candidate_from_entry_includes_retry_and_conflict_metadata() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="cache",
        provider="redis",
        factory="oneiric.adapters.bridge:AdapterBridge",
        retry_policy={"attempts": 3},
        conflicts_with=["memcached"],
    )

    candidate = _candidate_from_entry(entry, artifact_path=None)

    assert candidate.metadata["retry_policy"] == {"attempts": 3}
    assert candidate.metadata["conflicts_with"] == ["memcached"]


@pytest.mark.asyncio
async def test_sync_remote_manifest_breaker_open_returns_none(tmp_path, monkeypatch) -> None:
    resolver = Resolver()
    config = RemoteSourceConfig(
        enabled=True,
        manifest_url="https://example.com/manifest.json",
        cache_dir=str(tmp_path / "cache"),
    )

    class FakeBreaker:
        async def call(self, func):
            raise CircuitBreakerOpen("remote", 1.0)

    monkeypatch.setattr("oneiric.remote.loader._breaker_for", lambda *args, **kwargs: FakeBreaker())

    assert await sync_remote_manifest(resolver, config) is None


@pytest.mark.asyncio
async def test_sync_remote_manifest_records_failure(tmp_path, monkeypatch) -> None:
    resolver = Resolver()
    config = RemoteSourceConfig(
        enabled=True,
        manifest_url="https://example.com/manifest.json",
        cache_dir=str(tmp_path / "cache"),
    )

    class FakeBreaker:
        async def call(self, func):
            raise RuntimeError("boom")

    record_failure = MagicMock()
    record_metric = MagicMock()
    monkeypatch.setattr("oneiric.remote.loader._breaker_for", lambda *args, **kwargs: FakeBreaker())
    monkeypatch.setattr("oneiric.remote.loader.record_remote_failure", record_failure)
    monkeypatch.setattr("oneiric.remote.loader.record_remote_failure_metric", record_metric)

    with pytest.raises(RuntimeError, match="boom"):
        await sync_remote_manifest(resolver, config)

    record_failure.assert_called_once()
    record_metric.assert_called_once()
