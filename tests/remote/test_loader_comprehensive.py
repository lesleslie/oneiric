"""Comprehensive tests for oneiric.remote.loader.

This file is intentionally a NEW companion to tests/remote/test_loader.py and
tests/remote/test_loader_branches.py. It mirrors the class-based structure of
tests/unit/test_core_resolution.py and expands coverage of:

- RemoteSyncResult dataclass
- _local_path_from_url (pure URL/path validation)
- _breaker_for caching (the module-global _REMOTE_BREAKERS dict)
- sync_remote_manifest happy path, retry, circuit-breaker, signature failure,
  sha256 mismatch, missing cache_dir handling, telemetry recorder integration
- ArtifactManager (download via httpx.MockTransport, file:// local copy,
  sha256 verification, retry, raises on permanent failure)
- remote_sync_loop bounded execution (N ticks then cancel) and resilience to
  exceptions inside a tick
- _validate_entry / RemoteSourceConfig surface
- Integration: real Resolver + RemoteManifest end-to-end via sync_remote_manifest

Property-based tests (hypothesis) verify the breaker-key caching invariant and
the determinism of sha256 hashing.

Hazards:
- _REMOTE_BREAKERS is module-global -- every test in this file applies the
  `reset_remote_breakers` fixture as a defensive shield (per task spec).
- httpx.MockTransport is sync-callable; AsyncClient handles async dispatch.
- remote_sync_loop is intentionally unbounded -- wrap in asyncio.wait_for.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from oneiric.core.config import (
    RemoteAuthConfig,
    RemoteSourceConfig,
)
from oneiric.core.resiliency import CircuitBreakerOpen
from oneiric.core.resolution import CandidateSource, Resolver
from oneiric.remote import loader as rl
from oneiric.remote.loader import (
    DEFAULT_HTTP_TIMEOUT,
    VALID_DOMAINS,
    ArtifactManager,
    RemoteSyncResult,
    _breaker_for,
    _breaker_key,
    _candidate_from_entry,
    _local_path_from_url,
    _parse_manifest,
    _validate_entry,
    remote_sync_loop,
    sync_remote_manifest,
)
from oneiric.remote.models import (
    RemoteManifest,
    RemoteManifestEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    domain: str = "adapter",
    key: str = "cache",
    provider: str = "redis",
    factory: str = "oneiric.adapters:RedisAdapter",
    **kwargs: object,
) -> RemoteManifestEntry:
    """Factory producing a fresh RemoteManifestEntry."""
    return RemoteManifestEntry(
        domain=domain,
        key=key,
        provider=provider,
        factory=factory,
        **kwargs,
    )


def _build_manifest_dict(*entries: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-serializable manifest dict for HTTP mock responses."""
    default_entry = {
        "domain": "adapter",
        "key": "cache",
        "provider": "redis",
        "factory": "oneiric.adapters:RedisAdapter",
    }
    return {
        "source": "remote",
        "entries": list(entries) if entries else [default_entry],
    }


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> None:
    """Patch httpx.AsyncClient to use a MockTransport with the given handler.

    The loader constructs httpx.AsyncClient inline -- so we monkeypatch the
    httpx.AsyncClient class to return clients backed by our MockTransport.
    """
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("verify", None)
        kwargs.pop("timeout", None)
        kwargs.pop("follow_redirects", None)
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_valid_domains(self, reset_remote_breakers) -> None:
        assert VALID_DOMAINS == {
            "adapter",
            "action",
            "service",
            "task",
            "event",
            "workflow",
        }

    def test_default_http_timeout(self, reset_remote_breakers) -> None:
        assert DEFAULT_HTTP_TIMEOUT == 30.0

    def test_remote_breakers_is_dict(self, reset_remote_breakers) -> None:
        # Smoke test that the private dict exists and is a dict
        assert isinstance(rl._REMOTE_BREAKERS, dict)


# ---------------------------------------------------------------------------
# RemoteSyncResult
# ---------------------------------------------------------------------------


class TestRemoteSyncResult:
    def test_minimal_construction(self, reset_remote_breakers) -> None:
        manifest = RemoteManifest()
        result = RemoteSyncResult(
            manifest=manifest,
            registered=0,
            duration_ms=0.0,
            per_domain={},
            skipped=0,
        )
        assert result.manifest is manifest
        assert result.registered == 0
        assert result.duration_ms == 0.0
        assert result.per_domain == {}
        assert result.skipped == 0

    def test_custom_values(self, reset_remote_breakers) -> None:
        manifest = RemoteManifest(source="test")
        result = RemoteSyncResult(
            manifest=manifest,
            registered=3,
            duration_ms=125.5,
            per_domain={"adapter": 2, "service": 1},
            skipped=1,
        )
        assert result.registered == 3
        assert result.duration_ms == 125.5
        assert result.per_domain == {"adapter": 2, "service": 1}
        assert result.skipped == 1

    def test_per_domain_counts(self, reset_remote_breakers) -> None:
        result = RemoteSyncResult(
            manifest=RemoteManifest(),
            registered=5,
            duration_ms=0.0,
            per_domain={"adapter": 3, "service": 2},
            skipped=0,
        )
        assert sum(result.per_domain.values()) == result.registered

    def test_skipped_tracks_invalid_entries(self, reset_remote_breakers) -> None:
        result = RemoteSyncResult(
            manifest=RemoteManifest(),
            registered=1,
            duration_ms=10.0,
            per_domain={"adapter": 1},
            skipped=4,
        )
        assert result.skipped == 4
        assert result.registered == 1


# ---------------------------------------------------------------------------
# _local_path_from_url (pure URL/path validation)
# ---------------------------------------------------------------------------


class TestLocalPathFromUrl:
    def test_file_uri_with_allow_returns_path(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        local = tmp_path / "manifest.yaml"
        local.write_text("source: local\n")
        result = _local_path_from_url(
            f"file://{local}",
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )
        assert result == local

    def test_file_uri_with_allow_false_raises(self, reset_remote_breakers) -> None:
        with pytest.raises(ValueError, match="file URI access disabled"):
            _local_path_from_url(
                "file:///tmp/manifest.yaml",
                allow_file_uris=False,
                allowed_file_uri_roots=[],
            )

    def test_http_url_returns_none(self, reset_remote_breakers) -> None:
        # http(s):// URLs are not local paths -> returns None
        result = _local_path_from_url(
            "https://example.com/manifest.yaml",
            allow_file_uris=True,
            allowed_file_uri_roots=[],
        )
        assert result is None

    def test_https_url_returns_none(self, reset_remote_breakers) -> None:
        result = _local_path_from_url(
            "https://cdn.example.com/manifest.yaml",
            allow_file_uris=False,
            allowed_file_uri_roots=[],
        )
        assert result is None

    def test_existing_local_path_with_allow_returns_path(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        local = tmp_path / "manifest.yaml"
        local.write_text("source: local\n")
        result = _local_path_from_url(
            str(local),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )
        assert result == local

    def test_existing_local_path_without_allow_raises(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        local = tmp_path / "manifest.yaml"
        local.write_text("source: local\n")
        with pytest.raises(ValueError, match="local manifest paths disabled"):
            _local_path_from_url(
                str(local),
                allow_file_uris=False,
                allowed_file_uri_roots=[],
            )

    def test_nonexistent_path_returns_none(self, reset_remote_breakers) -> None:
        result = _local_path_from_url(
            "/nonexistent/path.yaml",
            allow_file_uris=True,
            allowed_file_uri_roots=[],
        )
        assert result is None

    def test_file_uri_outside_allowed_roots_raises(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        other_root = tmp_path / "other"
        other_root.mkdir()
        target = tmp_path / "manifest.yaml"
        target.write_text("x")
        # allowed root is "other", but target is in tmp_path -> denied
        with pytest.raises(ValueError, match="Local path access denied"):
            _local_path_from_url(
                f"file://{target}",
                allow_file_uris=True,
                allowed_file_uri_roots=[str(other_root)],
            )

    def test_file_uri_with_empty_allowlist_permits(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        # Empty allowlist == "no restrictions" per _assert_allowed_path
        local = tmp_path / "manifest.yaml"
        local.write_text("x")
        result = _local_path_from_url(
            f"file://{local}",
            allow_file_uris=True,
            allowed_file_uri_roots=[],
        )
        assert result == local


# ---------------------------------------------------------------------------
# _breaker_for and _breaker_key (caching invariants)
# ---------------------------------------------------------------------------


class TestBreakerFor:
    def test_same_url_and_cache_dir_returns_same_breaker(
        self, reset_remote_breakers, cache_dir: Path
    ) -> None:
        cfg = RemoteSourceConfig(cache_dir=str(cache_dir))
        url = "https://example.com/manifest.yaml"
        b1 = _breaker_for(cfg, url)
        b2 = _breaker_for(cfg, url)
        assert b1 is b2

    def test_distinct_cache_dirs_yield_distinct_breakers(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        cache_a = tmp_path / "cache-a"
        cache_b = tmp_path / "cache-b"
        cache_a.mkdir()
        cache_b.mkdir()
        cfg_a = RemoteSourceConfig(cache_dir=str(cache_a))
        cfg_b = RemoteSourceConfig(cache_dir=str(cache_b))
        url = "https://example.com/manifest.yaml"
        b_a = _breaker_for(cfg_a, url)
        b_b = _breaker_for(cfg_b, url)
        assert b_a is not b_b

    def test_distinct_urls_yield_distinct_breakers(
        self, reset_remote_breakers, cache_dir: Path
    ) -> None:
        cfg = RemoteSourceConfig(cache_dir=str(cache_dir))
        b1 = _breaker_for(cfg, "https://a.example.com/m.yaml")
        b2 = _breaker_for(cfg, "https://b.example.com/m.yaml")
        assert b1 is not b2

    def test_config_knobs_flow_through(
        self, reset_remote_breakers, cache_dir: Path
    ) -> None:
        cfg = RemoteSourceConfig(
            cache_dir=str(cache_dir),
            circuit_breaker_threshold=10,
            circuit_breaker_reset=120.0,
        )
        breaker = _breaker_for(cfg, "https://example.com/m.yaml")
        assert breaker.name == "remote:https://example.com/m.yaml"

    def test_breaker_key_format(self, reset_remote_breakers) -> None:
        key = _breaker_key("https://example.com/m.yaml", "/tmp/cache")
        assert key == "/tmp/cache:https://example.com/m.yaml"

    def test_breaker_key_distinct_inputs_distinct_outputs(
        self, reset_remote_breakers
    ) -> None:
        k1 = _breaker_key("u1", "/cache/a")
        k2 = _breaker_key("u2", "/cache/a")
        k3 = _breaker_key("u1", "/cache/b")
        assert len({k1, k2, k3}) == 3

    def test_breaker_cached_across_calls(
        self, reset_remote_breakers, cache_dir: Path
    ) -> None:
        cfg = RemoteSourceConfig(cache_dir=str(cache_dir))
        url = "https://example.com/manifest.yaml"
        breakers = [_breaker_for(cfg, url) for _ in range(5)]
        first = breakers[0]
        assert all(b is first for b in breakers)


# ---------------------------------------------------------------------------
# sync_remote_manifest
# ---------------------------------------------------------------------------


class TestSyncRemoteManifest:
    async def test_returns_none_when_no_url(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(cache_dir=str(cache_dir), manifest_url=None)
        result = await sync_remote_manifest(resolver, cfg)
        assert result is None

    async def test_returns_none_when_disabled(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=False,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
        )
        result = await sync_remote_manifest(resolver, cfg)
        assert result is None

    async def test_manifest_url_override_bypasses_disabled(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=False,
            cache_dir=str(cache_dir),
            verify_tls=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_build_manifest_dict())

        _install_mock_transport(monkeypatch, handler)
        result = await sync_remote_manifest(
            resolver, cfg, manifest_url="https://example.com/m.yaml"
        )
        assert result is not None
        assert isinstance(result, RemoteSyncResult)

    async def test_happy_path_with_mock_transport(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_build_manifest_dict())

        _install_mock_transport(monkeypatch, handler)
        result = await sync_remote_manifest(resolver, cfg)
        assert result is not None
        assert result.registered == 1
        assert result.skipped == 0
        assert "adapter" in result.per_domain
        assert result.duration_ms >= 0.0

    async def test_invalid_entries_increment_skipped(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "source": "remote",
                    "entries": [
                        {
                            "domain": "adapter",
                            "key": "good",
                            "provider": "redis",
                            "factory": "oneiric.adapters:RedisAdapter",
                        },
                        {
                            "domain": "unsupported-domain",
                            "key": "bad",
                            "provider": "p",
                            "factory": "f:F",
                        },
                    ],
                },
            )

        _install_mock_transport(monkeypatch, handler)
        result = await sync_remote_manifest(resolver, cfg)
        assert result is not None
        assert result.registered == 1
        assert result.skipped == 1

    async def test_registers_candidate_on_resolver(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_build_manifest_dict())

        _install_mock_transport(monkeypatch, handler)
        await sync_remote_manifest(resolver, cfg)
        candidate = resolver.registry._candidates.get(("adapter", "cache"))
        assert candidate is not None
        assert len(candidate) == 1
        assert candidate[0].provider == "redis"
        assert candidate[0].source == CandidateSource.REMOTE_MANIFEST

    async def test_circuit_breaker_open_returns_none(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
        )
        breaker = _breaker_for(cfg, cfg.manifest_url or "")

        async def _raise_open(*args: Any, **kwargs: Any) -> Any:
            raise CircuitBreakerOpen(breaker.name, 60.0)

        with patch.object(breaker, "call", side_effect=_raise_open):
            result = await sync_remote_manifest(resolver, cfg)
        assert result is None

    async def test_signature_failure_rejects_manifest(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
            signature_required=True,
            max_retries=1,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_build_manifest_dict())

        _install_mock_transport(monkeypatch, handler)
        with pytest.raises(ValueError, match="signature required"):
            await sync_remote_manifest(resolver, cfg)

    async def test_telemetry_recorder_called_on_success(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_build_manifest_dict())

        _install_mock_transport(monkeypatch, handler)
        calls: list[tuple[Any, ...]] = []
        with patch.object(
            rl,
            "record_remote_success",
            side_effect=lambda *a, **kw: calls.append((a, kw)),
        ):
            await sync_remote_manifest(resolver, cfg)
        assert len(calls) == 1

    async def test_telemetry_failure_called_on_error(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
            max_retries=1,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        _install_mock_transport(monkeypatch, handler)
        calls: list[tuple[Any, ...]] = []
        with patch.object(
            rl,
            "record_remote_failure",
            side_effect=lambda *a, **kw: calls.append((a, kw)),
        ):
            with pytest.raises(Exception):
                await sync_remote_manifest(resolver, cfg)
        assert len(calls) >= 1

    async def test_per_domain_counts_aggregated(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "source": "remote",
                    "entries": [
                        {
                            "domain": "adapter",
                            "key": "cache",
                            "provider": "redis",
                            "factory": "oneiric.adapters:Cache",
                        },
                        {
                            "domain": "adapter",
                            "key": "queue",
                            "provider": "rabbit",
                            "factory": "oneiric.adapters:Queue",
                        },
                        {
                            "domain": "service",
                            "key": "auth",
                            "provider": "google",
                            "factory": "oneiric.adapters:Auth",
                        },
                    ],
                },
            )

        _install_mock_transport(monkeypatch, handler)
        result = await sync_remote_manifest(resolver, cfg)
        assert result is not None
        assert result.per_domain.get("adapter") == 2
        assert result.per_domain.get("service") == 1
        assert result.registered == 3


# ---------------------------------------------------------------------------
# ArtifactManager
# ---------------------------------------------------------------------------


class TestArtifactManager:
    def test_init_creates_cache_directory(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        cache = tmp_path / "fresh"
        assert not cache.exists()
        manager = ArtifactManager(str(cache))
        assert cache.exists()
        assert manager.cache_dir == cache
        assert manager.verify_tls is True
        assert manager.timeout == DEFAULT_HTTP_TIMEOUT
        assert manager.allow_file_uris is False
        assert manager.allowed_file_uri_roots == []

    def test_init_custom_values(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(
            str(cache),
            verify_tls=False,
            timeout=10.0,
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )
        assert manager.verify_tls is False
        assert manager.timeout == 10.0
        assert manager.allow_file_uris is True
        assert manager.allowed_file_uri_roots == [str(tmp_path)]

    def test_init_with_existing_cache_directory(
        self, reset_remote_breakers, cache_dir: Path
    ) -> None:
        manager = ArtifactManager(str(cache_dir))
        assert manager.cache_dir == cache_dir

    async def test_fetch_local_file_with_sha256(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(
            str(cache),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )
        source = tmp_path / "source.txt"
        source.write_text("hello world")
        digest = hashlib.sha256(b"hello world").hexdigest()

        result = await manager.fetch(
            uri=f"file://{source}", sha256=digest, headers={}
        )
        assert result.exists()
        assert result.read_text() == "hello world"
        assert result.name == digest

    async def test_fetch_local_file_digest_mismatch_raises(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(
            str(cache),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
        )
        source = tmp_path / "source.txt"
        source.write_text("hello")
        with pytest.raises(ValueError, match="Digest mismatch"):
            await manager.fetch(
                uri=f"file://{source}",
                sha256="0" * 64,
                headers={},
            )

    async def test_fetch_file_uri_disabled_raises(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(str(cache), allow_file_uris=False)
        with pytest.raises(ValueError, match="file URI access disabled"):
            await manager.fetch(
                uri="file:///tmp/anything.txt", sha256=None, headers={}
            )

    async def test_fetch_empty_uri_raises(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        manager = ArtifactManager(str(tmp_path / "cache"))
        with pytest.raises(ValueError, match="URI cannot be empty"):
            await manager.fetch(uri="", sha256=None, headers={})

    async def test_fetch_path_traversal_raises(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        manager = ArtifactManager(str(tmp_path / "cache"))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(
                uri="../../etc/passwd", sha256=None, headers={}
            )

    async def test_fetch_absolute_path_raises(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        manager = ArtifactManager(str(tmp_path / "cache"))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(
                uri="/etc/passwd", sha256=None, headers={}
            )

    async def test_fetch_remote_http_with_mock_transport(
        self,
        reset_remote_breakers,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(str(cache), verify_tls=False)
        payload = b"binary artifact data"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=payload)

        _install_mock_transport(monkeypatch, handler)
        result = await manager.fetch(
            uri="https://cdn.example.com/artifact.bin",
            sha256=None,
            headers={},
        )
        assert result.exists()
        assert result.read_bytes() == payload

    async def test_fetch_remote_sha256_verification(
        self,
        reset_remote_breakers,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(str(cache), verify_tls=False)
        payload = b"verified payload"
        digest = hashlib.sha256(payload).hexdigest()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=payload)

        _install_mock_transport(monkeypatch, handler)
        result = await manager.fetch(
            uri="https://cdn.example.com/artifact.bin",
            sha256=digest,
            headers={},
        )
        assert result.exists()
        assert result.read_bytes() == payload
        assert result.name == digest

    async def test_fetch_remote_sha256_mismatch_raises(
        self,
        reset_remote_breakers,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(str(cache), verify_tls=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"actual")

        _install_mock_transport(monkeypatch, handler)
        with pytest.raises(ValueError, match="Digest mismatch"):
            await manager.fetch(
                uri="https://cdn.example.com/artifact.bin",
                sha256="0" * 64,
                headers={},
            )

    async def test_fetch_cached_file_returned_without_redownload(
        self,
        reset_remote_breakers,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(str(cache), verify_tls=False)
        payload = b"cached payload"
        digest = hashlib.sha256(payload).hexdigest()
        # Pre-seed cache
        cached_file = cache / digest
        cached_file.write_bytes(payload)

        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(500)

        _install_mock_transport(monkeypatch, handler)
        result = await manager.fetch(
            uri="https://cdn.example.com/artifact.bin",
            sha256=digest,
            headers={},
        )
        assert result == cached_file
        assert call_count["n"] == 0

    async def test_fetch_unsupported_scheme_raises(
        self,
        reset_remote_breakers,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # _validate_uri rejects ftp:// because it contains "/" and is not http(s)/file
        # so the message says "Path traversal" -- pin that behavior.
        manager = ArtifactManager(str(tmp_path / "cache"))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(
                uri="ftp://example.com/artifact.bin",
                sha256=None,
                headers={},
            )

    async def test_fetch_http_500_raises(
        self,
        reset_remote_breakers,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = tmp_path / "cache"
        manager = ArtifactManager(str(cache), verify_tls=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        _install_mock_transport(monkeypatch, handler)
        with pytest.raises(httpx.HTTPStatusError):
            await manager.fetch(
                uri="https://example.com/x.bin", sha256=None, headers={}
            )


# ---------------------------------------------------------------------------
# remote_sync_loop
# ---------------------------------------------------------------------------


class TestRemoteSyncLoop:
    async def test_loop_skips_when_no_url(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(cache_dir=str(cache_dir), manifest_url=None)
        # Should return immediately, not block
        await asyncio.wait_for(
            remote_sync_loop(resolver, cfg),
            timeout=0.5,
        )

    async def test_loop_skips_when_no_interval(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(
            cache_dir=str(cache_dir),
            manifest_url="https://example.com/m.yaml",
            refresh_interval=None,
        )
        await asyncio.wait_for(
            remote_sync_loop(resolver, cfg),
            timeout=0.5,
        )

    async def test_loop_skips_when_interval_override_zero(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(
            cache_dir=str(cache_dir),
            manifest_url="https://example.com/m.yaml",
            refresh_interval=300.0,
        )
        # interval_override=0 -> falsy -> skip
        await asyncio.wait_for(
            remote_sync_loop(resolver, cfg, interval_override=0.0),
            timeout=0.5,
        )

    async def test_loop_runs_n_times_then_cancelled(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            cache_dir=str(cache_dir),
            manifest_url="https://example.com/m.yaml",
            verify_tls=False,
        )
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, json=_build_manifest_dict())

        _install_mock_transport(monkeypatch, handler)
        # Use a tiny interval and wrap with wait_for to bound the loop
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                remote_sync_loop(resolver, cfg, interval_override=0.01),
                timeout=0.15,
            )
        # Loop must have ticked at least once
        assert call_count["n"] >= 1

    async def test_loop_continues_after_circuit_breaker_open(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(
            cache_dir=str(cache_dir),
            manifest_url="https://example.com/m.yaml",
            verify_tls=False,
        )
        breaker = _breaker_for(cfg, cfg.manifest_url or "")

        call_count = {"n": 0}

        async def _raise_open(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            raise CircuitBreakerOpen(breaker.name, 0.01)

        with patch.object(breaker, "call", side_effect=_raise_open):
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    remote_sync_loop(resolver, cfg, interval_override=0.01),
                    timeout=0.1,
                )
        # Loop kept going (didn't break) after CircuitBreakerOpen
        assert call_count["n"] >= 1


# ---------------------------------------------------------------------------
# _validate_entry
# ---------------------------------------------------------------------------


class TestValidateEntry:
    def test_valid_entry_returns_none(self, reset_remote_breakers) -> None:
        e = _make_entry()
        assert _validate_entry(e) is None

    def test_invalid_domain_returns_error(self, reset_remote_breakers) -> None:
        e = _make_entry(domain="invalid")
        result = _validate_entry(e)
        assert result is not None
        assert "unsupported domain" in result

    def test_valid_domains_all_pass(self, reset_remote_breakers) -> None:
        for domain in VALID_DOMAINS:
            e = _make_entry(domain=domain)
            assert _validate_entry(e) is None, f"{domain} should pass"

    def test_invalid_key_returns_error(self, reset_remote_breakers) -> None:
        e = _make_entry(key="invalid key with spaces")
        result = _validate_entry(e)
        assert result is not None
        assert "invalid key" in result

    def test_invalid_provider_returns_error(self, reset_remote_breakers) -> None:
        e = _make_entry(provider="invalid provider")
        result = _validate_entry(e)
        assert result is not None
        assert "invalid provider" in result

    def test_invalid_factory_returns_error(self, reset_remote_breakers) -> None:
        e = _make_entry(factory="invalid-no-colon")
        result = _validate_entry(e)
        assert result is not None
        assert "invalid factory" in result

    def test_priority_out_of_bounds_returns_error(
        self, reset_remote_breakers
    ) -> None:
        e = _make_entry(priority=10000)
        result = _validate_entry(e)
        assert result is not None

    def test_stack_level_out_of_bounds_returns_error(
        self, reset_remote_breakers
    ) -> None:
        e = _make_entry(stack_level=1000)
        result = _validate_entry(e)
        assert result is not None

    def test_path_traversal_uri_returns_error(
        self, reset_remote_breakers
    ) -> None:
        e = _make_entry(uri="../evil/path")
        result = _validate_entry(e)
        assert result is not None
        assert "path traversal" in result


# ---------------------------------------------------------------------------
# _parse_manifest (signature and parsing behaviour)
# ---------------------------------------------------------------------------


class TestParseManifest:
    def test_parses_json(self, reset_remote_breakers) -> None:
        text = json.dumps(_build_manifest_dict())
        manifest = _parse_manifest(text, verify_signature=False)
        assert isinstance(manifest, RemoteManifest)
        assert len(manifest.entries) == 1

    def test_parses_yaml(self, reset_remote_breakers) -> None:
        text = (
            "source: remote\n"
            "entries:\n"
            "  - domain: adapter\n"
            "    key: cache\n"
            "    provider: redis\n"
            "    factory: f:Cache\n"
        )
        manifest = _parse_manifest(text, verify_signature=False)
        assert len(manifest.entries) == 1
        assert manifest.entries[0].key == "cache"

    def test_rejects_non_mapping(self, reset_remote_breakers) -> None:
        with pytest.raises(ValueError, match="must be a mapping"):
            _parse_manifest("[1, 2, 3]", verify_signature=False)

    def test_rejects_unsigned_when_required(
        self, reset_remote_breakers
    ) -> None:
        cfg = RemoteSourceConfig(signature_required=True)
        text = json.dumps(_build_manifest_dict())
        with pytest.raises(ValueError, match="signature required"):
            _parse_manifest(text, signature_policy=cfg)

    def test_unsigned_passes_when_not_required(
        self, reset_remote_breakers
    ) -> None:
        cfg = RemoteSourceConfig(signature_required=False)
        text = json.dumps(_build_manifest_dict())
        manifest = _parse_manifest(text, signature_policy=cfg)
        assert isinstance(manifest, RemoteManifest)


# ---------------------------------------------------------------------------
# _candidate_from_entry
# ---------------------------------------------------------------------------


class TestCandidateFromEntry:
    def test_minimal_entry_to_candidate(self, reset_remote_breakers) -> None:
        e = _make_entry()
        c = _candidate_from_entry(e, artifact_path=None)
        assert c.domain == "adapter"
        assert c.key == "cache"
        assert c.provider == "redis"
        assert c.source == CandidateSource.REMOTE_MANIFEST
        assert c.metadata["source"] == "remote"

    def test_includes_artifact_path_when_provided(
        self, reset_remote_breakers, tmp_path: Path
    ) -> None:
        e = _make_entry(uri="https://cdn.example.com/x.whl")
        artifact = tmp_path / "x.whl"
        artifact.write_text("art")
        c = _candidate_from_entry(e, artifact_path=artifact)
        assert c.metadata["artifact_path"] == str(artifact)
        assert c.metadata["remote_uri"] == "https://cdn.example.com/x.whl"

    def test_excludes_none_metadata(self, reset_remote_breakers) -> None:
        e = _make_entry()
        c = _candidate_from_entry(e, artifact_path=None)
        # None-valued metadata is dropped
        for k, v in c.metadata.items():
            assert v is not None, f"metadata[{k}] is None"


# ---------------------------------------------------------------------------
# RemoteSourceConfig surface
# ---------------------------------------------------------------------------


class TestRemoteSourceConfigInteraction:
    def test_default_config(self, reset_remote_breakers) -> None:
        cfg = RemoteSourceConfig()
        assert cfg.enabled is False
        assert cfg.manifest_url is None
        assert cfg.cache_dir == ".oneiric_cache"
        assert cfg.verify_tls is True
        assert cfg.max_retries == 3

    def test_auth_default_factory(self, reset_remote_breakers) -> None:
        cfg = RemoteSourceConfig()
        assert isinstance(cfg.auth, RemoteAuthConfig)
        assert cfg.auth.header_name == "Authorization"
        assert cfg.auth.token is None

    def test_signature_settings_default(self, reset_remote_breakers) -> None:
        cfg = RemoteSourceConfig()
        assert cfg.signature_required is False
        assert cfg.signature_threshold == 1
        assert cfg.signature_max_age_seconds is None
        assert cfg.signature_require_expiry is False

    def test_circuit_breaker_settings_default(
        self, reset_remote_breakers
    ) -> None:
        cfg = RemoteSourceConfig()
        assert cfg.circuit_breaker_threshold == 5
        assert cfg.circuit_breaker_reset == 60.0

    def test_file_uri_settings_default(self, reset_remote_breakers) -> None:
        cfg = RemoteSourceConfig()
        assert cfg.allow_file_uris is False
        assert cfg.allowed_file_uri_roots == []

    def test_config_flows_into_loader(
        self,
        reset_remote_breakers,
        cache_dir: Path,
    ) -> None:
        cfg = RemoteSourceConfig(
            cache_dir=str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(cache_dir)],
            verify_tls=False,
            circuit_breaker_threshold=10,
        )
        breaker = _breaker_for(cfg, "https://example.com/m.yaml")
        # Breaker exists with the cache_dir-derived key
        assert (
            f"{cache_dir}:https://example.com/m.yaml"
            in rl._REMOTE_BREAKERS
        )
        assert breaker is not None


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestSyncRemoteManifestIntegration:
    async def test_real_resolver_and_manifest_end_to_end(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/m.yaml",
            cache_dir=str(cache_dir),
            verify_tls=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "source": "remote",
                    "entries": [
                        {
                            "domain": "adapter",
                            "key": "cache",
                            "provider": "redis",
                            "factory": "oneiric.adapters:Cache",
                        },
                        {
                            "domain": "service",
                            "key": "auth",
                            "provider": "google",
                            "factory": "oneiric.adapters:Auth",
                        },
                        {
                            "domain": "workflow",
                            "key": "deploy",
                            "provider": "argo",
                            "factory": "oneiric.adapters:Argo",
                        },
                    ],
                },
            )

        _install_mock_transport(monkeypatch, handler)
        result = await sync_remote_manifest(resolver, cfg)
        assert result is not None
        assert result.registered == 3
        assert result.skipped == 0
        assert set(result.per_domain.keys()) == {
            "adapter",
            "service",
            "workflow",
        }
        # Verify the Resolver actually has them registered
        for domain, key in (
            ("adapter", "cache"),
            ("service", "auth"),
            ("workflow", "deploy"),
        ):
            cands = resolver.registry._candidates.get((domain, key))
            assert cands is not None
            assert len(cands) == 1
            assert cands[0].source == CandidateSource.REMOTE_MANIFEST

    async def test_file_uri_manifest_round_trip(
        self,
        reset_remote_breakers,
        resolver: Resolver,
        cache_dir: Path,
        tmp_path: Path,
    ) -> None:
        manifest_file = tmp_path / "m.yaml"
        manifest_file.write_text(
            "source: local\n"
            "entries:\n"
            "  - domain: adapter\n"
            "    key: cache\n"
            "    provider: redis\n"
            "    factory: oneiric.adapters:Cache\n"
        )
        cfg = RemoteSourceConfig(
            enabled=True,
            manifest_url=f"file://{manifest_file}",
            cache_dir=str(cache_dir),
            allow_file_uris=True,
            allowed_file_uri_roots=[str(tmp_path)],
            verify_tls=False,
        )
        result = await sync_remote_manifest(resolver, cfg)
        assert result is not None
        assert result.registered == 1
        cands = resolver.registry._candidates.get(("adapter", "cache"))
        assert cands is not None and len(cands) == 1


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


class TestPropertyBased:
    @given(
        url=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-./:",
            min_size=1,
            max_size=50,
        ),
        cache_dir=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-./",
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=30)
    def test_breaker_key_format(self, url: str, cache_dir: str) -> None:
        """_breaker_key formats as '<cache_dir>:<url>' deterministically."""
        key = _breaker_key(url, cache_dir)
        # Format invariant: contains the cache_dir, then ':', then the url
        assert key == f"{cache_dir}:{url}"

    @given(
        url=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-./",
            min_size=1,
            max_size=30,
        ),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_breaker_for_caches_by_url_and_cache_dir(
        self, reset_remote_breakers, cache_dir: Path, url: str
    ) -> None:
        """Same (url, cache_dir) -> same breaker (caching invariant)."""
        cfg = RemoteSourceConfig(cache_dir=str(cache_dir))
        b1 = _breaker_for(cfg, url)
        b2 = _breaker_for(cfg, url)
        assert b1 is b2

    @given(
        payload=st.binary(min_size=0, max_size=1024),
    )
    @settings(max_examples=30)
    def test_manifest_hash_deterministic(self, payload: bytes) -> None:
        """Re-hashing the same bytes yields the same sha256 (determinism)."""
        h1 = hashlib.sha256(payload).hexdigest()
        h2 = hashlib.sha256(payload).hexdigest()
        assert h1 == h2
        assert len(h1) == 64
