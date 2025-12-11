"""ONNX Runtime embeddings adapter implementation for optimized inference."""

from __future__ import annotations

import asyncio
import importlib.util
import time
from contextlib import suppress
from typing import Any

import numpy as np
from pydantic import ConfigDict, Field

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
    PoolingStrategy,
)

# Check if onnxruntime and transformers are available
_onnx_available = (
    importlib.util.find_spec("onnxruntime") is not None
    and importlib.util.find_spec("transformers") is not None
)


class ONNXEmbeddingSettings(EmbeddingBaseSettings):
    """ONNX-specific embedding settings."""

    model_config = ConfigDict(env_prefix="ONNX_")

    model_path: str = Field(description="Path to ONNX model file")
    tokenizer_name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace tokenizer name",
    )
    tokenizer_revision: str = Field(
        default="main",
        description="HuggingFace tokenizer revision",
    )
    providers: list[str] = Field(
        default_factory=lambda: ["CPUExecutionProvider"],
        description="ONNX execution providers (CPUExecutionProvider, CUDAExecutionProvider, etc.)",
    )

    # Model optimization
    enable_cpu_mem_arena: bool = Field(
        default=True,
        description="Enable CPU memory arena for better performance",
    )
    enable_mem_pattern: bool = Field(
        default=True,
        description="Enable memory pattern optimization",
    )
    enable_profiling: bool = Field(
        default=False,
        description="Enable ONNX runtime profiling",
    )
    inter_op_num_threads: int = Field(
        default=0,
        description="Number of threads for inter-op parallelism (0 = auto)",
    )
    intra_op_num_threads: int = Field(
        default=0,
        description="Number of threads for intra-op parallelism (0 = auto)",
    )

    # Processing settings
    max_seq_length: int = Field(
        default=512,
        description="Maximum sequence length for tokenization",
    )
    pooling_strategy: PoolingStrategy = Field(default=PoolingStrategy.MEAN)
    batch_size: int = Field(default=32)

    # Edge optimization
    optimize_for_inference: bool = Field(
        default=True,
        description="Enable inference optimizations",
    )
    enable_quantization: bool = Field(
        default=False,
        description="Enable model quantization",
    )
    graph_optimization_level: str = Field(
        default="ORT_ENABLE_ALL",
        description="Graph optimization level (ORT_DISABLE_ALL, ORT_ENABLE_BASIC, ORT_ENABLE_EXTENDED, ORT_ENABLE_ALL)",
    )

    # Override base settings defaults
    model: str = Field(default=EmbeddingModel.ONNX_ALL_MINILM_L6_V2.value)


class ONNXEmbeddingAdapter(EmbeddingBase):
    """ONNX Runtime embeddings adapter implementing the lifecycle contract."""

    metadata = AdapterMetadata(
        category="embedding",
        provider="onnx",
        factory="oneiric.adapters.embedding.onnx:ONNXEmbeddingAdapter",
        version="1.0.0",
        description="ONNX Runtime embeddings adapter for high-performance inference and edge deployment",
        capabilities=[
            "async_operations",
            "batching",
            "caching",
            "metrics",
            "batch_embedding",
            "edge_optimized",
            "pooling_strategies",
            "memory_efficient_processing",
            "text_preprocessing",
            "vector_normalization",
            "on_device",
        ],
        stack_level=25,  # Lower than sentence_transformers (30) - more optimized
        priority=450,  # Between OpenAI (500) and sentence_transformers (400)
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=False,  # No API key required - runs locally
        settings_model=ONNXEmbeddingSettings,
    )

    def __init__(self, settings: ONNXEmbeddingSettings) -> None:
        super().__init__(settings)
        self._settings: ONNXEmbeddingSettings = settings
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._input_names: list[str] = []
        self._output_names: list[str] = []
        self._logger = get_logger("adapter.embedding.onnx").bind(
            domain="adapter",
            key="embedding",
            provider="onnx",
        )

    async def init(self) -> None:
        """Initialize ONNX embeddings adapter."""
        self._logger.info("onnx-adapter-init-start")

        if not _onnx_available:
            raise LifecycleError(
                "onnx-runtime-import-failed: pip install onnxruntime transformers"
            )

        try:
            # Load model and tokenizer
            await self._load_model()

            # Test with a simple embedding request
            test_result = await self.embed_text("initialization test")
            self._logger.debug(
                "onnx-test-success",
                dimensions=len(test_result),
                providers=self._session.get_providers() if self._session else [],
            )

            self._logger.info("onnx-adapter-init-success")
        except Exception as exc:
            self._logger.error("onnx-adapter-init-failed", error=str(exc))
            raise LifecycleError(f"onnx-init-failed: {exc}") from exc

    async def _load_model(self) -> None:
        """Load the ONNX model and tokenizer."""
        try:
            import importlib

            ort = importlib.import_module("onnxruntime")
            transformers = importlib.import_module("transformers")

            self._logger.info(
                "loading-onnx-model",
                model_path=self._settings.model_path,
                tokenizer=self._settings.tokenizer_name,
            )

            # Load tokenizer in executor
            self._tokenizer = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: transformers.AutoTokenizer.from_pretrained(
                    self._settings.tokenizer_name,
                    revision=self._settings.tokenizer_revision,
                ),
            )

            # Configure ONNX session options
            session_options = ort.SessionOptions()
            session_options.enable_cpu_mem_arena = self._settings.enable_cpu_mem_arena
            session_options.enable_mem_pattern = self._settings.enable_mem_pattern
            session_options.enable_profiling = self._settings.enable_profiling

            if self._settings.inter_op_num_threads > 0:
                session_options.inter_op_num_threads = (
                    self._settings.inter_op_num_threads
                )
            if self._settings.intra_op_num_threads > 0:
                session_options.intra_op_num_threads = (
                    self._settings.intra_op_num_threads
                )

            # Set graph optimization level
            opt_level_map = {
                "ORT_DISABLE_ALL": ort.GraphOptimizationLevel.ORT_DISABLE_ALL,
                "ORT_ENABLE_BASIC": ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
                "ORT_ENABLE_EXTENDED": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
                "ORT_ENABLE_ALL": ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
            }
            session_options.graph_optimization_level = opt_level_map.get(
                self._settings.graph_optimization_level,
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
            )

            # Create ONNX session in executor
            self._session = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ort.InferenceSession(
                    self._settings.model_path,
                    sess_options=session_options,
                    providers=self._settings.providers,
                ),
            )

            # Get input/output names
            if self._session is not None:
                self._input_names = [
                    input_node.name for input_node in self._session.get_inputs()
                ]
                self._output_names = [
                    output_node.name for output_node in self._session.get_outputs()
                ]

            self._logger.info(
                "onnx-model-loaded",
                providers=self._settings.providers,
                input_names=self._input_names,
                output_names=self._output_names,
            )

        except Exception as exc:
            self._logger.exception("onnx-model-load-failed", error=str(exc))
            raise LifecycleError(f"onnx-model-load-failed: {exc}") from exc

    async def _ensure_client(self) -> tuple[Any, Any]:
        """Ensure ONNX session and tokenizer are initialized."""
        if self._session is None or self._tokenizer is None:
            await self._load_model()
        return self._session, self._tokenizer

    async def health(self) -> bool:
        """Check if ONNX embeddings service is healthy."""
        if not self._session or not self._tokenizer:
            return False

        try:
            # Test with a simple embedding request
            await self.embed_text("health check test")
            return True
        except Exception as exc:
            self._logger.warning("onnx-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Cleanup ONNX session and tokenizer resources."""
        if self._session is not None:
            try:
                del self._session
                self._session = None
            except Exception as exc:
                self._logger.warning("onnx-session-cleanup-warning", error=str(exc))

        if self._tokenizer is not None:
            try:
                del self._tokenizer
                self._tokenizer = None
            except Exception as exc:
                self._logger.warning("onnx-tokenizer-cleanup-warning", error=str(exc))

        self._input_names.clear()
        self._output_names.clear()
        self._model_cache.clear()
        self._logger.info("onnx-cleanup-complete")

    async def _tokenize_batch(
        self,
        texts: list[str],
        tokenizer: Any,
    ) -> dict[str, np.ndarray]:
        """Tokenize batch of texts for ONNX processing."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=self._settings.max_seq_length,
                return_tensors="np",
            ),
        )

    def _prepare_onnx_inputs(
        self,
        tokenized: dict[str, np.ndarray],
    ) -> dict[str, np.ndarray]:
        """Prepare inputs for ONNX inference."""
        onnx_inputs: dict[str, np.ndarray] = {}

        for input_name in self._input_names:
            if input_name == "input_ids":
                onnx_inputs[input_name] = tokenized["input_ids"].astype(np.int64)
            elif input_name == "attention_mask":
                onnx_inputs[input_name] = tokenized["attention_mask"].astype(np.int64)
            elif input_name == "token_type_ids" and "token_type_ids" in tokenized:
                onnx_inputs[input_name] = tokenized["token_type_ids"].astype(np.int64)

        return onnx_inputs

    def _count_tokens_safe(
        self,
        text: str,
        tokenizer: Any,
    ) -> int | None:
        """Safely count tokens with error handling."""
        if not hasattr(tokenizer, "encode"):
            return None

        with suppress(Exception):
            return len(tokenizer.encode(text))

        return None

    def _create_embedding_result(
        self,
        text: str,
        embedding: np.ndarray,
        model: str,
        token_count: int | None,
    ) -> EmbeddingResult:
        """Create single embedding result with metadata."""
        return EmbeddingResult(
            text=text,
            embedding=embedding.tolist(),
            model=model,
            dimensions=len(embedding),
            tokens=token_count,
            metadata={
                "pooling_strategy": self._settings.pooling_strategy.value,
                "providers": self._settings.providers,
                "max_seq_length": self._settings.max_seq_length,
                "optimized": True,
            },
        )

    async def _process_single_batch(
        self,
        batch_texts: list[str],
        session: Any,
        tokenizer: Any,
        model: str,
        normalize: bool,
    ) -> list[EmbeddingResult]:
        """Process a single batch of texts."""
        # Tokenize
        inputs = await self._tokenize_batch(batch_texts, tokenizer)

        # Prepare ONNX inputs
        onnx_inputs = self._prepare_onnx_inputs(inputs)

        # Run inference in executor
        outputs = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: session.run(self._output_names, onnx_inputs),
        )

        # Apply pooling
        embeddings = await self._apply_pooling(
            outputs[0],
            inputs["attention_mask"],
            self._settings.pooling_strategy,
        )

        # Normalize if requested
        if normalize:
            embeddings = self._normalize_embeddings(embeddings)

        # Create results with token counting
        return [
            self._create_embedding_result(
                text,
                embedding,
                model,
                self._count_tokens_safe(text, tokenizer),
            )
            for text, embedding in zip(batch_texts, embeddings, strict=False)
        ]

    async def _process_all_batches(
        self,
        texts: list[str],
        batch_size: int,
        session: Any,
        tokenizer: Any,
        model: str,
        normalize: bool,
    ) -> list[EmbeddingResult]:
        """Process all text batches and return results."""
        results = []
        batches = self._batch_texts(texts, batch_size)

        for batch_texts in batches:
            try:
                batch_results = await self._process_single_batch(
                    batch_texts,
                    session,
                    tokenizer,
                    model,
                    normalize,
                )
                results.extend(batch_results)

                self._logger.debug(
                    "onnx-batch-completed",
                    batch_size=len(batch_texts),
                    model=model,
                )

            except Exception as exc:
                self._logger.exception("onnx-batch-failed", error=str(exc))
                raise LifecycleError(f"onnx-batch-failed: {exc}") from exc

        return results

    async def _embed_texts(
        self,
        texts: list[str],
        model: str,
        normalize: bool,
        batch_size: int,
        **kwargs: Any,
    ) -> EmbeddingBatch:
        """Generate embeddings for multiple texts using ONNX Runtime."""
        start_time = time.time()
        session, tokenizer = await self._ensure_client()

        # Process all batches
        results = await self._process_all_batches(
            texts,
            batch_size,
            session,
            tokenizer,
            model,
            normalize,
        )

        # Aggregate metrics
        processing_time = time.time() - start_time
        total_tokens = sum(result.tokens or 0 for result in results)

        return EmbeddingBatch(
            results=results,
            total_tokens=total_tokens if total_tokens > 0 else None,
            processing_time=processing_time,
            model=model,
            batch_size=len(results),
        )

    async def _apply_pooling(
        self,
        token_embeddings: np.ndarray,
        attention_mask: np.ndarray,
        strategy: PoolingStrategy,
    ) -> np.ndarray:
        """Apply pooling strategy to token embeddings."""
        if strategy == PoolingStrategy.MEAN:
            # Mean pooling with attention mask
            input_mask_expanded = np.expand_dims(attention_mask, axis=-1)
            input_mask_expanded = np.repeat(
                input_mask_expanded,
                token_embeddings.shape[-1],
                axis=-1,
            )

            sum_embeddings = np.sum(token_embeddings * input_mask_expanded, axis=1)
            sum_mask = np.clip(
                np.sum(input_mask_expanded, axis=1),
                a_min=1e-9,
                a_max=None,
            )
            result: np.ndarray = sum_embeddings / sum_mask
            return result

        if strategy == PoolingStrategy.MAX:
            # Max pooling
            input_mask_expanded = np.expand_dims(attention_mask, axis=-1)
            input_mask_expanded = np.repeat(
                input_mask_expanded,
                token_embeddings.shape[-1],
                axis=-1,
            )

            token_embeddings = np.where(
                input_mask_expanded == 0,
                -1e9,
                token_embeddings,
            )
            result = np.max(token_embeddings, axis=1)
            return result

        if strategy == PoolingStrategy.CLS:
            # CLS token pooling (first token)
            result = token_embeddings[:, 0]
            return result

        if strategy == PoolingStrategy.WEIGHTED_MEAN:
            # Weighted mean (simple implementation)
            weights = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
            weighted_embeddings = token_embeddings * weights
            sum_embeddings = np.sum(weighted_embeddings, axis=1)
            sum_weights = np.sum(weights, axis=1)
            result = sum_embeddings / np.clip(sum_weights, a_min=1e-9, a_max=None)
            return result

        raise ValueError(f"Unsupported pooling strategy: {strategy}")

    def _normalize_embeddings(self, embeddings: np.ndarray) -> np.ndarray:
        """Normalize embeddings using L2 normalization."""
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-12, a_max=None)
        result: np.ndarray = embeddings / norms
        return result

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
        """Get information about the ONNX model."""
        model_info: dict[str, Any] = {
            "name": model,
            "provider": "onnx",
            "type": "embedding",
            "model_path": self._settings.model_path,
            "tokenizer": self._settings.tokenizer_name,
            "optimized": True,
            "local": True,
            "requires_api_key": False,
        }

        if self._session:
            model_info.update(
                {
                    "providers": self._session.get_providers(),
                    "input_names": self._input_names,
                    "output_names": self._output_names,
                },
            )

        return model_info

    async def _list_models(self) -> list[dict[str, Any]]:
        """List common ONNX embedding models."""
        # These would typically be downloaded/converted models
        models = [
            {
                "name": "onnx-all-MiniLM-L6-v2",
                "description": "ONNX optimized version of all-MiniLM-L6-v2",
                "dimensions": 384,
                "performance": "High speed, low memory",
            },
            {
                "name": "onnx-all-mpnet-base-v2",
                "description": "ONNX optimized version of all-mpnet-base-v2",
                "dimensions": 768,
                "performance": "Balanced speed and quality",
            },
        ]

        return [
            model_info
            | {
                "provider": "onnx",
                "type": "embedding",
                "local": True,
                "requires_api_key": False,
            }
            for model_info in models
        ]

    async def get_performance_metrics(self) -> dict[str, Any]:
        """Get ONNX runtime performance metrics."""
        if not self._session:
            return {}

        try:
            profiling_data = (
                self._session.end_profiling()
                if self._settings.enable_profiling
                else None
            )

            return {
                "providers": self._session.get_providers(),
                "input_names": self._input_names,
                "output_names": self._output_names,
                "profiling_enabled": self._settings.enable_profiling,
                "profiling_data": profiling_data,
                "session_options": {
                    "enable_cpu_mem_arena": self._settings.enable_cpu_mem_arena,
                    "enable_mem_pattern": self._settings.enable_mem_pattern,
                    "inter_op_threads": self._settings.inter_op_num_threads,
                    "intra_op_threads": self._settings.intra_op_num_threads,
                    "graph_optimization": self._settings.graph_optimization_level,
                },
            }
        except Exception as exc:
            self._logger.warning("performance-metrics-failed", error=str(exc))
            return {"error": str(exc)}
