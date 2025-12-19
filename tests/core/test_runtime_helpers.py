import anyio
import pytest

from oneiric.core.runtime import anyio_nursery, run_with_anyio_taskgroup


@pytest.mark.anyio
async def test_anyio_nursery_runs_tasks() -> None:
    results: list[int] = []

    async def _task(value: int) -> None:
        await anyio.sleep(0)
        results.append(value)

    async with anyio_nursery(name="test.nursery", limit=2) as nursery:
        for idx in range(3):
            nursery.start_soon(_task, idx, task_name=f"task.{idx}")

    assert sorted(results) == [0, 1, 2]


@pytest.mark.anyio
async def test_run_with_anyio_taskgroup_returns_ordered_results() -> None:
    async def _make(value: int) -> int:
        await anyio.sleep(0)
        return value

    tasks = [lambda value=idx: _make(value) for idx in range(4)]
    results = await run_with_anyio_taskgroup(tasks, name="test.group", limit=2)

    assert results == [0, 1, 2, 3]
