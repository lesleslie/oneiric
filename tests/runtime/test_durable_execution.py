import pytest

from oneiric.runtime.dag import DAGTask, build_graph, execute_dag
from oneiric.runtime.durable import (
    WorkflowExecutionStore,
    build_durable_execution_hooks,
)


@pytest.mark.anyio
async def test_durable_execution_hooks_record_run(tmp_path) -> None:
    store = WorkflowExecutionStore(tmp_path / "durable.sqlite")
    hooks = build_durable_execution_hooks(store)

    async def _task() -> str:
        return "ok"

    graph = build_graph([DAGTask(key="step-1", runner=_task)])
    run_id = "run-123"
    run_result = await execute_dag(
        graph, workflow_key="demo", run_id=run_id, hooks=hooks
    )

    assert run_result["run_id"] == run_id
    assert run_result["results"]["step-1"] == "ok"
    run = store.load_run(run_id)
    nodes = store.load_nodes(run_id)
    assert run is not None
    assert run["workflow_key"] == "demo"
    assert run["status"] == "completed"
    assert nodes[0]["node_key"] == "step-1"
    assert nodes[0]["status"] == "completed"
