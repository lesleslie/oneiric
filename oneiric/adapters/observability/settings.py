from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OTelStorageSettings(BaseSettings):
    """pgvector-backed OTLP **storage** settings.

    ``extra="allow"`` because ``observability`` is a key consumers already use
    for their own, unrelated meaning -- Mahavishnu's ``ObservabilityConfig``
    (whether to EXPORT metrics/traces) collides with this model's ``observability``
    (where to STORE telemetry). With pydantic-settings' default
    ``extra="forbid"``, a single unknown nested key raised ValidationError inside
    ``OneiricSettings`` construction, ``load_settings`` propagated it, and the
    consumer's whole layered config was discarded in favour of defaults --
    silently taking unrelated settings (``adapters.hatchet_enabled``,
    ``qc.enabled``) down with it.

    This matches ``OneiricSettings``, which is already ``extra="allow"`` at the
    top level. A permissive parent with a strict child is the inconsistency
    that made the blast radius total rather than local.
    """

    model_config = SettingsConfigDict(extra="allow")

    connection_string: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/otel",
        description="PostgreSQL connection string with pgvector extension",
    )

    embedding_model: str = Field(
        default="all-MiniLM-L6-v2", description="HuggingFace sentence transformer model"
    )
    embedding_dimension: int = Field(
        default=384, ge=128, le=1024, description="Vector embedding dimension"
    )
    cache_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Number of embeddings to cache in memory",
    )

    similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for vector search",
    )

    batch_size: int = Field(
        default=100, ge=10, le=1000, description="Batch size for bulk inserts"
    )
    batch_interval_seconds: int = Field(
        default=5, ge=1, le=60, description="Seconds between batch flushes"
    )

    max_retries: int = Field(
        default=3, ge=1, le=10, description="Max retry attempts for DB operations"
    )
    circuit_breaker_threshold: int = Field(
        default=5, ge=3, le=20, description="Failures before circuit breaker opens"
    )

    @field_validator("connection_string")
    @classmethod
    def validate_connection_string(cls, v: str) -> str:
        if not v.startswith("postgresql://"):
            raise ValueError("Connection string must use postgresql:// scheme")
        return v
