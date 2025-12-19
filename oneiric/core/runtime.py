"""Runtime helpers that wrap asyncio.TaskGroup with structured logging."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from typing import Any

import anyio

from .logging import get_logger

CoroutineFactory = Callable[[], Awaitable[Any]]


class TaskGroupError(RuntimeError):
    """Raised when TaskGroup helpers are misused."""


class RuntimeTaskGroup:
    """Wrapper around asyncio.TaskGroup that tracks tasks and logs lifecycle events."""

    def __init__(self, name: str = "oneiric.nursery") -> None:
        self.name = name
        self._logger = get_logger(name)
        self._group: asyncio.TaskGroup | None = None
        self._tasks: list[asyncio.Task[Any]] = []

    async def __aenter__(self) -> RuntimeTaskGroup:
        self._group = asyncio.TaskGroup()
        await self._group.__aenter__()
        self._logger.debug("taskgroup-enter", name=self.name)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        if not self._group:
            return None

        # Call the underlying TaskGroup's __aexit__
        # Note: TaskGroup.__aexit__ returns None, but context managers can return bool
        result: bool | None = await self._group.__aexit__(exc_type, exc, tb)  # type: ignore[func-returns-value]

        # Cleanup logging (always executed after __aexit__)
        self._logger.debug(
            "taskgroup-exit", name=self.name, exc=str(exc) if exc else None
        )
        self._group = None
        self._tasks.clear()

        return result

    def start_soon(
        self,
        coro_or_factory: Awaitable[Any] | CoroutineFactory,
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        if not self._group:
            raise TaskGroupError(
                "TaskGroup not initialized. Use 'async with RuntimeTaskGroup()'."
            )
        if callable(coro_or_factory):
            coro_awaitable = coro_or_factory()
        else:
            coro_awaitable = coro_or_factory

        # Cast Awaitable to Coroutine for TaskGroup compatibility
        if not isinstance(coro_awaitable, Coroutine):

            async def _wrap() -> Any:
                return await coro_awaitable

            coro_coroutine = _wrap()
        else:
            coro_coroutine = coro_awaitable

        task: asyncio.Task[Any] = self._group.create_task(coro_coroutine, name=name)
        self._tasks.append(task)
        self._logger.debug("taskgroup-start", name=self.name, task=task.get_name())
        return task

    async def cancel_all(self) -> None:
        for task in self._tasks.copy():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def results(self) -> list[Any]:
        return [
            task.result()
            for task in self._tasks
            if task.done() and not task.cancelled()
        ]


class AnyioTaskGroup:
    """AnyIO TaskGroup wrapper that adds logging + optional concurrency limits."""

    def __init__(
        self,
        name: str,
        task_group: anyio.abc.TaskGroup,
        cancel_scope: anyio.CancelScope,
        limiter: anyio.CapacityLimiter | None = None,
    ) -> None:
        self.name = name
        self._task_group = task_group
        self._cancel_scope = cancel_scope
        self._limiter = limiter
        self._logger = get_logger(name)

    def start_soon(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        task_name: str | None = None,
    ) -> None:
        async def _runner() -> None:
            label = task_name or func.__name__
            self._logger.debug("taskgroup-task-start", name=self.name, task=label)
            try:
                if self._limiter is None:
                    await func(*args)
                else:
                    async with self._limiter:
                        await func(*args)
            finally:
                self._logger.debug("taskgroup-task-end", name=self.name, task=label)

        self._task_group.start_soon(_runner)

    def cancel(self) -> None:
        self._cancel_scope.cancel()


@asynccontextmanager
async def anyio_nursery(
    name: str = "oneiric.nursery",
    *,
    limit: int | None = None,
    timeout: float | None = None,
    shield: bool = False,
) -> AsyncIterator[AnyioTaskGroup]:
    logger = get_logger(name)
    limiter = anyio.CapacityLimiter(limit) if limit else None
    deadline = math.inf
    if timeout is not None:
        deadline = anyio.current_time() + timeout
    cancel_scope = anyio.CancelScope(deadline=deadline, shield=shield)
    with cancel_scope:
        async with anyio.create_task_group() as task_group:
            logger.debug("taskgroup-enter", name=name)
            try:
                yield AnyioTaskGroup(name, task_group, cancel_scope, limiter)
            finally:
                logger.debug(
                    "taskgroup-exit",
                    name=name,
                    cancelled=cancel_scope.cancel_called,
                )


async def run_with_anyio_taskgroup(
    tasks: Sequence[CoroutineFactory],
    *,
    name: str = "oneiric.nursery",
    limit: int | None = None,
    timeout: float | None = None,
    shield: bool = False,
) -> list[Any]:
    results: list[Any] = [None] * len(tasks)

    async def _runner(index: int, factory: CoroutineFactory) -> None:
        results[index] = await factory()

    async with anyio_nursery(
        name=name, limit=limit, timeout=timeout, shield=shield
    ) as tg:
        for idx, factory in enumerate(tasks):
            tg.start_soon(_runner, idx, factory, task_name=f"{name}.{idx}")

    return results


@asynccontextmanager
async def task_nursery(
    name: str = "oneiric.nursery",
) -> AsyncIterator[RuntimeTaskGroup]:
    group = RuntimeTaskGroup(name=name)
    async with group as active:
        yield active


async def run_with_taskgroup(
    *coroutines: Awaitable[Any], name: str = "oneiric.nursery"
) -> list[Any]:
    async with RuntimeTaskGroup(name=name) as group:
        for idx, coro in enumerate(coroutines):
            group.start_soon(coro, name=f"{name}.{idx}")
    return group.results()


def run_sync(main: Callable[[], Awaitable[Any]]) -> Any:
    """Run an async callable with asyncio.run and install debug logging."""

    logger = get_logger("runtime")
    logger.debug("runtime-start")
    coro_awaitable = main()

    # Cast Awaitable to Coroutine for asyncio.run compatibility
    if not isinstance(coro_awaitable, Coroutine):

        async def _wrap() -> Any:
            return await coro_awaitable

        coro_coroutine = _wrap()
    else:
        coro_coroutine = coro_awaitable

    result: Any = asyncio.run(coro_coroutine)
    logger.debug("runtime-stop")
    return result
