"""Tests for oneiric/adapters/tracked_settings.py — TrackedSettings wrapper.

Coverage:
    - TestInit: constructor arguments + default fallbacks
    - TestSetattr: change detection on attribute assignment
    - TestAllowlist: plaintext vs hashed values per adapter allowlist
    - TestHashing: FNV-1a 64-bit collision behavior
    - TestDebouncing: N changes within debounce window collapse to 1 push
    - TestLifecycle: on_startup / on_stop / on_restart fire immediate pushes
    - TestHttpFailure: HTTP failure does NOT raise; logs + caches fallback
    - TestFallbackPermissions: local fallback file mode is 0600
    - TestOTelAttributes: adapter_id emitted as TOP-LEVEL span attribute
    - TestFlushPending: graceful flush on stop
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from unittest.mock import patch

import httpx
import pytest
from pydantic import BaseModel, Field

from oneiric.adapters.tracked_settings import (
    FNV1A_OFFSET,
    FNV1A_PRIME,
    TrackedSettings,
    fnv1a_64,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SampleSettings(BaseModel):
    """Settings model used across the test suite."""

    host: str = "localhost"
    port: int = 5432
    api_key: str = "secret-key-12345"
    public_label: str = "visible"
    feature_flags: list[str] = Field(default_factory=list)


def _make_tracked(
    *,
    allowlist: list[str] | None = None,
    debounce_seconds: float = 0.05,
    dhara_url: str = "http://dhara.test:8683",
    adapter_id: str = "adapter:cache:redis",
    settings: SampleSettings | None = None,
) -> TrackedSettings:
    return TrackedSettings(
        model=settings or SampleSettings(),
        adapter_id=adapter_id,
        dhara_url=dhara_url,
        allowlist=allowlist,
        debounce_seconds=debounce_seconds,
    )


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------


class TestInit:
    def test_stores_model_and_adapter_id(self) -> None:
        s = SampleSettings()
        tracked = _make_tracked(settings=s)
        assert tracked._model is s
        assert tracked._adapter_id == "adapter:cache:redis"

    def test_default_allowlist_is_empty(self) -> None:
        tracked = _make_tracked()
        assert tracked._allowlist == set()

    def test_default_debounce_seconds(self) -> None:
        tracked = _make_tracked()
        assert tracked._debounce_seconds == 0.05

    def test_dhara_url_strips_trailing_slash(self) -> None:
        tracked = _make_tracked(dhara_url="http://dhara.test:8683/")
        assert tracked._dhara_url == "http://dhara.test:8683"

    def test_internal_state_initialised(self) -> None:
        tracked = _make_tracked()
        assert tracked._pending_changes == []
        assert tracked._flush_task is None


# ---------------------------------------------------------------------------
# TestSetattr
# ---------------------------------------------------------------------------


class TestSetattr:
    def test_setattr_to_existing_field_updates_model_and_records_change(self) -> None:
        tracked = _make_tracked()
        tracked.host = "newhost"
        assert tracked._model.host == "newhost"
        assert len(tracked._pending_changes) == 1
        change = tracked._pending_changes[0]
        assert change["key"] == "host"
        assert change["new_value"] == "newhost"

    def test_setattr_with_no_value_change_does_not_record(self) -> None:
        tracked = _make_tracked()
        tracked.host = "localhost"
        assert tracked._pending_changes == []

    def test_setattr_to_internal_underscore_attribute_does_not_record(self) -> None:
        tracked = _make_tracked()
        tracked._private_attr = "internal"
        assert tracked._private_attr == "internal"
        assert tracked._pending_changes == []

    def test_setattr_to_unknown_field_raises_via_pydantic(self) -> None:
        tracked = _make_tracked()
        with pytest.raises(ValueError):
            tracked.this_does_not_exist = "boom"

    def test_sync_setattr_does_not_crash_without_event_loop(self) -> None:
        # When __setattr__ is called from sync code (no running loop), it
        # should still record the change in _pending_changes. The debounced
        # flush is skipped — the next async lifecycle hook will pick it up.
        tracked = _make_tracked()
        tracked.host = "synced"
        assert tracked._model.host == "synced"
        assert len(tracked._pending_changes) == 1


# ---------------------------------------------------------------------------
# TestAllowlist
# ---------------------------------------------------------------------------


class TestAllowlist:
    def test_allowlisted_keys_stored_plaintext(self) -> None:
        tracked = _make_tracked(allowlist=["public_label", "host"])
        snap = tracked._build_snapshot()
        assert snap["public_label"] == "visible"
        assert snap["host"] == "localhost"

    def test_non_allowlisted_keys_are_hashed(self) -> None:
        tracked = _make_tracked(allowlist=["public_label"])
        snap = tracked._build_snapshot()
        assert snap["public_label"] == "visible"
        assert snap["host"] != "localhost"
        assert snap["host"].startswith("fnv1a:")
        assert snap["api_key"] != "secret-key-12345"
        assert snap["api_key"].startswith("fnv1a:")

    def test_allowlist_none_hashes_everything(self) -> None:
        tracked = _make_tracked(allowlist=None)
        snap = tracked._build_snapshot()
        for key in ("host", "port", "api_key", "public_label"):
            assert snap[key].startswith("fnv1a:"), key


# ---------------------------------------------------------------------------
# TestHashing
# ---------------------------------------------------------------------------


class TestHashing:
    def test_fnv1a_64_known_constants(self) -> None:
        assert FNV1A_OFFSET == 0xCBF29CE484222325
        assert FNV1A_PRIME == 0x100000001B3

    def test_fnv1a_64_is_deterministic(self) -> None:
        assert fnv1a_64("hello") == fnv1a_64("hello")

    def test_fnv1a_64_handles_empty_string(self) -> None:
        # Empty string hashes to the FNV offset basis, formatted as 16 hex chars.
        assert fnv1a_64("") == f"{FNV1A_OFFSET:016x}"

    def test_fnv1a_64_produces_hex_string(self) -> None:
        result = fnv1a_64("hello")
        assert isinstance(result, str)
        assert len(result) == 16

    def test_fnv1a_64_distinguishes_similar_inputs(self) -> None:
        assert fnv1a_64("api_key") != fnv1a_64("api-key")

    def test_hash_collision_acceptable_for_low_cardinality_keyspace(self) -> None:
        # 100 distinct values should all hash to distinct outputs
        values = [f"secret-value-{i}" for i in range(100)]
        hashes = {fnv1a_64(v) for v in values}
        assert len(hashes) == 100


# ---------------------------------------------------------------------------
# TestDebouncing
# ---------------------------------------------------------------------------


class TestDebouncing:
    async def test_multiple_changes_within_window_coalesce_to_one_push(
        self,
    ) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            tracked.host = "a"
            tracked.port = 1111
            tracked.public_label = "x"
            await asyncio.sleep(0.12)
            await tracked.flush_pending()

        assert len(posts) == 1, f"expected 1 batched push, got {len(posts)}"
        body = json.loads(posts[0].content)
        assert body["adapter_id"] == "adapter:cache:redis"
        events = body["events"]
        assert len(events) == 3
        keys = {e["key"] for e in events}
        assert keys == {"host", "port", "public_label"}

    async def test_no_changes_means_no_push(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            await asyncio.sleep(0.10)
            await tracked.flush_pending()

        assert posts == []


# ---------------------------------------------------------------------------
# TestLifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_pushes_full_snapshot_immediately(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=["public_label"],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            await tracked.on_startup()

        assert len(posts) == 1
        body = json.loads(posts[0].content)
        assert body["event_type"] == "startup"
        assert body["adapter_id"] == "adapter:cache:redis"
        assert body["config_json"]["public_label"] == "visible"

    async def test_on_stop_pushes_snapshot_with_stop_event_type(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            await tracked.on_stop()

        assert len(posts) == 1
        body = json.loads(posts[0].content)
        assert body["event_type"] == "stop"

    async def test_on_restart_pushes_restart_event_type(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            await tracked.on_restart()

        body = json.loads(posts[0].content)
        assert body["event_type"] == "restart"

    async def test_on_stop_flushes_pending_changes_before_snapshot(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=10.0,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            tracked.host = "pending-host"
            await tracked.on_stop()

        paths = [str(p.url) for p in posts]
        # First the change batch flush, then the stop snapshot
        assert any("/tools/store_config_events" in u for u in paths)
        assert any("/tools/store_config_snapshot" in u for u in paths)


# ---------------------------------------------------------------------------
# TestHttpFailure
# ---------------------------------------------------------------------------


class TestHttpFailure:
    async def test_http_500_does_not_raise_on_lifecycle(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            await tracked.on_startup()

    async def test_network_error_does_not_raise_on_lifecycle(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            await tracked.on_startup()

    async def test_http_failure_writes_fallback_file(self, tmp_path) -> None:
        cache_dir = tmp_path / "cache" / "oneiric" / "pending_snapshots"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with patch(
            "oneiric.adapters.tracked_settings._FALLBACK_DIR",
            cache_dir,
        ):
            async with TrackedSettings(
                model=SampleSettings(),
                adapter_id="adapter:cache:redis",
                dhara_url="http://dhara.test:8683",
                allowlist=[],
                debounce_seconds=0.05,
                client_factory=lambda: httpx.AsyncClient(
                    transport=httpx.MockTransport(handler),
                    base_url="http://dhara.test:8683",
                ),
            ) as tracked:
                await tracked.on_startup()

            assert cache_dir.exists()
            files = list(cache_dir.iterdir())
            assert len(files) == 1
            assert files[0].name.startswith("adapter:cache:redis-")

    async def test_http_failure_during_change_push_does_not_raise(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            tracked.host = "changed"
            await asyncio.sleep(0.10)
            await tracked.flush_pending()


# ---------------------------------------------------------------------------
# TestFallbackPermissions
# ---------------------------------------------------------------------------


class TestFallbackPermissions:
    def test_fallback_directory_default_path(self) -> None:
        from oneiric.adapters.tracked_settings import _FALLBACK_DIR

        assert str(_FALLBACK_DIR).endswith("pending_snapshots")

    def test_fallback_file_written_with_0600_permissions(self, tmp_path) -> None:
        from oneiric.adapters.tracked_settings import (
            _write_fallback_payload,
        )

        cache_dir = tmp_path / "cache"
        payload = {"adapter_id": "adapter:cache:redis", "data": "value"}
        path = _write_fallback_payload(
            cache_dir=cache_dir,
            adapter_id="adapter:cache:redis",
            kind="snapshot",
            payload=payload,
        )
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600


# ---------------------------------------------------------------------------
# TestOTelAttributes
# ---------------------------------------------------------------------------


class TestOTelAttributes:
    async def test_lifecycle_span_emits_adapter_id_as_top_level_attribute(
        self,
    ) -> None:

        captured: dict[str, object] = {}

        class _Span:
            def set_attribute(self, key: str, value: object) -> None:
                captured[key] = value

            def set_attributes(self, attrs: dict[str, object]) -> None:
                for k, v in attrs.items():
                    captured[k] = v

            def __enter__(self) -> _Span:
                return self

            def __exit__(self, *_: object) -> None:
                pass

        class _Tracer:
            def start_as_current_span(self, name: str) -> _Span:
                captured["span_name"] = name
                return _Span()

        fake_tracer = _Tracer()
        with patch(
            "oneiric.adapters.tracked_settings.get_tracer",
            return_value=fake_tracer,
        ):
            posts: list[httpx.Request] = []

            def handler(request: httpx.Request) -> httpx.Response:
                posts.append(request)
                return httpx.Response(200, json={"ok": True})

            async with TrackedSettings(
                model=SampleSettings(),
                adapter_id="adapter:cache:redis",
                dhara_url="http://dhara.test:8683",
                allowlist=[],
                debounce_seconds=0.05,
                client_factory=lambda: httpx.AsyncClient(
                    transport=httpx.MockTransport(handler),
                    base_url="http://dhara.test:8683",
                ),
            ) as tracked:
                await tracked.on_startup()

        # adapter_id MUST be a top-level attribute, not nested under
        # another namespace key
        assert "adapter_id" in captured
        assert captured["adapter_id"] == "adapter:cache:redis"
        assert captured["span_name"] == "tracked_settings.startup"

    async def test_change_event_span_emits_adapter_id_as_top_level_attribute(
        self,
    ) -> None:
        captured: dict[str, object] = {}

        class _Span:
            def set_attribute(self, key: str, value: object) -> None:
                captured[key] = value

            def set_attributes(self, attrs: dict[str, object]) -> None:
                for k, v in attrs.items():
                    captured[k] = v

            def __enter__(self) -> _Span:
                return self

            def __exit__(self, *_: object) -> None:
                pass

        class _Tracer:
            def start_as_current_span(self, name: str) -> _Span:
                captured["span_name"] = name
                return _Span()

        fake_tracer = _Tracer()
        with patch(
            "oneiric.adapters.tracked_settings.get_tracer",
            return_value=fake_tracer,
        ):
            posts: list[httpx.Request] = []

            def handler(request: httpx.Request) -> httpx.Response:
                posts.append(request)
                return httpx.Response(200, json={"ok": True})

            async with TrackedSettings(
                model=SampleSettings(),
                adapter_id="adapter:cache:redis",
                dhara_url="http://dhara.test:8683",
                allowlist=[],
                debounce_seconds=0.05,
                client_factory=lambda: httpx.AsyncClient(
                    transport=httpx.MockTransport(handler),
                    base_url="http://dhara.test:8683",
                ),
            ) as tracked:
                tracked.host = "changed"
                await asyncio.sleep(0.10)
                await tracked.flush_pending()

        assert "adapter_id" in captured
        assert captured["adapter_id"] == "adapter:cache:redis"
        assert captured["span_name"] == "tracked_settings.change_batch"


# ---------------------------------------------------------------------------
# TestFlushPending
# ---------------------------------------------------------------------------


class TestFlushPending:
    async def test_flush_with_no_pending_changes_is_a_noop(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            await tracked.flush_pending()
        assert posts == []

    async def test_flush_pushes_pending_batch(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        async with TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=10.0,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        ) as tracked:
            tracked.host = "x"
            tracked.port = 9999
            await tracked.flush_pending()
            assert tracked._pending_changes == []

        assert len(posts) == 1
        body = json.loads(posts[0].content)
        events = body["events"]
        assert {e["key"] for e in events} == {"host", "port"}


# ---------------------------------------------------------------------------
# TestAsyncContextManager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    async def test_aenter_aexit_closes_client(self) -> None:
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={"ok": True})

        tracked = TrackedSettings(
            model=SampleSettings(),
            adapter_id="adapter:cache:redis",
            dhara_url="http://dhara.test:8683",
            allowlist=[],
            debounce_seconds=0.05,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://dhara.test:8683",
            ),
        )
        async with tracked:
            assert tracked._client is not None
        # Client should be closed after exit; verify is_closed set on httpx
        assert tracked._client.is_closed is True
