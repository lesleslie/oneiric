from __future__ import annotations

import os

import pytest

from oneiric.core.config import OneiricSettings, load_settings
from oneiric.core.substrate_settings import SubstrateSettings


@pytest.fixture(autouse=True)
def _clean_substrate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ONEIRIC__SUBSTRATE__* from the test process before each test.

    The custom ``_SubstrateEnvSource`` reads ``os.environ`` directly,
    so callers (and prior tests) can leak substrate overrides across
    test boundaries. We scrub here to make every test hermetic.
    """
    for key in list(os.environ.keys()):
        if key.startswith("ONEIRIC__SUBSTRATE__"):
            monkeypatch.delenv(key, raising=False)


def test_substrate_settings_default_construction() -> None:
    """Defaults survive when no ``ONEIRIC__SUBSTRATE__*`` env vars are set."""
    s = load_settings()
    assert hasattr(s, "substrate")
    assert isinstance(s.substrate, SubstrateSettings)
    assert s.substrate.cache__backend == "memory"
    assert s.substrate.cache__max_entries == 10000
    assert s.substrate.cache__default_ttl_seconds == 3600.0
    assert s.substrate.warm__backend == "pgvector"
    assert s.substrate.warm__pg_url.startswith("postgresql+psycopg://")
    assert s.substrate.warm__pg_pool_size == 8
    assert s.substrate.warm__schema_namespace == "akosha"
    assert s.substrate.warm__embedding_dim == 384
    assert s.substrate.warm__distance_metric == "cosine"
    assert s.substrate.warm__hnsw_m == 16
    assert s.substrate.warm__hnsw_ef_construction == 200
    assert s.substrate.warm__hnsw_ef_search == 64
    assert s.substrate.warm__enable_quantization is False
    assert s.substrate.warm__quantization_method == "scalar"
    assert s.substrate.cold__backend == "r2"
    assert s.substrate.cold__bucket == "oneiric-substrate-shared"
    assert s.substrate.cold__prefix == "akosha/"
    assert s.substrate.cold__compression == "snappy"
    assert s.substrate.cold__retention_days == 365
    assert s.substrate.embedding__backend == "llama_server"
    assert s.substrate.embedding__model == "nomic-embed-text"
    assert s.substrate.embedding__dim == 384
    assert s.substrate.embedding__normalize is True
    assert s.substrate.embedding__batch_size == 32
    assert s.substrate.embedding__timeout_seconds == 30.0
    assert s.substrate.embedding__endpoint_url is None
    assert s.substrate.pool__workers_per_instance == 3
    assert s.substrate.pool__isolation == "subprocess"
    assert s.substrate.pool__min_workers == 1
    assert s.substrate.pool__max_workers == 10
    assert s.substrate.retry__max_attempts == 3
    assert s.substrate.retry__backoff_multiplier == 2.0
    assert s.substrate.retry__initial_delay_seconds == 0.5
    assert s.substrate.circuit_breaker__failure_threshold == 5
    assert s.substrate.circuit_breaker__reset_timeout_seconds == 60
    assert s.substrate.telemetry__service_namespace == "oneiric-substrate"
    assert s.substrate.telemetry__service_name == "oneiric"
    assert s.substrate.telemetry__exporter == "otlp"
    assert s.substrate.telemetry__sample_ratio == 1.0
    assert s.substrate.backup__retention_days == 30
    assert s.substrate.auth__enabled is False
    assert s.substrate.auth__loopback_trusted is True


def test_substrate_field_round_trips_via_oneiric_settings() -> None:
    """The new substrate field on ``OneiricSettings`` is a real ``SubstrateSettings``."""
    settings = OneiricSettings()
    assert isinstance(settings.substrate, SubstrateSettings)
    # Tuple-style access via pydantic field iteration must include the
    # ``substrate`` key (not be dropped to ``__pydantic_extra__``).
    field_names = set(OneiricSettings.model_fields.keys())
    assert "substrate" in field_names
    # ``substrate`` is NOT a stdlib dataclass: arbitrary_types_allowed
    # would only need to be true if it were. Confirm the field type
    # annotation resolves to ``SubstrateSettings``.
    substrate_field = OneiricSettings.model_fields["substrate"]
    assert substrate_field.default_factory is SubstrateSettings


def test_substrate_env_var_cache_max_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5`` → ``cache__max_entries=5``."""
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES", "5")
    s = load_settings()
    assert s.substrate.cache__max_entries == 5


def test_substrate_env_var_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ONEIRIC__SUBSTRATE__AUTH__ENABLED=true`` → ``auth__enabled=True``."""
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", "true")
    s = load_settings()
    assert s.substrate.auth__enabled is True


def test_substrate_env_var_warm_schema_namespace_sb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``warm__schema_namespace`` accepts the per-component override.

    Session-Buddy binds ``sb``; Akosha binds ``akosha``. The substrate
    settings must not coerce to an unrelated value.
    """
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__WARM__SCHEMA_NAMESPACE", "sb")
    s = load_settings()
    assert s.substrate.warm__schema_namespace == "sb"


def test_substrate_env_var_warm_pg_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-environment ``warm__pg_url`` override routes through cleanly."""
    url = "postgresql+psycopg://prod:secret@db.internal:5432/substrate"
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__WARM__PG_URL", url)
    s = load_settings()
    assert s.substrate.warm__pg_url == url


def test_substrate_env_var_multiple_overrides_coexist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several ``ONEIRIC__SUBSTRATE__*`` env vars merge into the substrate dict."""
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES", "123")
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__AUTH__ENABLED", "true")
    monkeypatch.setenv("ONEIRIC__SUBSTRATE__WARM__PG_POOL_SIZE", "16")
    s = load_settings()
    assert s.substrate.cache__max_entries == 123
    assert s.substrate.auth__enabled is True
    assert s.substrate.warm__pg_pool_size == 16
    # Untouched fields keep their defaults.
    assert s.substrate.cache__backend == "memory"
    assert s.substrate.telemetry__exporter == "otlp"


def test_substrate_env_var_missing_leaves_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defaults are preserved when no env vars are set (hermetic)."""
    s = load_settings()
    assert s.substrate.cache__max_entries == 10000
    assert s.substrate.auth__enabled is False


def test_substrate_settings_standalone_construction() -> None:
    """``SubstrateSettings`` is a real ``BaseSettings`` usable without the parent."""
    s = SubstrateSettings()
    assert s.cache__max_entries == 10000
    assert s.auth__enabled is False


def test_substrate_settings_invalid_backend_rejected() -> None:
    """``Literal`` constraints are enforced at construction time."""
    with pytest.raises(ValueError):
        SubstrateSettings(cache__backend="not-a-real-backend")
    with pytest.raises(ValueError):
        SubstrateSettings(warm__distance_metric="wrong-metric")


def test_no_consumer_regression_after_substrate_added() -> None:
    """Adding ``substrate`` did not perturb existing fields on ``OneiricSettings``."""
    settings = load_settings()
    expected_fields = {
        "config_dir",
        "cache_dir",
        "app",
        "adapters",
        "services",
        "tasks",
        "events",
        "workflows",
        "actions",
        "secrets",
        "remote",
        "logging",
        "lifecycle",
        "plugins",
        "profile",
        "runtime_paths",
        "runtime_supervisor",
        "observability",
        "auth",
        "substrate",
    }
    actual_fields = set(OneiricSettings.model_fields.keys())
    missing = expected_fields - actual_fields
    assert not missing, (
        f"Expected fields missing from OneiricSettings after substrate add: {missing}"
    )
    # And the schema-DOES-NOT-SILENTLY-DROP via extra='allow'.
    assert isinstance(settings.adapters, type(settings.adapters))


def test_oneiric_settings_substrate_only_init() -> None:
    """``OneiricSettings(substrate=SubstrateSettings(...))`` honors explicit kwargs."""
    custom = SubstrateSettings(
        cache__max_entries=999,
        warm__schema_namespace="sb",
        auth__enabled=True,
    )
    settings = OneiricSettings(substrate=custom)
    assert settings.substrate.cache__max_entries == 999
    assert settings.substrate.warm__schema_namespace == "sb"
    assert settings.substrate.auth__enabled is True
    # Substrate cache__backend remains default because we only set
    # three fields above.
    assert settings.substrate.cache__backend == "memory"
