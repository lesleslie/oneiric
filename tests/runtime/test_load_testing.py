from unittest.mock import patch

import anyio
import pytest

from oneiric.runtime.load_testing import (
    LoadTestProfile,
    _default_workload,
    _percentile,
    run_load_test,
)


@pytest.mark.anyio
async def test_run_load_test_returns_metrics() -> None:
    profile = LoadTestProfile(
        total_tasks=5,
        concurrency=2,
        sleep_ms=1.0,
        warmup_tasks=1,
    )
    result = await run_load_test(profile)

    assert result.total_tasks == 5
    assert result.concurrency == 2
    assert result.errors == 0
    assert result.duration_seconds > 0


@pytest.mark.anyio
async def test_run_load_test_handles_payload_and_errors() -> None:
    seen_payload_lengths: list[int | None] = []
    seen_task_ids: list[int] = []

    async def workload(task_id: int, profile: LoadTestProfile, payload: bytes | None):
        seen_task_ids.append(task_id)
        seen_payload_lengths.append(len(payload) if payload is not None else None)
        if task_id == 1:
            raise ValueError("boom")
        await anyio.sleep(0)

    profile = LoadTestProfile(
        total_tasks=3,
        concurrency=2,
        payload_bytes=4,
        warmup_tasks=1,
    )

    result = await run_load_test(profile, workload=workload)

    assert result.total_tasks == 3
    assert result.errors == 1
    assert set(seen_task_ids) == {0, 1, 2}
    assert all(length == 4 for length in seen_payload_lengths)
    assert _percentile([], 95) == 0.0


@pytest.mark.anyio
async def test_default_workload_skips_hash_without_payload() -> None:
    profile = LoadTestProfile(sleep_ms=0.0)

    with patch("oneiric.runtime.load_testing.hashlib.sha256") as mock_sha256:
        await _default_workload(0, profile, None)
        mock_sha256.assert_not_called()


@pytest.mark.anyio
async def test_run_tasks_reraises_cancellation() -> None:
    profile = LoadTestProfile(total_tasks=1, concurrency=1, sleep_ms=0.0)

    class SentinelCancelled(BaseException):
        pass

    async def workload(task_id: int, profile: LoadTestProfile, payload: bytes | None):
        raise SentinelCancelled()

    with patch(
        "oneiric.runtime.load_testing.anyio.get_cancelled_exc_class",
        return_value=SentinelCancelled,
    ):
        with pytest.raises(BaseExceptionGroup) as excinfo:
            await run_load_test(profile, workload=workload)  # type: ignore[arg-type]

    assert any(
        isinstance(exc, SentinelCancelled) for exc in excinfo.value.exceptions
    )


@pytest.mark.anyio
async def test_default_workload_hashes_payload() -> None:
    profile = LoadTestProfile(sleep_ms=0.0)

    with patch("oneiric.runtime.load_testing.hashlib.sha256") as mock_sha256:
        await _default_workload(0, profile, b"payload")

    mock_sha256.assert_called_once_with(b"payload")
