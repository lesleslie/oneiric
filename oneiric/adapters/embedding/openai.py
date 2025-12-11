"""OpenAI embeddings adapter with lifecycle integration."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import (
    EmbeddingBase,
    EmbeddingBaseSettings,
    EmbeddingBatch,
    EmbeddingModel,
    EmbeddingResult,
    EmbeddingUtils,
)


class OpenAIEmbeddingSettings(EmbeddingBaseSettings):
    """OpenAI-specific embedding settings."""

    # OpenAI-specific settings
    organization: str | None = Field(default=None, description="OpenAI organization ID")
    dimensions: int | None = Field(
        default=None,
        description="Embedding dimensions (for v3 models)",
    )
    encoding_format: str = Field(
        default="float",
        description="Encoding format (float or base64)",
    )

    # Rate limiting
    requests_per_minute: int = Field(default=3000)
    tokens_per_minute: int = Field(default=1000000)

    # Override base settings defaults
    model: str = Field(default=EmbeddingModel.TEXT_EMBEDDING_3_SMALL.value)
    batch_size: int = Field(default=100)  # OpenAI supports up to 2048 inputs


class OpenAIEmbeddingAdapter(EmbeddingBase):
    """OpenAI embeddings adapter implementing the lifecycle contract."""

    metadata = AdapterMetadata(
        category="embedding",
        provider="openai",
        factory="oneiric.adapters.embedding.openai:OpenAIEmbeddingAdapter",
        capabilities=[
            "batch_embedding",
            "vector_normalization",
            "text_preprocessing",
            "rate_limiting",
        ],
        stack_level=30,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=True,
        settings_model=OpenAIEmbeddingSettings,
    )

    def __init__(self, settings: OpenAIEmbeddingSettings) -> None:
        super().__init__(settings)
        self._settings: OpenAIEmbeddingSettings = settings
        self._client: Any | None = None
        self._last_request_time = 0.0
        self._logger = get_logger("adapter.embedding.openai").bind(
            domain="adapter",
            key="embedding",
            provider="openai",
        )

    async def init(self) -> None:
        """Initialize OpenAI embeddings adapter."""
        self._logger.info("openai-embedding-adapter-init-start")

        try:
            # Initialize client
            await self._ensure_client()

            # Test with a simple embedding request
            test_result = await self.embed_text("initialization test")
            self._logger.debug(
                "openai-embedding-test-success", dimensions=len(test_result)
            )

            self._logger.info("openai-embedding-adapter-init-success")
        except Exception as exc:
            self._logger.error("openai-embedding-adapter-init-failed", error=str(exc))
            raise LifecycleError(f"openai-embedding-init-failed: {exc}") from exc

    async def _ensure_client(self) -> Any:
        """Ensure OpenAI client is initialized."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise LifecycleError(
                    "openai-import-failed: pip install openai"
                ) from exc

            try:
                self._client = AsyncOpenAI(
                    api_key=self._settings.api_key.get_secret_value()
                    if self._settings.api_key
                    else None,
                    organization=self._settings.organization,
                    base_url=self._settings.base_url,
                    timeout=self._settings.timeout,
                    max_retries=self._settings.max_retries,
                )
                self._logger.debug("openai-client-initialized")
            except Exception as exc:
                raise LifecycleError(f"openai-client-creation-failed: {exc}") from exc

        return self._client

    async def health(self) -> bool:
        """Check if OpenAI embeddings service is healthy."""
        if not self._client:
            return False

        try:
            # Test with a simple embedding request
            await self.embed_text("health check test")
            return True
        except Exception as exc:
            self._logger.warning("openai-embedding-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Cleanup OpenAI embeddings resources."""
        if self._client:
            try:
                await self._client.close()
            except Exception as exc:
                self._logger.warning("openai-cleanup-warning", error=str(exc))
            finally:
                self._client = None

        self._model_cache.clear()
        self._logger.info("openai-embedding-cleanup-complete")

    async def _embed_texts(
        self,
        texts: list[str],
        model: str,
        normalize: bool,
        batch_size: int,
        **kwargs: Any,
    ) -> EmbeddingBatch:
        """Generate embeddings for multiple texts using OpenAI."""
        start_time = time.time()
        client = await self._ensure_client()

        results = []
        total_tokens = 0

        # Process texts in batches
        batches = self._batch_texts(texts, batch_size)

        for batch_texts in batches:
            try:
                await self._apply_rate_limit()

                # Process single batch
                batch_results, batch_tokens = await self._process_embedding_batch(
                    client,
                    batch_texts,
                    model,
                    normalize,
                )

                results.extend(batch_results)
                total_tokens += batch_tokens

                self._logger.debug(
                    "openai-embedding-batch-completed",
                    texts_count=len(batch_texts),
                    model=model,
                )

            except Exception as exc:
                self._logger.exception("openai-embedding-batch-failed", error=str(exc))
                raise LifecycleError(f"openai-embedding-failed: {exc}") from exc

        processing_time = time.time() - start_time

        return EmbeddingBatch(
            results=results,
            total_tokens=total_tokens if total_tokens > 0 else None,
            processing_time=processing_time,
            model=model,
            batch_size=len(results),
        )

    async def _process_embedding_batch(
        self,
        client: Any,
        batch_texts: list[str],
        model: str,
        normalize: bool,
    ) -> tuple[list[EmbeddingResult], int]:
        """Process a single batch of embeddings."""
        # Prepare and execute API request
        request_params = self._prepare_request_params(batch_texts, model)
        response = await client.embeddings.create(**request_params)

        # Process response data
        results = self._extract_embedding_results(
            response,
            batch_texts,
            normalize,
        )

        # Extract token usage
        tokens = (
            response.usage.total_tokens
            if hasattr(response, "usage") and response.usage
            else 0
        )

        return results, tokens

    def _prepare_request_params(
        self,
        batch_texts: list[str],
        model: str,
    ) -> dict[str, Any]:
        """Prepare OpenAI API request parameters."""
        request_params: dict[str, Any] = {
            "input": batch_texts,
            "model": model,
            "encoding_format": self._settings.encoding_format,
        }

        # Add dimensions for v3 models
        if self._settings.dimensions and model.startswith("text-embedding-3"):
            request_params["dimensions"] = self._settings.dimensions

        return request_params

    def _extract_embedding_results(
        self,
        response: Any,
        batch_texts: list[str],
        normalize: bool,
    ) -> list[EmbeddingResult]:
        """Extract embedding results from API response."""
        results = []

        for i, embedding_data in enumerate(response.data):
            embedding = embedding_data.embedding

            # Normalize if requested
            if normalize:
                embedding = self._normalize_vector(
                    embedding,
                    self._settings.normalization,
                )

            result = EmbeddingResult(
                text=batch_texts[i],
                embedding=embedding,
                model=response.model,
                dimensions=len(embedding),
                tokens=None,  # OpenAI doesn't provide token count per text
                metadata={
                    "index": embedding_data.index,
                    "object": embedding_data.object,
                },
            )
            results.append(result)

        return results

    async def _embed_documents(
        self,
        documents: list[str],
        chunk_size: int,
        chunk_overlap: int,
        model: str,
        **kwargs: Any,
    ) -> list[EmbeddingBatch]:
        """Embed large documents with chunking."""
        batches = []

        for document in documents:
            # Split document into chunks
            chunks = self._chunk_text(document, chunk_size, chunk_overlap)

            # Generate embeddings for chunks
            batch = await self._embed_texts(
                chunks,
                model=model,
                normalize=self._settings.normalize_embeddings,
                batch_size=self._settings.batch_size,
                **kwargs,
            )

            # Add document metadata
            for result in batch.results:
                result.metadata.update(
                    {
                        "document_id": hash(document),
                        "is_chunk": True,
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                    },
                )

            batches.append(batch)

        return batches

    async def _compute_similarity(
        self,
        embedding1: list[float],
        embedding2: list[float],
        method: str,
    ) -> float:
        """Compute similarity between two embeddings."""
        if method == "cosine":
            return EmbeddingUtils.cosine_similarity(embedding1, embedding2)
        if method == "euclidean":
            return EmbeddingUtils.euclidean_distance(embedding1, embedding2)
        if method == "dot":
            return EmbeddingUtils.dot_product(embedding1, embedding2)
        if method == "manhattan":
            return EmbeddingUtils.manhattan_distance(embedding1, embedding2)

        raise ValueError(f"Unsupported similarity method: {method}")

    async def _get_model_info(self, model: str) -> dict[str, Any]:
        """Get information about an OpenAI embedding model."""
        model_info: dict[str, Any] = {
            "name": model,
            "provider": "openai",
            "type": "embedding",
        }

        # Add model-specific information
        if model == EmbeddingModel.TEXT_EMBEDDING_3_SMALL.value:
            model_info.update(
                {
                    "max_dimensions": 1536,
                    "default_dimensions": 1536,
                    "max_tokens": 8191,
                    "price_per_1k_tokens": 0.00002,
                    "description": "Most efficient embedding model with good performance",
                },
            )
        elif model == EmbeddingModel.TEXT_EMBEDDING_3_LARGE.value:
            model_info.update(
                {
                    "max_dimensions": 3072,
                    "default_dimensions": 3072,
                    "max_tokens": 8191,
                    "price_per_1k_tokens": 0.00013,
                    "description": "Most powerful embedding model with highest accuracy",
                },
            )
        elif model == EmbeddingModel.TEXT_EMBEDDING_ADA_002.value:
            model_info.update(
                {
                    "max_dimensions": 1536,
                    "default_dimensions": 1536,
                    "max_tokens": 8191,
                    "price_per_1k_tokens": 0.0001,
                    "description": "Legacy embedding model (v2)",
                },
            )

        return model_info

    async def _list_models(self) -> list[dict[str, Any]]:
        """List available OpenAI embedding models."""
        models = [
            EmbeddingModel.TEXT_EMBEDDING_3_SMALL.value,
            EmbeddingModel.TEXT_EMBEDDING_3_LARGE.value,
            EmbeddingModel.TEXT_EMBEDDING_ADA_002.value,
        ]

        return [await self._get_model_info(model) for model in models]

    async def _apply_rate_limit(self) -> None:
        """Apply rate limiting to API requests."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time

        # Simple rate limiting - ensure minimum time between requests
        min_interval = 60.0 / self._settings.requests_per_minute
        if time_since_last < min_interval:
            await asyncio.sleep(min_interval - time_since_last)

        self._last_request_time = time.time()
