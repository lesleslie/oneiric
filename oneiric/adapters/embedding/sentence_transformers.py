"""Sentence Transformers embeddings adapter with lifecycle integration."""

from __future__ import annotations

import asyncio
import importlib.util
import time
from operator import itemgetter
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

# Check if sentence-transformers is available
_sentence_transformers_available = (
    importlib.util.find_spec("sentence_transformers") is not None
)


class SentenceTransformersSettings(EmbeddingBaseSettings):
    """Sentence Transformers-specific embedding settings."""

    # Model configuration
    device: str = Field(
        default="auto",
        description="Device to run model on (cpu, cuda, auto)",
    )
    cache_folder: str | None = Field(
        default=None,
        description="Model cache directory",
    )
    use_auth_token: str | None = Field(default=None)
    revision: str | None = Field(default=None)
    trust_remote_code: bool = Field(default=False)

    # Model optimization
    convert_to_numpy: bool = Field(default=True)
    convert_to_tensor: bool = Field(default=False)
    show_progress_bar: bool = Field(default=False)
    precision: str = Field(
        default="float32",
        description="Model precision (float32, float16)",
    )

    # Edge optimization
    enable_quantization: bool = Field(default=False)
    memory_efficient: bool = Field(default=True)

    # Override base settings defaults
    model: str = Field(default=EmbeddingModel.ALL_MINILM_L6_V2.value)
    batch_size: int = Field(default=32)


class SentenceTransformersAdapter(EmbeddingBase):
    """Sentence Transformers embeddings adapter implementing the lifecycle contract."""

    metadata = AdapterMetadata(
        category="embedding",
        provider="sentence_transformers",
        factory="oneiric.adapters.embedding.sentence_transformers:SentenceTransformersAdapter",
        capabilities=[
            "batch_embedding",
            "edge_optimized",
            "semantic_search",
            "similarity_computation",
            "pooling_strategies",
            "memory_efficient_processing",
            "on_device",
        ],
        stack_level=30,
        priority=400,  # Lower priority than OpenAI (500) - open-source alternative
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=False,  # No API key required - runs locally
        settings_model=SentenceTransformersSettings,
    )

    def __init__(self, settings: SentenceTransformersSettings) -> None:
        super().__init__(settings)
        self._settings: SentenceTransformersSettings = settings
        self._model: Any | None = None
        self._device: str | None = None
        self._logger = get_logger("adapter.embedding.sentence_transformers").bind(
            domain="adapter",
            key="embedding",
            provider="sentence_transformers",
        )

    async def init(self) -> None:
        """Initialize Sentence Transformers adapter."""
        self._logger.info("sentence-transformers-adapter-init-start")

        if not _sentence_transformers_available:
            raise LifecycleError(
                "sentence-transformers-import-failed: pip install sentence-transformers torch"
            )

        try:
            # Load model
            await self._load_model()

            # Test with a simple embedding request
            test_result = await self.embed_text("initialization test")
            self._logger.debug(
                "sentence-transformers-test-success",
                dimensions=len(test_result),
                device=self._device,
            )

            self._logger.info("sentence-transformers-adapter-init-success")
        except Exception as exc:
            self._logger.error(
                "sentence-transformers-adapter-init-failed", error=str(exc)
            )
            raise LifecycleError(f"sentence-transformers-init-failed: {exc}") from exc

    async def _load_model(self) -> None:
        """Load the Sentence Transformer model."""
        try:
            import importlib

            torch = importlib.import_module("torch")
            st_mod = importlib.import_module("sentence_transformers")
            STClass = st_mod.SentenceTransformer

            # Determine device
            if self._settings.device == "auto":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._device = self._settings.device

            self._logger.info(
                "loading-sentence-transformer-model",
                model=self._settings.model,
                device=self._device,
            )

            # Build model kwargs
            model_kwargs = {
                "device": self._device,
                "cache_folder": self._settings.cache_folder,
                "use_auth_token": self._settings.use_auth_token,
                "revision": self._settings.revision,
                "trust_remote_code": self._settings.trust_remote_code,
            }

            # Remove None values
            model_kwargs = {k: v for k, v in model_kwargs.items() if v is not None}

            # Load model in executor to avoid blocking
            self._model = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: STClass(self._settings.model, **model_kwargs),
            )

            # Apply optimizations
            if self._settings.precision == "float16" and self._device == "cuda":
                self._model.half()

            self._logger.info(
                "sentence-transformer-model-loaded",
                model=self._settings.model,
                device=self._device,
            )

        except Exception as exc:
            self._logger.exception("sentence-transformer-load-failed", error=str(exc))
            raise LifecycleError(f"model-load-failed: {exc}") from exc

    async def _ensure_client(self) -> Any:
        """Ensure Sentence Transformer model is loaded."""
        if self._model is None:
            await self._load_model()
        return self._model

    async def health(self) -> bool:
        """Check if Sentence Transformers service is healthy."""
        if not self._model:
            return False

        try:
            # Test with a simple embedding request
            await self.embed_text("health check test")
            return True
        except Exception as exc:
            self._logger.warning(
                "sentence-transformers-health-check-failed", error=str(exc)
            )
            return False

    async def cleanup(self) -> None:
        """Cleanup Sentence Transformers resources."""
        if self._model is not None:
            try:
                del self._model
                self._model = None

                # Clear CUDA cache if using GPU
                from contextlib import suppress

                with suppress(Exception):
                    import importlib

                    torch = importlib.import_module("torch")
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

            except Exception as exc:
                self._logger.warning(
                    "sentence-transformers-cleanup-warning", error=str(exc)
                )

        self._model_cache.clear()
        self._logger.info("sentence-transformers-cleanup-complete")

    async def _embed_texts(
        self,
        texts: list[str],
        model: str,
        normalize: bool,
        batch_size: int,
        **kwargs: Any,
    ) -> EmbeddingBatch:
        """Generate embeddings for multiple texts using Sentence Transformers."""
        start_time = time.time()
        model_obj = await self._ensure_client()

        try:
            # Generate embeddings in executor to avoid blocking
            embeddings = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model_obj.encode(
                    texts,
                    batch_size=batch_size,
                    show_progress_bar=self._settings.show_progress_bar,
                    normalize_embeddings=normalize,
                    convert_to_numpy=self._settings.convert_to_numpy,
                    convert_to_tensor=self._settings.convert_to_tensor,
                ),
            )

            # Convert to list format if numpy
            if hasattr(embeddings, "tolist"):
                embeddings_list = embeddings.tolist()
            else:
                embeddings_list = embeddings

            # Create results
            results = []
            for i, (text, embedding) in enumerate(
                zip(texts, embeddings_list, strict=False)
            ):
                result = EmbeddingResult(
                    text=text,
                    embedding=embedding,
                    model=model,
                    dimensions=len(embedding),
                    tokens=None,  # Sentence Transformers doesn't provide token count
                    metadata={
                        "device": self._device,
                        "precision": self._settings.precision,
                        "normalized": normalize,
                        "index": i,
                    },
                )
                results.append(result)

            processing_time = time.time() - start_time

            self._logger.debug(
                "sentence-transformers-embedding-batch-completed",
                texts_count=len(texts),
                model=model,
                processing_time=processing_time,
            )

            return EmbeddingBatch(
                results=results,
                total_tokens=None,  # Not available for local models
                processing_time=processing_time,
                model=model,
                batch_size=len(results),
            )

        except Exception as exc:
            self._logger.exception(
                "sentence-transformers-embedding-failed", error=str(exc)
            )
            raise LifecycleError(
                f"sentence-transformers-embedding-failed: {exc}"
            ) from exc

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

    async def similarity_search(
        self,
        query: str,
        documents: list[str],
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Perform semantic similarity search using the model's built-in capabilities."""
        model_obj = await self._ensure_client()

        # Generate embeddings
        query_embedding = await self.embed_text(query)
        doc_embeddings = await self.embed_texts(documents)

        # Compute similarities using Sentence Transformers utilities
        similarities = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: model_obj.similarity(
                [query_embedding],
                [result.embedding for result in doc_embeddings.results],
            ),
        )

        # Get top-k results
        if hasattr(similarities, "tolist"):
            similarities = similarities.tolist()[0]
        else:
            similarities = similarities[0]

        # Sort by similarity (descending)
        results = list(zip(documents, similarities, strict=False))
        results.sort(key=itemgetter(1), reverse=True)

        return results[:top_k]

    async def _get_model_info(self, model: str) -> dict[str, Any]:
        """Get information about a Sentence Transformer model."""
        model_info: dict[str, Any] = {
            "name": model,
            "provider": "sentence_transformers",
            "type": "embedding",
            "device": self._device,
            "local": True,
            "requires_api_key": False,
        }

        if self._model:
            from contextlib import suppress

            with suppress(Exception):
                model_info.update(
                    {
                        "max_seq_length": self._model.max_seq_length,
                        "dimensions": self._model.get_sentence_embedding_dimension(),
                        "tokenizer": (
                            type(self._model.tokenizer).__name__
                            if hasattr(self._model, "tokenizer")
                            else None
                        ),
                    },
                )

        return model_info

    async def _list_models(self) -> list[dict[str, Any]]:
        """List popular Sentence Transformer models."""
        models = [
            {
                "name": "all-MiniLM-L6-v2",
                "description": "Lightweight model, good performance/speed tradeoff",
                "dimensions": 384,
                "size": "80MB",
                "recommended_for": "general_purpose",
            },
            {
                "name": "all-mpnet-base-v2",
                "description": "Best quality model for many tasks",
                "dimensions": 768,
                "size": "420MB",
                "recommended_for": "high_accuracy",
            },
            {
                "name": "multi-qa-mpnet-base-dot-v1",
                "description": "Optimized for question-answering retrieval",
                "dimensions": 768,
                "size": "420MB",
                "recommended_for": "qa_retrieval",
            },
            {
                "name": "all-distilroberta-v1",
                "description": "Good balance of quality and speed",
                "dimensions": 768,
                "size": "290MB",
                "recommended_for": "balanced",
            },
            {
                "name": "paraphrase-multilingual-mpnet-base-v2",
                "description": "Multilingual model for 50+ languages",
                "dimensions": 768,
                "size": "970MB",
                "recommended_for": "multilingual",
            },
        ]

        return [
            model_info
            | {
                "provider": "sentence_transformers",
                "type": "embedding",
                "local": True,
                "requires_api_key": False,
            }
            for model_info in models
        ]
