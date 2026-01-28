"""Configuration for OTel storage adapter."""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class OTelStorageSettings(BaseSettings):
    """Settings for OTel storage adapter."""

    # Database connection
    connection_string: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/otel",
        description="PostgreSQL connection string with pgvector extension"
    )

    # Embedding
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="HuggingFace sentence transformer model"
    )
    embedding_dimension: int = Field(
        default=384,
        ge=128,
        le=1024,
        description="Vector embedding dimension"
    )
    cache_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Number of embeddings to cache in memory"
    )

    # Vector search
    similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for vector search"
    )

    # Performance
    batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Batch size for bulk inserts"
    )
    batch_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Seconds between batch flushes"
    )

    # Resilience
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max retry attempts for DB operations"
    )
    circuit_breaker_threshold: int = Field(
        default=5,
        ge=3,
        le=20,
        description="Failures before circuit breaker opens"
    )

    @field_validator("connection_string")
    @classmethod
    def validate_connection_string(cls, v: str) -> str:
        """Ensure connection string uses postgresql:// scheme."""
        if not v.startswith("postgresql://"):
            raise ValueError("Connection string must use postgresql:// scheme")
        return v
