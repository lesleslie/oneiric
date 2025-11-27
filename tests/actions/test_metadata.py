from __future__ import annotations

from pathlib import Path

from oneiric.actions.metadata import ActionMetadata, register_action_metadata
from oneiric.core.resolution import CandidateSource, Resolver


def test_action_metadata_to_candidate_includes_fields() -> None:
    metadata = ActionMetadata(
        key="compression.encode",
        provider="builtin",
        factory="pkg.actions:encode",
        domains=["task", "workflow"],
        capabilities=["compress", "encode"],
        stack_level=10,
        priority=200,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        extras={"formats": ["json"]},
    )
    candidate = metadata.to_candidate()
    assert candidate.domain == "action"
    assert candidate.key == "compression.encode"
    assert candidate.provider == "builtin"
    assert candidate.metadata["domains"] == ["task", "workflow"]
    assert candidate.metadata["side_effect_free"] is True


def test_register_action_metadata_registers_candidates(tmp_path) -> None:
    resolver = Resolver()
    metadata = ActionMetadata(
        key="workflow.notify",
        provider="demo",
        factory="demo.actions:notify",
        source=CandidateSource.LOCAL_PKG,
    )
    register_action_metadata(
        resolver,
        package_name="oneiric.actions",
        package_path=str(Path("oneiric/actions")),
        actions=[metadata],
    )
    candidate = resolver.resolve("action", "workflow.notify")
    assert candidate is not None
    assert candidate.provider == "demo"
