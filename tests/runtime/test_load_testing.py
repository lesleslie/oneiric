import pytest

from oneiric.runtime.load_testing import LoadTestProfile, run_load_test


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
