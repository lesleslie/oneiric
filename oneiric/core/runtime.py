"""Runtime helpers that wrap asyncio.TaskGroup with structured logging."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional

from .logging import get_logger

CoroutineFactory = Callable[[], Awaitable[Any]]


class TaskGroupError(RuntimeError):
    """Raised when TaskGroup helpers are misused."""


class RuntimeTaskGroup:
    """Wrapper around asyncio.TaskGroup that tracks tasks and logs lifecycle events."""

    def __init__(self, name: str = "oneiric.nursery") -> None:
        self.name = name
        self._logger = get_logger(name)
        self._group: Optional[asyncio.TaskGroup] = None
        self._tasks: List[asyncio.Task[Any]] = []

    async def __aenter__(self) -> "RuntimeTaskGroup":
        self._group = asyncio.TaskGroup()
        await self._group.__aenter__()
        self._logger.debug("taskgroup-enter", name=self.name)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> Optional[bool]:
        if not self._group:
            return None
        try:
            return await self._group.__aexit__(exc_type, exc, tb)
        finally:
            self._logger.debug("taskgroup-exit", name=self.name, exc=str(exc) if exc else None)
            self._group = None
            self._tasks.clear()

    def start_soon(
        self,
        coro_or_factory: Awaitable[Any] | CoroutineFactory,
        *,
        name: Optional[str] = None,
    ) -> asyncio.Task[Any]:
        if not self._group:
            raise TaskGroupError("TaskGroup not initialized. Use 'async with RuntimeTaskGroup()'.")
        if callable(coro_or_factory):
            coro = coro_or_factory()
        else:
            coro = coro_or_factory
        task = self._group.create_task(coro, name=name)
        self._tasks.append(task)
        self._logger.debug("taskgroup-start", name=self.name, task=task.get_name())
        return task

    async def cancel_all(self) -> None:
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def results(self) -> List[Any]:
        return [task.result() for task in self._tasks if task.done() and not task.cancelled()]


@asynccontextmanager
async def task_nursery(name: str = "oneiric.nursery") -> AsyncIterator[RuntimeTaskGroup]:
    group = RuntimeTaskGroup(name=name)
    async with group as active:
        yield active


async def run_with_taskgroup(*coroutines: Awaitable[Any], name: str = "oneiric.nursery") -> List[Any]:
    async with RuntimeTaskGroup(name=name) as group:
        for idx, coro in enumerate(coroutines):
            group.start_soon(coro, name=f"{name}.{idx}")
    return group.results()


def run_sync(main: Callable[[], Awaitable[Any]]) -> Any:
    """Run an async callable with asyncio.run and install debug logging."""

    logger = get_logger("runtime")
    logger.debug("runtime-start")
    result = asyncio.run(main())
    logger.debug("runtime-stop")
    return result
