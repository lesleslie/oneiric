"""Load testing helpers for exercising concurrency and throughput."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from pydantic import BaseModel, Field

from oneiric.core.logging import get_logger
from oneiric.core.runtime import anyio_nursery


class LoadTestProfile(BaseModel):
    total_tasks: int = Field(1000, ge=1)
    concurrency: int = Field(50, ge=1)
    warmup_tasks: int = Field(0, ge=0)
    sleep_ms: float = Field(0.0, ge=0.0)
    payload_bytes: int = Field(0, ge=0)
    timeout_seconds: float | None = Field(None, ge=0.0)


class LoadTestResult(BaseModel):
    total_tasks: int
    concurrency: int
    duration_seconds: float
    throughput_per_second: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    errors: int


LoadTestWorkload = Callable[[int, LoadTestProfile, bytes | None], Awaitable[Any]]


async def _default_workload(
    task_id: int, profile: LoadTestProfile, payload: bytes | None
) -> None:
    if payload:
        hashlib.sha256(payload).hexdigest()
    if profile.sleep_ms:
        await anyio.sleep(profile.sleep_ms / 1000)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((percentile / 100) * (len(ordered) - 1)))
    index = max(0, min(index, len(ordered) - 1))
    return ordered[index]


async def _run_tasks(
    total: int,
    profile: LoadTestProfile,
    workload: LoadTestWorkload,
    payload: bytes | None,
    record_latencies: bool,
    latencies: list[float],
    errors: list[int],
) -> None:
    async def _runner(task_id: int) -> None:
        start = time.perf_counter()
        try:
            await workload(task_id, profile, payload)
        except BaseException as exc:
            if isinstance(exc, anyio.get_cancelled_exc_class()):
                raise
            errors[0] += 1
        finally:
            if record_latencies:
                latencies.append(time.perf_counter() - start)

    async with anyio_nursery(
        name="oneiric.loadtest",
        limit=profile.concurrency,
        timeout=profile.timeout_seconds,
    ) as tg:
        for idx in range(total):
            tg.start_soon(_runner, idx, task_name=f"loadtest.{idx}")


async def run_load_test(
    profile: LoadTestProfile,
    workload: LoadTestWorkload | None = None,
) -> LoadTestResult:
    logger = get_logger("load-test")
    workload = workload or _default_workload
    payload = b"x" * profile.payload_bytes if profile.payload_bytes else None
    latencies: list[float] = []
    errors: list[int] = [0]

    if profile.warmup_tasks:
        logger.debug("loadtest-warmup-start", count=profile.warmup_tasks)
        await _run_tasks(
            profile.warmup_tasks,
            profile,
            workload,
            payload,
            record_latencies=False,
            latencies=latencies,
            errors=errors,
        )
        logger.debug("loadtest-warmup-end", count=profile.warmup_tasks)

    start = time.perf_counter()
    await _run_tasks(
        profile.total_tasks,
        profile,
        workload,
        payload,
        record_latencies=True,
        latencies=latencies,
        errors=errors,
    )
    duration = time.perf_counter() - start
    throughput = profile.total_tasks / duration if duration else 0.0
    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0

    return LoadTestResult(
        total_tasks=profile.total_tasks,
        concurrency=profile.concurrency,
        duration_seconds=duration,
        throughput_per_second=throughput,
        avg_latency_ms=avg_latency * 1000,
        p50_latency_ms=_percentile(latencies, 50) * 1000,
        p95_latency_ms=_percentile(latencies, 95) * 1000,
        p99_latency_ms=_percentile(latencies, 99) * 1000,
        errors=errors[0],
    )
