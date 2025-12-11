"""Tests for workflow checkpoint store."""

from __future__ import annotations

from oneiric.runtime.checkpoints import WorkflowCheckpointStore


class TestWorkflowCheckpointStore:
    def test_load_save_clear(self, tmp_path):
        store = WorkflowCheckpointStore(tmp_path / "checkpoints.sqlite")
        workflow_key = "demo-workflow"

        # Initially empty
        assert store.load(workflow_key) == {}

        checkpoint = {"extract": "ok", "extract__duration": 0.1}
        store.save(workflow_key, checkpoint)

        loaded = store.load(workflow_key)
        assert loaded == checkpoint

        store.clear(workflow_key)
        assert store.load(workflow_key) == {}
