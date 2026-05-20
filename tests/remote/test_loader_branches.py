from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.core.config import RemoteAuthConfig, RemoteSourceConfig
from oneiric.core.resolution import CandidateSource, Resolver
from oneiric.core.resiliency import CircuitBreakerOpen
from oneiric.remote.loader import (
    ArtifactManager,
    _auth_headers,
    _candidate_from_entry,
    _extract_signatures,
    _fetch_text,
    _local_path_from_url,
    _parse_manifest,
    _parse_timestamp,
    _validate_entry,
    _validate_signature_timing,
    remote_sync_loop,
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


# ---------------------------------------------------------------------------
# _local_path_from_url: file:// URI branches (lines 81-85)
# ---------------------------------------------------------------------------


def test_local_path_from_url_file_uri_allowed(tmp_path) -> None:
    local_file = tmp_path / "manifest.yaml"
    local_file.write_text("source: test\nentries: []\n")

    result = _local_path_from_url(
        f"file://{local_file}",
        allow_file_uris=True,
        allowed_file_uri_roots=[str(tmp_path)],
    )
    assert result == local_file


def test_local_path_from_url_file_uri_disabled_raises() -> None:
    with pytest.raises(ValueError, match="file URI access disabled"):
        _local_path_from_url(
            "file:///some/path/manifest.yaml",
            allow_file_uris=False,
            allowed_file_uri_roots=[],
        )


# ---------------------------------------------------------------------------
# ArtifactManager private methods
# ---------------------------------------------------------------------------


def test_artifact_manager_validate_uri_empty_raises(tmp_path) -> None:
    mgr = ArtifactManager(str(tmp_path))
    with pytest.raises(ValueError, match="URI cannot be empty"):
        mgr._validate_uri("")


def test_artifact_manager_get_safe_filename_path_traversal_raises(tmp_path) -> None:
    mgr = ArtifactManager(str(tmp_path))
    # Path("..").name == ".." which triggers the traversal check
    with pytest.raises(ValueError, match="Path traversal"):
        mgr._get_safe_filename("..", None)


def test_artifact_manager_get_destination_path_outside_cache_raises(tmp_path) -> None:
    mgr = ArtifactManager(str(tmp_path / "cache"))
    with pytest.raises(ValueError, match="Path traversal attempt detected"):
        mgr._get_destination_path("../outside.bin")


def test_artifact_manager_try_local_file_disabled_raises(tmp_path) -> None:
    mgr = ArtifactManager(str(tmp_path), allow_file_uris=False)
    with pytest.raises(ValueError, match="file URI access disabled for artifacts"):
        mgr._try_local_file("file:///some/path.bin", tmp_path / "dest.bin", None)


def test_artifact_manager_try_local_file_missing_returns_none(tmp_path) -> None:
    mgr = ArtifactManager(str(tmp_path), allow_file_uris=True)
    result = mgr._try_local_file(
        f"file://{tmp_path}/nonexistent.bin", tmp_path / "dest.bin", None
    )
    assert result is None


@pytest.mark.asyncio
async def test_artifact_manager_fetch_remote_file_unsupported_scheme(tmp_path) -> None:
    mgr = ArtifactManager(str(tmp_path))
    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        await mgr._fetch_remote_file("ftp://example.com/file", tmp_path / "dest.bin", None, {})


@pytest.mark.asyncio
async def test_artifact_manager_fetch_remote_file_cleans_up_on_digest_error(tmp_path) -> None:
    mgr = ArtifactManager(str(tmp_path))
    fake_tmp = tmp_path / "fake-dl.bin"
    fake_tmp.write_bytes(b"real content")

    with patch.object(mgr, "_download_to_temp_file", return_value=fake_tmp):
        with pytest.raises(ValueError, match="Digest mismatch"):
            await mgr._fetch_remote_file(
                "https://example.com/file",
                tmp_path / "dest.bin",
                "badhash" * 9,
                {},
            )
    assert not fake_tmp.exists()


# ---------------------------------------------------------------------------
# remote_sync_loop early-return paths (lines 285-293)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_sync_loop_returns_early_when_no_url() -> None:
    resolver = Resolver()
    config = RemoteSourceConfig()  # no manifest_url
    await remote_sync_loop(resolver, config)  # must return immediately


@pytest.mark.asyncio
async def test_remote_sync_loop_returns_early_when_no_interval() -> None:
    resolver = Resolver()
    config = RemoteSourceConfig(
        manifest_url="https://example.com/m.json",
        refresh_interval=0.0,
    )
    await remote_sync_loop(resolver, config, interval_override=0.0)


@pytest.mark.asyncio
async def test_remote_sync_loop_circuit_breaker_logs_and_continues(monkeypatch) -> None:
    resolver = Resolver()
    config = RemoteSourceConfig(
        manifest_url="https://example.com/m.json",
        refresh_interval=0.01,
    )

    call_count = [0]

    class FakeBreaker:
        async def call(self, func):
            call_count[0] += 1
            raise CircuitBreakerOpen("remote", 1.0)

    monkeypatch.setattr("oneiric.remote.loader._breaker_for", lambda *a, **kw: FakeBreaker())

    async def fake_sleep(t):
        if call_count[0] >= 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await remote_sync_loop(resolver, config)

    assert call_count[0] >= 1


# ---------------------------------------------------------------------------
# _parse_manifest: yaml fallback and signature failure (498, 504)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_to_temp_file_cleans_up_on_stream_error(tmp_path, monkeypatch) -> None:
    import httpx

    mgr = ArtifactManager(str(tmp_path))

    # Mock streaming to raise mid-stream
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    async def failing_aiter_bytes():
        yield b"partial"
        raise RuntimeError("stream error")

    mock_response.aiter_bytes = failing_aiter_bytes
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

    with pytest.raises(RuntimeError, match="stream error"):
        await mgr._download_to_temp_file("https://example.com/file.bin", {})

    # No stray temp files should remain
    leftover = list(tmp_path.glob("dl-*"))
    assert len(leftover) == 0


@pytest.mark.asyncio
async def test_fetch_text_via_httpx_returns_response_text(monkeypatch) -> None:
    import httpx
    from oneiric.remote import loader as _loader

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = "source: http-result\nentries: []\n"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    class FakeAsyncClientCM:
        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeAsyncClientCM())

    result = await _fetch_text(
        "https://example.com/manifest.yaml",
        headers={},
        verify_tls=True,
        allow_file_uris=False,
        allowed_file_uri_roots=[],
    )
    assert result == "source: http-result\nentries: []\n"


def test_parse_manifest_yaml_fallback() -> None:
    yaml_text = "source: test\nentries: []\n"
    manifest = _parse_manifest(yaml_text, verify_signature=False)
    assert manifest.source == "test"


def test_parse_manifest_unsupported_algorithm_raises() -> None:
    import json

    manifest_text = json.dumps(
        {
            "source": "test",
            "entries": [],
            "signatures": [{"signature": "abc123", "algorithm": "rsa-sha256"}],
        }
    )
    with pytest.raises(ValueError, match="Unsupported signature algorithm"):
        _parse_manifest(manifest_text, verify_signature=True)


def test_parse_manifest_signature_failure_raises() -> None:
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    bad_sig = base64.b64encode(b"not-a-real-sig").decode("ascii")
    manifest_text = '{"source": "test", "entries": [], "signature": "' + bad_sig + '"}'

    with pytest.raises(ValueError, match="Signature verification failed"):
        _parse_manifest(
            manifest_text,
            verify_signature=True,
            signature_policy=RemoteSourceConfig(
                trusted_public_keys=[
                    base64.b64encode(
                        private_key.public_key().public_bytes_raw()
                    ).decode("ascii")
                ]
            ),
        )


# ---------------------------------------------------------------------------
# _extract_signatures: non-dict/non-str skip (line 534)
# ---------------------------------------------------------------------------


def test_extract_signatures_skips_non_dict_non_str_entries() -> None:
    signatures, algorithms = _extract_signatures(
        {"signatures": [42, None, {"signature": "abc"}]}
    )
    assert signatures == ["abc"]


# ---------------------------------------------------------------------------
# _parse_timestamp branches (573, 577-578, 580, 582)
# ---------------------------------------------------------------------------


def test_parse_timestamp_invalid_iso_string_raises() -> None:
    with pytest.raises(ValueError, match="Invalid ISO timestamp"):
        _parse_timestamp("not-a-timestamp")


def test_parse_timestamp_naive_datetime_adds_utc() -> None:
    from datetime import datetime, timezone

    naive = datetime(2024, 1, 1, 12, 0, 0)  # no tzinfo
    result = _parse_timestamp(naive.isoformat())
    assert result.tzinfo is not None


def test_parse_timestamp_aware_datetime_converts_to_utc() -> None:
    result = _parse_timestamp("2024-06-01T10:00:00+05:00")
    assert result is not None
    assert result.tzinfo is not None


def test_parse_timestamp_datetime_object_directly() -> None:
    from datetime import datetime, timezone

    aware_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = _parse_timestamp(aware_dt)
    assert result is not None


def test_parse_timestamp_invalid_type_raises() -> None:
    with pytest.raises(ValueError, match="Invalid timestamp value"):
        _parse_timestamp(12345)


# ---------------------------------------------------------------------------
# Metadata builder branches (640, 643, 649, 658, 667, 669, 676, 678, 709)
# ---------------------------------------------------------------------------


def test_candidate_from_entry_includes_owner_settings_model_and_dag() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="cache",
        provider="redis",
        factory="oneiric.adapters.bridge:AdapterBridge",
        owner="platform-team",
        settings_model="oneiric.adapters:CacheSettings",
        timeout_seconds=30,
        retry_policy={"attempts": 2},
        requires=["dep1"],
        conflicts_with=["other"],
        python_version=">=3.11",
        os_platform=["linux"],
        dag={"nodes": []},
        license="MIT",
        documentation_url="https://docs.example.com",
    )

    candidate = _candidate_from_entry(entry, artifact_path=None)
    m = candidate.metadata

    assert m.get("owner") == "platform-team"
    assert m.get("settings_model") == "oneiric.adapters:CacheSettings"
    assert m.get("timeout_seconds") == 30
    assert m.get("retry_policy") == {"attempts": 2}
    assert m.get("requires") == ["dep1"]
    assert m.get("conflicts_with") == ["other"]
    assert m.get("python_version") == ">=3.11"
    assert m.get("os_platform") == ["linux"]
    assert m.get("dag") == {"nodes": []}
    assert m.get("license") == "MIT"
    assert m.get("documentation_url") == "https://docs.example.com"


# ---------------------------------------------------------------------------
# _validate_entry validator branches (738, 757, 768, 779, 787-789, 792-794)
# ---------------------------------------------------------------------------


def test_validate_entry_invalid_key_format() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="invalid key!",
        provider="valid",
        factory="mod:Cls",
    )
    error = _validate_entry(entry)
    assert error is not None
    assert "invalid key" in error


def test_validate_entry_missing_provider() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="valid-key",
        provider="",
        factory="mod:Cls",
    )
    error = _validate_entry(entry)
    assert error == "missing provider"


def test_validate_entry_invalid_provider_format() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="valid-key",
        provider="invalid provider!",
        factory="mod:Cls",
    )
    error = _validate_entry(entry)
    assert error is not None
    assert "invalid provider" in error


def test_validate_entry_invalid_factory_format() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="valid-key",
        provider="valid",
        factory="oneiric.some.module:Invalid Class!",  # valid module, bad class
    )
    error = _validate_entry(entry)
    assert error is not None
    assert "invalid factory" in error or "factory" in error.lower()


def test_validate_entry_priority_out_of_bounds() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="valid-key",
        provider="valid",
        factory="oneiric.adapters.bridge:AdapterBridge",
        priority=9999,
    )
    error = _validate_entry(entry)
    assert error is not None
    assert "Priority" in error or "priority" in error.lower()


def test_validate_entry_stack_level_out_of_bounds() -> None:
    entry = RemoteManifestEntry(
        domain="adapter",
        key="valid-key",
        provider="valid",
        factory="oneiric.adapters.bridge:AdapterBridge",
        stack_level=999,
    )
    error = _validate_entry(entry)
    assert error is not None
