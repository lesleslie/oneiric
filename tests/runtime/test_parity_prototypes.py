"""Parity prototype tests for event dispatcher and DAG executor."""

from __future__ import annotations

import asyncio
from typing import Any

import anyio
import pytest

from oneiric.runtime.dag import (
    DAGExecutionError,
    DAGTask,
    build_graph,
    execute_dag,
    plan_levels,
)
from oneiric.runtime.events import EventDispatcher, EventEnvelope, EventHandler


@pytest.mark.anyio
async def test_event_dispatcher_runs_handlers_concurrently():
    dispatcher = EventDispatcher()
    call_order: list[str] = []

    async def handler_a(event: EventEnvelope) -> str:
        await anyio.sleep(0.05)
        call_order.append(f"a:{event.payload['value']}")
        return "A"

    async def handler_b(event: EventEnvelope) -> str:
        call_order.append(f"b:{event.payload['value']}")
        return "B"

    dispatcher.register(
        EventHandler(name="handler-a", callback=handler_a, topics=("demo.probe",))
    )
    dispatcher.register(EventHandler(name="handler-b", callback=handler_b))

    envelope = EventEnvelope(topic="demo.probe", payload={"value": 1})
    results = await dispatcher.dispatch(envelope)

    assert {result.handler for result in results} == {"handler-a", "handler-b"}
    assert all(result.success for result in results)
    assert call_order[0].startswith("b:")  # handler-b returns immediately


def test_dag_builder_detects_cycles():
    a = DAGTask(key="a", depends_on=("c",))
    b = DAGTask(key="b", depends_on=("a",))
    c = DAGTask(key="c", depends_on=("b",))

    with pytest.raises(ValueError):
        build_graph([a, b, c])


@pytest.mark.anyio
async def test_execute_dag_runs_generations_in_order():
    executed: list[str] = []

    async def make_runner(name: str):
        async def _run() -> str:
            executed.append(name)
            await asyncio.sleep(0)
            return name.upper()

        return _run

    tasks = [
        DAGTask(key="extract", runner=await make_runner("extract")),
        DAGTask(
            key="transform",
            depends_on=("extract",),
            runner=await make_runner("transform"),
        ),
        DAGTask(
            key="load",
            depends_on=("transform",),
            runner=await make_runner("load"),
        ),
    ]
    graph = build_graph(tasks)
    levels = plan_levels(graph)
    assert levels == [["extract"], ["transform"], ["load"]]

    results = await execute_dag(graph)
    assert executed == ["extract", "transform", "load"]
    assert results["extract"] == "EXTRACT"
    assert "extract__duration" in results


@pytest.mark.anyio
async def test_event_dispatcher_retries_handler_successfully():
    dispatcher = EventDispatcher()
    attempt_counter = 0

    async def flaky(event: EventEnvelope) -> str:
        nonlocal attempt_counter
        attempt_counter += 1
        if attempt_counter < 2:
            raise RuntimeError("boom")
        return "ok"

    dispatcher.register(
        EventHandler(
            name="retry-handler",
            callback=flaky,
            retry_policy={
                "attempts": 3,
                "base_delay": 0.01,
                "max_delay": 0.05,
                "jitter": 0.0,
            },
        )
    )
    results = await dispatcher.dispatch(EventEnvelope(topic="demo", payload={}))

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].attempts == 2
    assert results[0].value == "ok"


@pytest.mark.anyio
async def test_event_dispatcher_reports_retry_failure():
    dispatcher = EventDispatcher()

    async def always_fail(event: EventEnvelope) -> str:
        raise RuntimeError("nope")

    dispatcher.register(
        EventHandler(
            name="retry-handler",
            callback=always_fail,
            retry_policy={
                "attempts": 2,
                "base_delay": 0.01,
                "max_delay": 0.02,
                "jitter": 0.0,
            },
        )
    )

    results = await dispatcher.dispatch(EventEnvelope(topic="demo", payload={}))

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].attempts == 2
    assert "nope" in (results[0].error or "")


@pytest.mark.anyio
async def test_event_dispatcher_records_metrics(monkeypatch):
    dispatcher = EventDispatcher()
    recorder: list[dict[str, Any]] = []

    async def handler(event: EventEnvelope) -> str:
        return "ok"

    dispatcher.register(EventHandler(name="metric-handler", callback=handler))

    def _record(**kwargs):
        recorder.append(kwargs)

    monkeypatch.setattr(
        "oneiric.runtime.events.record_event_handler_metrics",
        lambda **kwargs: _record(**kwargs),
    )

    await dispatcher.dispatch(EventEnvelope(topic="demo.metric", payload={}))

    assert recorder
    metric = recorder[0]
    assert metric["handler"] == "metric-handler"
    assert metric["topic"] == "demo.metric"
    assert metric["success"] is True


@pytest.mark.anyio
async def test_execute_dag_uses_checkpoint():
    async def _should_not_run():
        raise AssertionError("runner should have been skipped")

    tasks = [
        DAGTask(
            key="extract",
            runner=_should_not_run,
        )
    ]
    graph = build_graph(tasks)
    checkpoint = {
        "extract": "cached",
        "extract__duration": 0.01,
        "extract__attempts": 1,
    }

    results = await execute_dag(graph, checkpoint=checkpoint)

    assert results["extract"] == "cached"
    assert results["extract__attempts"] == 1


@pytest.mark.anyio
async def test_execute_dag_retries_and_records_attempts():
    attempts = {"extract": 0}

    async def flaky():
        attempts["extract"] += 1
        if attempts["extract"] < 2:
            raise RuntimeError("boom")
        return "ok"

    tasks = [
        DAGTask(
            key="extract",
            runner=flaky,
            retry_policy={
                "attempts": 3,
                "base_delay": 0.01,
                "max_delay": 0.02,
                "jitter": 0.0,
            },
        )
    ]
    graph = build_graph(tasks)
    results = await execute_dag(graph)

    assert results["extract"] == "ok"
    assert results["extract__attempts"] == 2


@pytest.mark.anyio
async def test_execute_dag_raises_after_retry_exhausted():
    async def always_fail():
        raise RuntimeError("boom")

    tasks = [
        DAGTask(
            key="extract",
            runner=always_fail,
            retry_policy={
                "attempts": 2,
                "base_delay": 0.01,
                "max_delay": 0.02,
                "jitter": 0.0,
            },
        )
    ]
    graph = build_graph(tasks)

    with pytest.raises(DAGExecutionError, match="failed after 2 attempt"):
        await execute_dag(graph)


@pytest.mark.anyio
async def test_execute_dag_records_metrics(monkeypatch):
    recorder: list[dict[str, Any]] = []

    async def runner():
        return "ok"

    def _record(**kwargs):
        recorder.append(kwargs)

    monkeypatch.setattr(
        "oneiric.runtime.dag.record_workflow_node_metrics",
        lambda **kwargs: _record(**kwargs),
    )

    tasks = [DAGTask(key="extract", runner=runner)]
    graph = build_graph(tasks)
    await execute_dag(graph, workflow_key="demo-flow")

    assert recorder
    metric = recorder[0]
    assert metric["workflow"] == "demo-flow"
    assert metric["node"] == "extract"
    assert metric["success"] is True
