from __future__ import annotations

from pathlib import Path

from oneiric.adapters.metadata import AdapterMetadata, register_adapter_metadata
from oneiric.core.resolution import CandidateSource, Resolver


def test_adapter_metadata_to_candidate_includes_settings_model_and_extras() -> None:
    metadata = AdapterMetadata(
        category="cache",
        provider="redis",
        factory="pkg.adapters:RedisCache",
        capabilities=["kv"],
        owner="platform",
        requires_secrets=True,
        settings_model="pkg.settings:RedisSettings",
        extras={"tier": "shared"},
    )

    candidate = metadata.to_candidate()

    assert candidate.domain == "adapter"
    assert candidate.key == "cache"
    assert candidate.provider == "redis"
    assert candidate.metadata["capabilities"] == ["kv"]
    assert candidate.metadata["settings_model"] == "pkg.settings:RedisSettings"
    assert candidate.metadata["tier"] == "shared"
    assert candidate.metadata["requires_secrets"] is True


def test_register_adapter_metadata_registers_candidates(tmp_path) -> None:
    resolver = Resolver()
    metadata = AdapterMetadata(
        category="queue",
        provider="memory",
        factory=lambda: object(),
        source=CandidateSource.LOCAL_PKG,
    )

    register_adapter_metadata(
        resolver,
        package_name="oneiric.adapters",
        package_path=str(Path("oneiric/adapters")),
        adapters=[metadata],
    )

    candidate = resolver.resolve("adapter", "queue")
    assert candidate is not None
    assert candidate.provider == "memory"
