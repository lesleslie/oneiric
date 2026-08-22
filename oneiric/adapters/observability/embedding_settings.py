"""Settings for the hybrid EmbeddingService probe chain.

Defines the per-backend config that ``EmbeddingService`` reads at
``initialize()`` time. Each backend has an ``enabled`` flag plus the
URL/model/timeout fields needed for its probe and encode call.

Env-var mapping follows oneiric's standard layered config:
    oneiric.embeddings.llama_cpp.base_url
    → ONEIRIC__EMBEDDINGS__LLAMA_CPP__BASE_URL
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingSettings(BaseModel):
    """Configuration for the hybrid EmbeddingService backend chain.

    All backends are opt-in via ``enabled: bool``. Backends with
    missing or unreachable dependencies auto-skip during probe (see
    ``EmbeddingService.initialize``). The chain order is fixed by the
    ``EmbeddingService`` implementation; this settings model just
    controls which legs participate.

    Attributes:
        llama_cpp_enabled: Whether to probe llama.cpp server.
        llama_cpp_base_url: llama-server HTTP root (no trailing /v1).
        llama_cpp_model: Embedding model name to request from llama-server.
        llama_cpp_timeout_seconds: Probe + encode timeout.
        ollama_enabled: Whether to probe Ollama.
        ollama_base_url: Ollama HTTP root.
        ollama_model: Embedding model name (e.g. ``nomic-embed-text``).
        ollama_timeout_seconds: Probe + encode timeout.
        minimax_enabled: Whether to probe MiniMax (api.minimax.chat).
        minimax_api_key: Bearer token (usually ``${MINIMAX_API_KEY}``).
        minimax_group_id: Group ID query param (usually ``${MINIMAX_GROUP_ID}``).
        minimax_base_url: MiniMax HTTP root (default ``https://api.minimax.chat/v1``).
        minimax_model: MiniMax embedding model (default ``embo-01``).
        minimax_timeout_seconds: Probe + encode timeout.
        model2vec_enabled: Whether to attempt model2vec (pure-numpy).
        model2vec_model_name: HuggingFace model id (default ``minishlab/potion-base-32M``).
        model2vec_cache_dir: Local directory to cache the model.
        mock_fallback: Whether to allow mock fallback as last resort.
        mock_dimension: Vector dimension for the mock fallback.
    """

    model_config = ConfigDict(extra="ignore")

    # llama.cpp server (preferred local)
    llama_cpp_enabled: bool = True
    llama_cpp_base_url: str = "http://localhost:8080"
    llama_cpp_model: str = "nomic-embed-text"
    llama_cpp_timeout_seconds: int = Field(default=5, ge=1, le=300)

    # Ollama (fallback local)
    ollama_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "nomic-embed-text"
    ollama_timeout_seconds: int = Field(default=10, ge=1, le=300)

    # MiniMax / ZhipuAI (cloud)
    minimax_enabled: bool = True
    minimax_api_key: str | None = None
    minimax_group_id: str | None = None
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "embo-01"
    minimax_timeout_seconds: int = Field(default=30, ge=1, le=300)

    # Model2Vec (pure-numpy offline)
    model2vec_enabled: bool = True
    model2vec_model_name: str = "minishlab/potion-base-32M"
    model2vec_cache_dir: str | None = None

    # Mock fallback
    mock_fallback: bool = True
    mock_dimension: int = Field(default=384, ge=1, le=4096)
