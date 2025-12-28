import anyio
import pytest

from oneiric.core.runtime import (
    RuntimeTaskGroup,
    TaskGroupError,
    anyio_nursery,
    run_sync,
    run_with_anyio_taskgroup,
    run_with_taskgroup,
)


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


@pytest.mark.asyncio
async def test_runtime_taskgroup_rejects_uninitialized_start() -> None:
    group = RuntimeTaskGroup(name="test.group")

    with pytest.raises(TaskGroupError, match="TaskGroup not initialized"):
        group.start_soon(lambda: anyio.sleep(0))


@pytest.mark.asyncio
async def test_run_with_taskgroup_collects_results() -> None:
    async def _make(value: int) -> int:
        await anyio.sleep(0)
        return value

    results = await run_with_taskgroup(_make(1), _make(2), name="test.group")

    assert results == [1, 2]


@pytest.mark.asyncio
async def test_runtime_taskgroup_cancel_all_clears_pending_tasks() -> None:
    async with RuntimeTaskGroup(name="test.group") as group:
        gate = anyio.Event()

        async def _block() -> None:
            await gate.wait()

        group.start_soon(_block(), name="task.blocked")
        await group.cancel_all()

        assert group.results() == []


def test_run_sync_wraps_non_coroutine_awaitable() -> None:
    class DummyAwaitable:
        def __await__(self):
            async def _inner() -> str:
                return "ok"

            return _inner().__await__()

    def _main() -> DummyAwaitable:
        return DummyAwaitable()

    assert run_sync(_main) == "ok"
