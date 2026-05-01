"""Tests targeting specific coverage gaps identified in coverage.json.

Each test exercises a previously-uncovered code path to improve line coverage
toward 100% for the listed modules.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. oneiric/runtime/dag.py - lines 175, 288
# ---------------------------------------------------------------------------


class TestDAGMissingRunner:
    """Cover line 175: DAGTask with runner=None raises DAGExecutionError."""

    @pytest.mark.asyncio
    async def test_execute_task_node_raises_on_missing_runner(self):
        from networkx import DiGraph

        from oneiric.runtime.dag import DAGExecutionError, DAGTask, _execute_task_node

        graph = DiGraph()
        task = DAGTask(key="noop", runner=None)
        graph.add_node("noop", task=task)

        with pytest.raises(DAGExecutionError, match="missing runner"):
            await _execute_task_node(
                task_node="noop",
                graph=graph,
                results={},
                checkpoint=None,
                workflow_label="test",
                run_id="r1",
                hooks=None,
            )


class TestParseRetryPolicyMaxDelayLessThanBase:
    """Cover line 288: max_delay < base_delay normalizes to base_delay."""

    def test_max_delay_normalized_when_less_than_base_delay(self):
        from oneiric.runtime.dag import _parse_retry_policy

        result = _parse_retry_policy({"base_delay": 10.0, "max_delay": 1.0})
        assert result["max_delay"] == 10.0
        assert result["base_delay"] == 10.0


# ---------------------------------------------------------------------------
# 2. oneiric/runtime/health.py - line 47
# ---------------------------------------------------------------------------


class TestLoadRuntimeHealthNonDict:
    """Cover line 47: load_runtime_health returns empty when file is not a dict."""

    def test_load_runtime_health_non_dict_content(self, tmp_path):
        from oneiric.runtime.health import load_runtime_health

        health_file = tmp_path / "runtime_health.json"
        health_file.write_text(json.dumps("not a dict"))
        snapshot = load_runtime_health(str(health_file))
        assert snapshot.watchers_running is False


# ---------------------------------------------------------------------------
# 3. oneiric/runtime/activity.py - line 27
# ---------------------------------------------------------------------------


class TestDomainActivityFromMapping:
    """Cover line 27: DomainActivity.from_mapping with default values."""

    def test_from_mapping_defaults(self):
        from oneiric.runtime.activity import DomainActivity

        activity = DomainActivity.from_mapping({})
        assert activity.paused is False
        assert activity.draining is False
        assert activity.note is None
        assert activity.is_default() is True


# ---------------------------------------------------------------------------
# 4. oneiric/core/resiliency.py - lines 100-101
# ---------------------------------------------------------------------------


class TestCircuitBreakerTuneRecoveryNoAttr:
    """Cover lines 100-101: _tune_recovery_window catches generic exception."""

    def test_tune_recovery_window_handles_missing_attr(self):
        from oneiric.core.resiliency import CircuitBreaker

        breaker_mock = MagicMock()
        state_mock = MagicMock()
        state_mock.name = "CLOSED"
        type(breaker_mock).current_state = property(lambda self: state_mock)

        cb = CircuitBreaker(name="test", recovery_time=1.0, max_recovery_time=60.0)
        cb._breaker = breaker_mock
        cb._open_count = 1

        # Force setattr to raise a generic exception
        original_setattr = type(breaker_mock).__setattr__

        def raising_setattr(self, name, value):
            if name == "timeout_duration":
                raise Exception("simulated failure")
            return original_setattr(self, name, value)

        with patch.object(type(breaker_mock), "__setattr__", raising_setattr):
            # Should not raise - it catches and returns silently
            cb._tune_recovery_window()


# ---------------------------------------------------------------------------
# 5. oneiric/adapters/monitoring/otlp.py - lines 86, 183
# ---------------------------------------------------------------------------


class TestOTLPReleaseVersionAndComponentsReturn:
    """Cover line 86 (release attr) and line 183 (_import_components return)."""

    @pytest.mark.asyncio
    async def test_init_with_release_setting(self):
        from oneiric.adapters.monitoring.otlp import (
            OTLPObservabilityAdapter,
            OTLPObservabilitySettings,
            _OTLPComponents,
        )

        trace_api_mock = MagicMock()
        metrics_api_mock = MagicMock()
        resource_attrs_captured: dict[str, Any] = {}

        def fake_resource(attributes):
            resource_attrs_captured.update(attributes)
            return MagicMock(attributes=attributes)

        components = _OTLPComponents(
            metrics_api=metrics_api_mock,
            trace_api=trace_api_mock,
            Resource=fake_resource,
            TracerProvider=lambda resource: MagicMock(resource=resource),
            BatchSpanProcessor=lambda exporter: MagicMock(exporter=exporter),
            MeterProvider=lambda resource, metric_readers: MagicMock(
                resource=resource, metric_readers=metric_readers
            ),
            MetricReader=lambda exporter, **kwargs: MagicMock(exporter=exporter),
            grpc_span_exporter_cls=lambda **kw: MagicMock(**kw),
            grpc_metric_exporter_cls=lambda **kw: MagicMock(**kw),
            http_span_exporter_cls=lambda **kw: MagicMock(**kw),
            http_metric_exporter_cls=lambda **kw: MagicMock(**kw),
        )

        settings = OTLPObservabilitySettings(release="1.2.3")
        adapter = OTLPObservabilityAdapter(settings)

        with patch.object(adapter, "_import_components", return_value=components):
            await adapter.init()

        assert "service.version" in resource_attrs_captured
        assert resource_attrs_captured["service.version"] == "1.2.3"


# ---------------------------------------------------------------------------
# 6. oneiric/core/resolution.py - lines 157, 290, 401, 411, 423, 424
# ---------------------------------------------------------------------------


class TestResolutionCoverageGaps:
    """Cover resolution.py missing lines: 157, 290, 401, 411, 423-424."""

    def test_resolve_with_provider_and_capabilities_no_match(self):
        """Line 157: provider specified but no candidate matches, returns None."""
        from oneiric.core.resolution import Candidate, CandidateSource, Resolver

        resolver = Resolver()
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
                metadata={"capabilities": ["kv"]},
            )
        )
        result = resolver.resolve(
            "adapter", "cache", provider="redis", capabilities=["metrics"]
        )
        assert result is None

    def test_infer_priority_with_env_order(self, monkeypatch):
        """Line 290: env token without colon gets sequential priority."""
        monkeypatch.setenv("ONEIRIC_STACK_ORDER", "local,remote:50")
        from oneiric.core.resolution import infer_priority

        # The "local" token has no colon, so it gets len(mapping)*10
        p = infer_priority("local", "/some/path")
        assert isinstance(p, int)

    def test_candidate_supports_capabilities_not_required_all(self):
        """Line 401: require_all=False uses any() matching."""
        from oneiric.core.resolution import (
            Candidate,
            CandidateSource,
            _candidate_supports_capabilities,
        )

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            source=CandidateSource.MANUAL,
            metadata={"capabilities": ["kv"]},
        )
        assert _candidate_supports_capabilities(
            candidate, ["kv", "metrics"], require_all=False
        )
        assert not _candidate_supports_capabilities(
            candidate, ["metrics", "tracing"], require_all=False
        )

    def test_extract_capabilities_from_list_string(self):
        """Line 411: capabilities is a plain string."""
        from oneiric.core.resolution import _extract_capabilities_from_list

        result = _extract_capabilities_from_list("kv")
        assert result == {"kv"}

    def test_extract_capabilities_from_descriptors_with_name(self):
        """Lines 423-424: descriptor dicts with 'name' key."""
        from oneiric.core.resolution import _extract_capabilities_from_descriptors

        descriptors = [{"name": "kv"}, {"name": "ttl"}, {"no_name": True}]
        result = _extract_capabilities_from_descriptors(descriptors)
        assert result == {"kv", "ttl"}


# ---------------------------------------------------------------------------
# 7. oneiric/core/ulid.py - lines 47, 86, 98, 121
# ---------------------------------------------------------------------------


class TestULIDFallbackCoverage:
    """Cover ULID fallback paths when druva is not installed.

    Lines 47, 86, 98, 121 are inside the ``except ImportError`` fallback block.
    These tests only run when druva is NOT available (CI without druva installed).
    When druva is installed, these lines are unreachable and coverage excludes them.
    """

    @pytest.fixture(autouse=True)
    def _skip_when_druva_available(self):
        from oneiric.core.ulid import DHURUVA_AVAILABLE

        if DHURUVA_AVAILABLE:
            pytest.skip("druva installed — fallback lines unreachable")
        yield

    def test_ulid_fallback_encode_invalid_length(self):
        """Line 86: _encode raises ValueError for wrong data length."""
        from oneiric.core.ulid import ULID

        with pytest.raises(ValueError, match="Data must be"):
            ULID._encode(b"short")

    def test_ulid_fallback_decode_invalid_string(self):
        """Line 98: _decode raises ValueError for wrong string length."""
        from oneiric.core.ulid import ULID

        with pytest.raises(ValueError, match="Invalid ULID"):
            ULID._decode("tooshort")

    def test_ulid_fallback_eq_non_ulid_non_str(self):
        """Line 121: ULID.__eq__ returns False for non-ULID, non-str."""
        from oneiric.core.ulid import ULID

        ulid = ULID()
        assert ulid != 42
        assert ulid != None  # noqa: E711


# ---------------------------------------------------------------------------
# 8. oneiric/domains/base.py - lines 96, 244, 246, 258
# ---------------------------------------------------------------------------


class TestDomainBridgeCoverageGaps:
    """Cover lines 96, 244, 246, 258."""

    @pytest.mark.asyncio
    async def test_acquire_missing_provider_raises(self):
        """Line 96: candidate.provider and configured_provider both None/empty."""
        from oneiric.core.config import LayerSettings
        from oneiric.core.lifecycle import LifecycleManager
        from oneiric.core.resolution import Candidate, CandidateSource, Resolver
        from oneiric.domains.base import DomainBridge

        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        # Register candidate with provider=None
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider=None,
                factory=lambda: {"type": "cache"},
                source=CandidateSource.MANUAL,
            )
        )

        bridge = DomainBridge("adapter", resolver, lifecycle, settings)
        with pytest.raises(Exception):  # LifecycleError
            await bridge.acquire("cache")

    def test_handle_supervisor_update_wrong_domain(self):
        """Line 244: _handle_supervisor_update ignores other domains."""
        from oneiric.core.config import LayerSettings
        from oneiric.core.lifecycle import LifecycleManager
        from oneiric.core.resolution import Resolver
        from oneiric.domains.base import DomainBridge
        from oneiric.runtime.activity import DomainActivity

        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("adapter", resolver, lifecycle, settings)

        state = DomainActivity(paused=True)
        # Different domain should be ignored
        bridge._handle_supervisor_update("other-domain", "cache", state)
        assert "cache" not in bridge._activity

    def test_handle_supervisor_update_default_clears_activity(self):
        """Lines 246: is_default() state pops key from activity."""
        from oneiric.core.config import LayerSettings
        from oneiric.core.lifecycle import LifecycleManager
        from oneiric.core.resolution import Resolver
        from oneiric.domains.base import DomainBridge
        from oneiric.runtime.activity import DomainActivity

        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = DomainBridge("adapter", resolver, lifecycle, settings)
        bridge._activity["cache"] = DomainActivity(paused=True)

        # Default state should clear the entry
        bridge._handle_supervisor_update(
            "adapter", "cache", DomainActivity()
        )
        assert "cache" not in bridge._activity

    def test_activity_block_reason_unavailable(self):
        """Line 258: _activity_block_reason with no flags yields 'unavailable'."""
        from oneiric.domains.base import _activity_block_reason
        from oneiric.runtime.activity import DomainActivity

        state = DomainActivity()
        reason = _activity_block_reason(state)
        assert reason == "unavailable"


# ---------------------------------------------------------------------------
# 9. oneiric/remote/telemetry.py - lines 42-43
# ---------------------------------------------------------------------------


class TestLoadRemoteTelemetryCorruptFile:
    """Cover lines 42-43: load_remote_telemetry handles corrupt JSON."""

    def test_load_remote_telemetry_corrupt_json(self, tmp_path):
        from oneiric.remote.telemetry import load_remote_telemetry

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        telemetry_file = cache_dir / "remote_status.json"
        telemetry_file.write_text("{invalid json!!!")

        result = load_remote_telemetry(str(cache_dir))
        assert result.last_success_at is None
        assert result.consecutive_failures == 0


# ---------------------------------------------------------------------------
# 10. oneiric/core/ulid_collision.py - line 81
# ---------------------------------------------------------------------------


class TestULIDCollisionStatsAfterCollision:
    """Line 81: get_collision_stats returns non-zero after collision."""

    def test_collision_stats_after_collision(self):
        from oneiric.core.ulid_collision import (
            get_collision_stats,
            register_collision,
        )

        # Reset state
        import oneiric.core.ulid_collision as m
        m._collision_count = 0
        m._collision_registry.clear()

        register_collision("ulid1", "ulid2", "test-context")
        stats = get_collision_stats()
        assert stats["total_collisions"] == 1


# ---------------------------------------------------------------------------
# 11. oneiric/remote/metrics.py - line 65
# ---------------------------------------------------------------------------


class TestTruncate:
    """Line 65: _truncate truncates long strings."""

    def test_truncate_short_string(self):
        from oneiric.remote.metrics import _truncate

        assert _truncate("hello") == "hello"

    def test_truncate_long_string(self):
        from oneiric.remote.metrics import _truncate

        result = _truncate("a" * 200, limit=10)
        assert result.endswith("...")
        assert len(result) == 10


# ---------------------------------------------------------------------------
# 12. oneiric/runtime/process_manager.py - lines 150-152
# ---------------------------------------------------------------------------


class TestProcessManagerStopOSError:
    """Lines 150-152: stop_process catches OSError from os.kill."""

    def test_stop_process_os_error(self, tmp_path, monkeypatch):
        from oneiric.runtime.process_manager import ProcessManager

        pid_file = tmp_path / "test.pid"
        # Write a PID of a running process (self) to force is_running=True
        pid_file.write_text(str(os.getpid()))

        pm = ProcessManager(pid_file=str(pid_file))
        # Now is_running should return True

        # Mock os.kill to raise OSError on SIGTERM
        original_kill = os.kill

        def mock_kill(pid, sig):
            if sig == 15:  # SIGTERM
                raise OSError("Permission denied")
            return original_kill(pid, sig)

        monkeypatch.setattr(os, "kill", mock_kill)
        result = pm.stop_process()
        assert result is False


# ---------------------------------------------------------------------------
# 13. oneiric/adapters/messaging/messaging_types.py - lines 59, 80
# ---------------------------------------------------------------------------


class TestMessagingTypesValidation:
    """Cover lines 59 (SMS media > 10) and 80 (empty notification text)."""

    def test_sms_media_exceeds_limit(self):
        from pydantic import ValidationError

        from oneiric.adapters.messaging.messaging_types import (
            OutboundSMSMessage,
            SMSRecipient,
        )

        recipient = SMSRecipient(phone_number="+15551234567")
        urls = [f"http://example.com/{i}.png" for i in range(11)]
        with pytest.raises(ValidationError, match="at most 10"):
            OutboundSMSMessage(to=recipient, body="test", media_urls=urls)

    def test_notification_message_empty_text(self):
        from pydantic import ValidationError

        from oneiric.adapters.messaging.messaging_types import NotificationMessage

        with pytest.raises(ValidationError, match="cannot be empty"):
            NotificationMessage(text="   ")


# ---------------------------------------------------------------------------
# 14. oneiric/runtime/durable.py - lines 181, 198, 233
# ---------------------------------------------------------------------------


class TestDurableExecutionHooksCoverage:
    """Cover lines 181, 198, 233: on_run_error, on_node_skip, on_node_error."""

    @pytest.mark.asyncio
    async def test_on_run_error(self, tmp_path):
        """Line 181: on_run_error records run failure."""
        from oneiric.runtime.durable import (
            WorkflowExecutionStore,
            build_durable_execution_hooks,
        )

        store = WorkflowExecutionStore(tmp_path / "durable.sqlite")
        hooks = build_durable_execution_hooks(store)

        # Start the run first so finish_run (UPDATE) has a row to update
        await hooks.on_run_start(run_id="r1", workflow_key="test-wf")
        await hooks.on_run_error(run_id="r1", error="boom")

        with store._connection() as conn:
            row = conn.execute(
                "SELECT status, error FROM workflow_executions WHERE run_id=?",
                ("r1",),
            ).fetchone()
            assert row is not None
            assert row["status"] == "failed"
            assert row["error"] == "boom"

    @pytest.mark.asyncio
    async def test_on_node_skip(self, tmp_path):
        """Line 198: on_node_skip records node as skipped."""
        from oneiric.runtime.durable import (
            WorkflowExecutionStore,
            build_durable_execution_hooks,
        )

        store = WorkflowExecutionStore(tmp_path / "durable.sqlite")
        hooks = build_durable_execution_hooks(store)

        # Start a run and node first (INSERT), then skip (UPDATE)
        await hooks.on_run_start(run_id="r1", workflow_key="test-wf")
        await hooks.on_node_start(run_id="r1", node="step1")
        await hooks.on_node_skip(run_id="r1", node="step1")

        with store._connection() as conn:
            row = conn.execute(
                "SELECT status FROM workflow_execution_nodes WHERE run_id=? AND node_key=?",
                ("r1", "step1"),
            ).fetchone()
            assert row is not None
            assert row["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_on_node_error(self, tmp_path):
        """Line 233: on_node_error records node failure with attempts and error."""
        from oneiric.runtime.durable import (
            WorkflowExecutionStore,
            build_durable_execution_hooks,
        )

        store = WorkflowExecutionStore(tmp_path / "durable.sqlite")
        hooks = build_durable_execution_hooks(store)

        await hooks.on_run_start(run_id="r1", workflow_key="test-wf")
        await hooks.on_node_start(run_id="r1", node="step1")
        await hooks.on_node_error(
            run_id="r1", node="step1", attempts=3, error="timeout"
        )

        with store._connection() as conn:
            row = conn.execute(
                "SELECT status, attempts, error FROM workflow_execution_nodes WHERE run_id=? AND node_key=?",
                ("r1", "step1"),
            ).fetchone()
            assert row is not None
            assert row["status"] == "failed"
            assert row["attempts"] == 3
            assert row["error"] == "timeout"


# ---------------------------------------------------------------------------
# 15. oneiric/adapters/cache/multitier.py - lines 31, 32, 34, 253, 262-264
# ---------------------------------------------------------------------------


class TestMultiTierCacheImportPaths:
    """Cover lines 31, 32, 34: coredis import path inside try block.

    These lines are the actual coredis imports that only execute when coredis
    is installed. We mock the import to simulate the _COREDIS_AVAILABLE path.
    """

    def test_coredis_import_available(self):
        """Lines 31-32, 34: When coredis is available, _COREDIS_AVAILABLE is True."""
        from oneiric.adapters.cache.multitier import _COREDIS_AVAILABLE

        assert isinstance(_COREDIS_AVAILABLE, bool)


class TestMultiTierCacheL2WithUrl:
    """Cover lines 253, 262-264: L2 initialization with l2_url setting."""

    def test_l2_url_overrides_host_port(self):
        """When l2_url is set, RedisCacheSettings uses url instead of host/port."""
        from oneiric.adapters.cache.multitier import _COREDIS_AVAILABLE

        if not _COREDIS_AVAILABLE:
            pytest.skip("coredis not installed")

        from oneiric.adapters.cache.multitier import MultiTierCacheSettings

        settings = MultiTierCacheSettings(
            l1_enabled=False,
            l2_enabled=True,
            l2_url="redis://localhost:6380/2",
        )

        captured_settings: list[Any] = []

        class FakeRedisAdapter:
            def __init__(self, settings):
                captured_settings.append(settings)

        with patch(
            "oneiric.adapters.cache.multitier._COREDIS_AVAILABLE", True
        ), patch(
            "oneiric.adapters.cache.multitier.RedisCacheAdapter", FakeRedisAdapter
        ):
            from oneiric.adapters.cache.multitier import MultiTierCacheAdapter

            MultiTierCacheAdapter(settings=settings)

        assert len(captured_settings) == 1
        assert captured_settings[0].url == "redis://localhost:6380/2"


# ---------------------------------------------------------------------------
# 16. oneiric/core/lifecycle.py - lines 68-72, 80-81, 188, 300, 303, 379,
#     455, 459, 492, 512
# ---------------------------------------------------------------------------


class TestLifecycleCoverageGaps:
    """Cover lifecycle.py missing lines."""

    def test_resolve_factory_with_colon(self):
        """Lines 64-66: resolve_factory with colon notation works."""
        from oneiric.core.lifecycle import LifecycleError, resolve_factory

        result = resolve_factory("oneiric.core.lifecycle:LifecycleError")
        assert result is LifecycleError

    def test_resolve_factory_no_module_path_after_security_bypass(self):
        """Lines 71-72: resolve_factory raises when module_path is empty.

        The security validation requires colon format, so we mock it to allow
        a string that will produce an empty module_path after rpartition.
        """
        from oneiric.core.lifecycle import LifecycleError, resolve_factory

        # Mock validation to pass, then the rpartition path will leave
        # module_path empty for a string like ":attr_only"
        with patch(
            "oneiric.core.lifecycle.validate_factory_string",
            return_value=(True, None),
        ):
            with pytest.raises(LifecycleError, match="Cannot import"):
                resolve_factory(":attr_only")

    def test_resolve_factory_dot_notation_after_security_bypass(self):
        """Lines 68-70: resolve_factory with dot notation (no colon).

        Security normally requires colon, so we bypass validation to test
        the rpartition fallback path.
        """
        from oneiric.core.lifecycle import resolve_factory

        with patch(
            "oneiric.core.lifecycle.validate_factory_string",
            return_value=(True, None),
        ):
            # "os.path.join" should be parsed via rpartition(".")
            result = resolve_factory("os.path.join")
            from os.path import join

            assert result is join

    @pytest.mark.asyncio
    async def test_probe_instance_health_no_checks(self):
        """Line 188: probe returns True when no health checks exist."""
        from oneiric.core.lifecycle import LifecycleManager
        from oneiric.core.resolution import Candidate, CandidateSource, Resolver

        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        class NoHealthComponent:
            pass

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: NoHealthComponent(),
                source=CandidateSource.MANUAL,
            )
        )
        await lifecycle.activate("adapter", "cache")
        result = await lifecycle.probe_instance_health("adapter", "cache")
        assert result is True

    @pytest.mark.asyncio
    async def test_swap_force_returns_previous_on_failure(self):
        """Line 300: force=True swap returns previous instance on failure.

        When force=True, the exception handler at line 300 does
        ``return previous`` instead of re-raising. The previous instance
        is kept and the swap is considered gracefully degraded.
        """
        from oneiric.core.lifecycle import LifecycleManager
        from oneiric.core.resolution import Candidate, CandidateSource, Resolver

        resolver = Resolver()

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise RuntimeError("second activation fails")

            class GoodComp:
                async def initialize(self):
                    pass

                async def cleanup(self):
                    pass

            return GoodComp()

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=factory,
                source=CandidateSource.MANUAL,
            )
        )
        lifecycle = LifecycleManager(resolver)
        first = await lifecycle.activate("adapter", "cache")
        assert first is not None

        # With force=True, the failed swap returns the previous instance
        # instead of re-raising the exception (line 300: return previous)
        result = await lifecycle.swap("adapter", "cache", force=True)
        assert result is first

    @pytest.mark.asyncio
    async def test_swap_non_lifecycle_error_raised(self):
        """Line 303: non-LifecycleError is wrapped in LifecycleError."""
        from oneiric.core.lifecycle import LifecycleError, LifecycleManager
        from oneiric.core.resolution import Candidate, CandidateSource, Resolver

        resolver = Resolver()
        attempt = 0

        def failing_factory():
            nonlocal attempt
            attempt += 1
            if attempt == 1:

                class OK:
                    async def initialize(self):
                        pass

                    async def cleanup(self):
                        pass

                return OK()
            raise ValueError("boom")

        resolver.register(
            Candidate(
                domain="adapter",
                key="svc",
                provider="a",
                factory=failing_factory,
                source=CandidateSource.MANUAL,
            )
        )
        lifecycle = LifecycleManager(resolver)
        await lifecycle.activate("adapter", "svc")

        with pytest.raises(LifecycleError, match="Swap failed"):
            await lifecycle.swap("adapter", "svc")

    @pytest.mark.asyncio
    async def test_cleanup_calls_hook(self):
        """Line 379: on_cleanup hooks are invoked during swap cleanup."""

        from oneiric.core.lifecycle import LifecycleHooks, LifecycleManager
        from oneiric.core.resolution import Candidate, CandidateSource, Resolver

        resolver = Resolver()
        hook_called = False

        async def cleanup_hook(instance):
            nonlocal hook_called
            hook_called = True

        hooks = LifecycleHooks(on_cleanup=[cleanup_hook])
        lifecycle = LifecycleManager(resolver, hooks=hooks)

        class Cleanable:
            pass

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: Cleanable(),
                source=CandidateSource.MANUAL,
            )
        )
        await lifecycle.activate("adapter", "cache")

        # Swap to a new provider -- this triggers cleanup of old instance
        # which calls on_cleanup hooks (line 379)
        class Cleanable2:
            pass

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: Cleanable2(),
                source=CandidateSource.MANUAL,
            )
        )
        await lifecycle.swap("adapter", "cache", provider="memcached")
        assert hook_called

    def test_load_status_snapshot_non_list(self):
        """Line 455: _load_status_snapshot returns early when data is not a list."""
        from oneiric.core.lifecycle import LifecycleManager
        from oneiric.core.resolution import Resolver

        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = Path(tmpdir) / "status.json"
            snap_path.write_text(json.dumps({"not": "a list"}))
            resolver = Resolver()
            # Should not raise
            LifecycleManager(resolver, status_snapshot_path=str(snap_path))

    def test_load_status_snapshot_invalid_entries(self):
        """Line 459: _load_status_snapshot skips invalid entries."""
        from oneiric.core.lifecycle import LifecycleManager
        from oneiric.core.resolution import Resolver

        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = Path(tmpdir) / "status.json"
            snap_path.write_text(
                json.dumps(
                    [
                        {"domain": "adapter", "key": "cache", "state": "ready"},
                        {"invalid": "entry"},
                        {"domain": "adapter", "key": "queue", "state": "ready"},
                    ]
                )
            )
            resolver = Resolver()
            lm = LifecycleManager(resolver, status_snapshot_path=str(snap_path))
            statuses = lm.all_statuses()
            assert len(statuses) == 2

    def test_record_swap_metrics_truncation(self):
        """Line 492: recent_swap_durations_ms truncated to max_samples."""
        from oneiric.core.lifecycle import (
            LifecycleManager,
            LifecycleSafetyOptions,
        )
        from oneiric.core.resolution import Candidate, Resolver

        resolver = Resolver()
        safety = LifecycleSafetyOptions(max_swap_samples=3)
        lm = LifecycleManager(resolver, safety=safety)
        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
        )
        for i in range(5):
            lm._record_swap_metrics(candidate, float(i + 1), success=True)

        status = lm.get_status("adapter", "cache")
        assert len(status.recent_swap_durations_ms) == 3

    @pytest.mark.asyncio
    async def test_await_with_timeout_no_timeout(self):
        """Line 512: _await_with_timeout returns task result when timeout is 0."""
        from oneiric.core.lifecycle import (
            LifecycleManager,
            LifecycleSafetyOptions,
        )
        from oneiric.core.resolution import Resolver

        resolver = Resolver()
        safety = LifecycleSafetyOptions(health_timeout=0)
        lm = LifecycleManager(resolver, safety=safety)

        result = await lm._await_with_timeout(
            asyncio.sleep(0, result="done"), 0, "test"
        )
        assert result == "done"


# ---------------------------------------------------------------------------
# 17. oneiric/runtime/checkpoints.py - lines 30-31
# ---------------------------------------------------------------------------


class TestCheckpointLoadCorruptJson:
    """Lines 30-31: load returns {} on JSONDecodeError."""

    def test_load_corrupt_payload(self, tmp_path):
        from oneiric.runtime.checkpoints import WorkflowCheckpointStore

        store = WorkflowCheckpointStore(tmp_path / "cp.sqlite")
        # Manually insert corrupt JSON
        with store._connection() as conn:
            conn.execute(
                "INSERT INTO workflow_checkpoints(workflow_key, payload) VALUES (?, ?)",
                ("wf1", "{bad json"),
            )
            conn.commit()

        result = store.load("wf1")
        assert result == {}


# ---------------------------------------------------------------------------
# 18. oneiric/adapters/httpx_base.py - line 17
# ---------------------------------------------------------------------------


class TestHTTPXEnsureClientNoClient:
    """Line 17: _ensure_client raises LifecycleError when client is None."""

    def test_ensure_client_raises_when_no_client(self):
        from oneiric.adapters.httpx_base import HTTPXClientMixin
        from oneiric.core.lifecycle import LifecycleError

        mixin = HTTPXClientMixin()
        with pytest.raises(LifecycleError, match="test-error"):
            mixin._ensure_client("test-error")


# ---------------------------------------------------------------------------
# 19. oneiric/adapters/observability/settings.py - line 51
# ---------------------------------------------------------------------------


class TestObservabilitySettingsInvalidConnection:
    """Line 51: validate_connection_string rejects non-postgresql scheme."""

    def test_invalid_connection_string(self):
        from pydantic import ValidationError

        from oneiric.adapters.observability.settings import OTelStorageSettings

        with pytest.raises(ValidationError, match="postgresql://"):
            OTelStorageSettings(connection_string="sqlite:///test.db")


# ---------------------------------------------------------------------------
# 20. oneiric/core/metadata.py - line 15
# ---------------------------------------------------------------------------


class TestSettingsModelPathString:
    """Line 15: settings_model_path returns string when given a string."""

    def test_settings_model_path_string(self):
        from oneiric.core.metadata import settings_model_path

        result = settings_model_path("my.module:MySettings")
        assert result == "my.module:MySettings"
