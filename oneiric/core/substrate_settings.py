from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class SubstrateSettings(BaseSettings):
    """Shared Bodai substrate configuration (Phase E1, Plan 2).

    Single Pydantic settings container for the cache/warm/cold/embedding/
    pool/retry/circuit-breaker/telemetry/backup/auth surfaces that all
    Bodai components (Mahavishnu, Akosha, Session-Buddy, Crackerjack,
    Oneiric) bind against.

    Field names use the canonical double-underscore convention
    (``cache__max_entries``, ``warm__pg_url``, etc.) per the substrate
    spec §5.3. Pydantic-settings resolves the env-var form
    ``ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5`` by:

    1. The parent ``OneiricSettings`` (env_prefix ``ONEIRIC_``,
       env_nested_delimiter ``__``) strips the prefix and splits on
       ``__`` → ``['substrate', 'cache__max_entries']``.
    2. The walk enters the ``substrate`` field of the parent and
       delegates the remaining ``cache__max_entries`` tail to this
       model. Because ``SubstrateSettings`` deliberately sets
       ``env_nested_delimiter=None`` (the pydantic-settings default),
       the inner env source treats the tail as a literal field-name
       lookup rather than re-splitting — so ``cache__max_entries`` is
       matched against the field declared here.

    Per-component overrides (e.g. ``MAHAVISHNU__POOL__WORKERS_PER_INSTANCE``)
    still flow through the higher layers documented in
    ``OneiricSettings.settings_customise_sources``.

    See ``docs/plans/2026-10-12-shared-bodai-substrate-phase-e1.md``.
    """

    model_config = {
        # No env_prefix and no env_nested_delimiter — the parent
        # OneiricSettings owns the resolution path
        # (``ONEIRIC__SUBSTRATE__<field>`` is reached via the parent's
        # nested-delimiter walk). When SubstrateSettings is constructed
        # standalone (e.g. in tests), env vars like
        # ``CACHE__MAX_ENTRIES=5`` map directly to field
        # ``cache__max_entries`` because the inner delimiter is None.
    }

    # ---- Cache tier ----------------------------------------------------
    cache__backend: Literal["memory", "redis", "multitier", "persistent_kv"] = Field(
        default="memory",
        description=(
            "Tier-0 hot cache backend. ``memory`` is the in-process "
            "default; ``redis`` shares state across workers; "
            "``multitier`` chains L1+L2; ``persistent_kv`` is the "
            "disk-backed edge case for slow-restart workloads."
        ),
    )
    cache__max_entries: int | None = Field(
        default=10000,
        ge=0,
        description=(
            "Maximum number of entries held by the L1 cache. ``None`` "
            "disables the cap (recommended only for memory tier with "
            "external bounds)."
        ),
    )
    cache__default_ttl_seconds: float | None = Field(
        default=3600.0,
        ge=0.0,
        description=(
            "TTL applied to cache entries that do not declare their "
            "own expiry. ``None`` means entries live until evicted by "
            "policy (LRU)."
        ),
    )

    # ---- Warm tier (pgvector) -----------------------------------------
    warm__backend: Literal["pgvector"] = Field(
        default="pgvector",
        description="Warm-tier backend. Phase E1 ships pgvector only.",
    )
    warm__pg_url: str = Field(
        default="postgresql+psycopg://user:pass@localhost:5432/oneiric_substrate",
        description=(
            "psycopg/SQLAlchemy URL for the warm-tier pgvector instance. "
            "Per-component deploys override this via "
            "``{COMPONENT}__WARM__PG_URL`` or the substrate YAML layer."
        ),
    )
    warm__pg_pool_size: int = Field(
        default=8,
        ge=1,
        le=128,
        description="SQLAlchemy connection pool size for warm-tier reads/writes.",
    )
    warm__schema_namespace: Literal["akosha", "sb"] = Field(
        default="akosha",
        description=(
            "Schema namespace used to isolate per-component collections "
            "inside the shared pgvector database. ``akosha`` is the "
            "default; Session-Buddy overrides to ``sb``."
        ),
    )
    warm__embedding_dim: int = Field(
        default=384,
        ge=64,
        le=4096,
        description=(
            "Embedding vector dimensionality. Must match the embedding "
            "model output; mismatches trigger a hard substrate init "
            "error (REQ-WARM-DIM-001)."
        ),
    )
    warm__distance_metric: Literal["cosine", "l2", "ip"] = Field(
        default="cosine",
        description="Distance metric used by HNSW probes.",
    )
    warm__hnsw_m: int = Field(
        default=16,
        ge=2,
        le=64,
        description=(
            "HNSW ``m`` parameter — max bi-directional links per node. "
            "Higher = better recall, more memory + build time."
        ),
    )
    warm__hnsw_ef_construction: int = Field(
        default=200,
        ge=16,
        le=1024,
        description=(
            "HNSW ``ef_construction`` — candidate list size during "
            "index build. Higher = better recall, slower build."
        ),
    )
    warm__hnsw_ef_search: int = Field(
        default=64,
        ge=1,
        le=1024,
        description=(
            "HNSW ``ef_search`` — candidate list size during query. "
            "Tune against per-query latency budget."
        ),
    )
    warm__enable_quantization: bool = Field(
        default=False,
        description=(
            "Enable half/binary quantization on stored vectors. "
            "Trades recall for ~4-32× storage savings."
        ),
    )
    warm__quantization_method: Literal["scalar", "binary"] = Field(
        default="scalar",
        description=(
            "Quantization method when ``warm__enable_quantization`` is "
            "true. ``scalar`` is uint8; ``binary`` is 1-bit."
        ),
    )

    # ---- Cold tier (object store) -------------------------------------
    cold__backend: Literal["r2", "s3", "gcs", "azure", "local"] = Field(
        default="r2",
        description=(
            "Tier-2 cold-storage backend. Cloudflare R2 is the "
            "Bodai-default; S3/GCS/Azure are interchangeable via the "
            "fsspec protocol layer."
        ),
    )
    cold__bucket: str = Field(
        default="oneiric-substrate-shared",
        description="Cold-tier bucket name (shared across Bodai components).",
    )
    cold__prefix: str = Field(
        default="akosha/",
        description=(
            "Object-key prefix used to isolate per-component cold data. "
            "Akosha uses ``akosha/``; Session-Buddy uses ``sb/``; etc."
        ),
    )
    cold__compression: Literal["snappy", "zstd", "gzip"] = Field(
        default="snappy",
        description=(
            "Compression codec applied at write time. ``snappy`` is "
            "fast + balanced; ``zstd`` is higher ratio, slower; "
            "``gzip`` is universal but slower than snappy."
        ),
    )
    cold__retention_days: int = Field(
        default=365,
        ge=1,
        le=36500,
        description="Days to retain cold-tier objects before lifecycle eviction.",
    )

    # ---- Embedding ----------------------------------------------------
    embedding__backend: Literal["openai", "fastembed", "llama_server"] = (
        Field(
            default="llama_server",
            description=(
                "Embedding-model backend. ``llama_server`` (default) routes "
                "through the local llama.cpp-compatible endpoint; "
                "``openai`` is the cloud-paid tier; ``fastembed`` is "
                "the offline CPU tier."
            ),
        )
    )
    embedding__model: str = Field(
        default="nomic-embed-text",
        description="Embedding-model identifier (provider-specific).",
    )
    embedding__dim: int = Field(
        default=384,
        ge=64,
        le=4096,
        description=(
            "Output dimension. Must equal ``warm__embedding_dim`` for "
            "the warm tier to accept these vectors."
        ),
    )
    embedding__normalize: bool = Field(
        default=True,
        description=(
            "L2-normalize embeddings on return. Required when "
            "``warm__distance_metric='cosine'``."
        ),
    )
    embedding__batch_size: int = Field(
        default=32,
        ge=1,
        le=1024,
        description="Batch size for bulk embedding calls.",
    )
    embedding__timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="Per-batch embedding timeout.",
    )
    embedding__endpoint_url: str | None = Field(
        default=None,
        description=(
            "Override endpoint URL for the ``llama_server`` "
            "backend. Defaults to the per-component local value."
        ),
    )

    # ---- Pool sizing --------------------------------------------------
    pool__workers_per_instance: int = Field(
        default=3,
        ge=1,
        le=64,
        description="Worker count per substrate-touching instance.",
    )
    pool__isolation: Literal["process", "subprocess"] = Field(
        default="subprocess",
        description=(
            "Worker isolation model. ``subprocess`` is the safer "
            "default (separate process tree); ``process`` shares "
            "memory but risks cross-tenant leaks."
        ),
    )
    pool__min_workers: int = Field(
        default=1,
        ge=0,
        le=128,
        description="Floor on warm worker count.",
    )
    pool__max_workers: int = Field(
        default=10,
        ge=1,
        le=512,
        description="Ceiling on worker count under load.",
    )

    # ---- Retry policy -------------------------------------------------
    retry__max_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Max retry attempts for substrate-backed operations.",
    )
    retry__backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Exponential backoff multiplier between attempts.",
    )
    retry__initial_delay_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=60.0,
        description="Initial delay before the first retry.",
    )

    # ---- Circuit breaker ----------------------------------------------
    circuit_breaker__failure_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        description=("Consecutive failures that trip the breaker into the open state."),
    )
    circuit_breaker__reset_timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Seconds the breaker remains open before half-open probing.",
    )

    # ---- Telemetry ----------------------------------------------------
    telemetry__service_namespace: str = Field(
        default="oneiric-substrate",
        description="OTel service.namespace applied to substrate spans.",
    )
    telemetry__service_name: str = Field(
        default="oneiric",
        description=(
            "OTel service.name. Per-component overrides set this to "
            "the component key (``mahavishnu``, ``akosha``, ``sb``, "
            "``crackerjack``)."
        ),
    )
    telemetry__exporter: Literal["otlp", "console", "jaeger"] = Field(
        default="otlp",
        description="OTel exporter type.",
    )
    telemetry__sample_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Head-based sampling ratio for substrate spans.",
    )

    # ---- Backup -------------------------------------------------------
    backup__retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Days of substrate snapshots to retain in backup tier.",
    )

    # ---- Auth (loopback-only default) ---------------------------------
    auth__enabled: bool = Field(
        default=False,
        description=(
            "Enable substrate auth gate. Off by default — the "
            "loopback-trusted path is the Phase E1 escape hatch."
        ),
    )
    auth__loopback_trusted: bool = Field(
        default=True,
        description=(
            "When true, requests from loopback addresses bypass the "
            "auth gate. Set false in shared-tenant deployments."
        ),
    )
