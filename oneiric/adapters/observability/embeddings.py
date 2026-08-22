"""Hybrid EmbeddingService with a 5-backend probe chain.

The Bodai ecosystem needs real semantic embeddings without forcing a
heavy ONNX/torch dependency on every component. This service probes a
chain of HTTP and pure-numpy backends at ``initialize()`` time and
selects the first responder:

    1. llama.cpp server     preferred local    http://localhost:8080
    2. Ollama               fallback local     http://localhost:11434
    3. MiniMax (ZhipuAI)    cloud              https://api.minimax.chat/v1
    4. Model2Vec            pure-numpy offline minishlab/potion-base-32M
    5. Mock                 last resort        deterministic Gaussian

Each leg's probe is a fast GET to ``/v1/models`` (or equivalent). The
selected backend is cached for the lifetime of the service. ``encode``
and ``encode_batch`` delegate to the active backend.

Backwards compatibility:

- ``embed_trace`` still accepts a dict-shaped trace and returns a
  ``np.ndarray`` (same signature as the previous implementation).
- ``__init__`` accepts an optional ``EmbeddingSettings`` instance; if
  omitted, default settings enable every backend.

The previous implementation hardcoded ``all-MiniLM-L6-v2`` with 384
dimensions via optional sentence-transformers (which was never
installed in production). This rewrite replaces that with the chain
above so callers finally get real embeddings when the underlying
backend is reachable.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

import httpx
import numpy as np

from oneiric.adapters.observability.embedding_settings import EmbeddingSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

_EMBED_CACHE: dict[tuple[int, str], np.ndarray] = {}
_EMBED_CACHE_MAX = 1000


class EmbeddingService:
    """Hybrid embedding service with auto-detected backend.

    The service starts in an uninitialised state. Call ``await initialize()``
    to probe the backend chain and select the first reachable backend.
    After ``initialize``, ``encode`` and ``embed_trace`` route through
    that backend, with ``is_available()`` reporting whether a real
    backend (not the mock fallback) was selected.

    Examples:
        >>> svc = EmbeddingService()
        >>> await svc.initialize()
        >>> svc.backend_name()
        'ollama'
        >>> svc.is_available()
        True
        >>> v = await svc.encode("hello")
        >>> v.shape
        (768,)
    """

    def __init__(
        self,
        settings: EmbeddingSettings | None = None,
        model_name: str | None = None,
    ) -> None:
        """Initialize embedding service.

        Args:
            settings: Per-backend config. ``None`` → defaults.
            model_name: Backwards-compat param (the original ctor
                accepted ``model_name=...``). When provided AND
                ``settings`` is ``None``, the settings' model_name
                fields stay at their defaults (the legacy arg is
                informational only).
        """
        self._settings = settings or EmbeddingSettings()
        self._model_name = model_name  # retained for back-compat
        self._backend: str = "uninitialized"
        self._backend_dim: int | None = None
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Probe the backend chain and select the first responder.

        Order (matches ``docs/plans/2026-08-22-hybrid-embeddings-design.md``):

            llama_cpp → ollama → minimax → model2vec → mock

        ``initialize`` never raises. If every probe fails (or raises),
        the service falls back to the deterministic mock backend and
        ``is_available()`` returns ``False``.
        """
        probe_order = (
            ("llama_cpp", self._probe_llama_cpp),
            ("ollama", self._probe_ollama),
            ("minimax", self._probe_minimax),
            ("model2vec", self._probe_model2vec),
        )

        for name, probe_fn in probe_order:
            try:
                if await probe_fn():
                    self._backend = name
                    logger.info(
                        "oneiric.embedding.backend_selected",
                        extra={"backend": name},
                    )
                    return
            except Exception as exc:
                logger.debug(
                    "oneiric.embedding.probe_failed",
                    extra={"backend": name, "error": str(exc)},
                )

        # Fallback to mock
        self._backend = "mock"
        self._backend_dim = self._settings.mock_dimension
        logger.warning(
            "oneiric.embedding.fell_back_to_mock",
            extra={"dimension": self._backend_dim},
        )

    def is_available(self) -> bool:
        """Whether a real (non-mock) backend was selected at initialize."""
        return self._backend not in ("mock", "uninitialized")

    def backend_name(self) -> str:
        """Name of the active backend (or ``"uninitialized"``)."""
        return self._backend

    def dimension(self) -> int | None:
        """Embedding vector dimension of the active backend, if known."""
        return self._backend_dim

    async def encode(self, text: str) -> np.ndarray:
        """Generate an embedding for a single text.

        Args:
            text: Input text.

        Returns:
            ``np.ndarray`` of shape ``(dimension,)``.

        Raises:
            RuntimeError: If ``initialize()`` was not called.
        """
        if self._backend == "uninitialized":
            raise RuntimeError(
                "EmbeddingService.initialize() must be awaited before encode()"
            )

        if self._backend == "llama_cpp":
            results = await self._encode_llama_cpp([text])
            return results[0]
        if self._backend == "ollama":
            results = await self._encode_ollama([text])
            return results[0]
        if self._backend == "minimax":
            results = await self._encode_minimax([text])
            return results[0]
        if self._backend == "model2vec":
            results = self._encode_model2vec([text])
            return results[0]
        return self._generate_fallback_embedding(text)

    async def encode_batch(self, texts: Sequence[str]) -> list[np.ndarray]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input strings.

        Returns:
            List of ``np.ndarray`` of shape ``(dimension,)``.

        Raises:
            RuntimeError: If ``initialize()`` was not called.
        """
        if self._backend == "uninitialized":
            raise RuntimeError(
                "EmbeddingService.initialize() must be awaited before encode_batch()"
            )

        if self._backend == "llama_cpp":
            return await self._encode_llama_cpp(list(texts))
        if self._backend == "ollama":
            return await self._encode_ollama(list(texts))
        if self._backend == "minimax":
            return await self._encode_minimax(list(texts))
        if self._backend == "model2vec":
            return self._encode_model2vec(list(texts))
        return [self._generate_fallback_embedding(t) for t in texts]

    async def embed_trace(self, trace: dict[str, Any]) -> np.ndarray:
        """Generate an embedding for an OpenTelemetry-shaped trace dict.

        Backwards-compatible signature. Builds a human-readable text
        representation of the trace, then delegates to ``encode``.

        Args:
            trace: Dict with ``service``, ``operation``, ``status``,
                ``duration_ms``, and ``attributes`` keys.

        Returns:
            ``np.ndarray`` of shape ``(dimension,)``.
        """
        text = self._build_text_from_trace(trace)
        cache_key = self._generate_cache_key(trace)
        cached = _EMBED_CACHE.get((cache_key, text))
        if cached is not None:
            return cached
        try:
            embedding = await self.encode(text)
        except (httpx.HTTPError, RuntimeError, OSError, ValueError) as exc:
            logger.warning(
                "oneiric.embedding.encode_failed",
                extra={"error": str(exc), "trace_id": trace.get("trace_id")},
            )
            return self._generate_fallback_embedding(trace.get("trace_id", "unknown"))
        if len(_EMBED_CACHE) >= _EMBED_CACHE_MAX:
            _EMBED_CACHE.pop(next(iter(_EMBED_CACHE)))
        _EMBED_CACHE[(cache_key, text)] = embedding
        return embedding

    # ------------------------------------------------------------------
    # Backwards-compat trace helpers (kept from the old implementation)
    # ------------------------------------------------------------------

    def _build_text_from_trace(self, trace: dict[str, Any]) -> str:
        service = trace.get("service", "unknown")
        operation = trace.get("operation", "unknown")
        status = trace.get("status", "UNKNOWN")
        duration_ms = trace.get("duration_ms", 0)
        attributes = trace.get("attributes", {})

        attr_str = " ".join(f"{k}={v}" for k, v in sorted(attributes.items()))
        return (
            f"{service} {operation} {status} in {duration_ms}ms attributes: {attr_str}"
        )

    def _generate_cache_key(self, trace: dict[str, Any]) -> int:
        canonical_trace = json.dumps(trace, sort_keys=True, default=str)
        return hash(canonical_trace)

    def _generate_fallback_embedding(self, trace_id: str) -> np.ndarray:
        """Generate a deterministic mock embedding.

        Used when ``initialize()`` could not reach any real backend, or
        when an individual ``encode`` call fails. The output is
        deterministic for a given ``trace_id`` so search ranks stay
        stable across runs (semantically meaningless but reproducible).
        """
        seed_text = trace_id
        # Deterministic seed from SHA-256 of the text.
        digest = hashlib.sha256(seed_text.encode()).digest()
        seed_int = int.from_bytes(digest[:8], "big")
        rng = np.random.default_rng(seed_int)
        vec = rng.standard_normal(self._settings.mock_dimension).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = (vec / norm).astype(np.float32)
        return vec

    # ------------------------------------------------------------------
    # Per-backend probes
    # ------------------------------------------------------------------

    async def _probe_llama_cpp(self) -> bool:
        if not self._settings.llama_cpp_enabled:
            return False
        url = f"{self._settings.llama_cpp_base_url.rstrip('/')}/v1/models"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.llama_cpp_timeout_seconds
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    # Try a single encode to confirm dimension.
                    probe_vec = await self._probe_encode_via(
                        client,
                        f"{self._settings.llama_cpp_base_url.rstrip('/')}/v1/embeddings",
                        self._settings.llama_cpp_model,
                        ["probe"],
                    )
                    if probe_vec is not None:
                        self._backend_dim = int(probe_vec.shape[0])
                        return True
        except httpx.HTTPError:
            return False
        return False

    async def _probe_ollama(self) -> bool:
        if not self._settings.ollama_enabled:
            return False
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/tags"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.ollama_timeout_seconds
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    probe_vec = await self._probe_encode_via(
                        client,
                        f"{self._settings.ollama_base_url.rstrip('/')}/api/embeddings",
                        self._settings.ollama_model,
                        ["probe"],
                        ollama=True,
                    )
                    if probe_vec is not None:
                        self._backend_dim = int(probe_vec.shape[0])
                        return True
        except httpx.HTTPError:
            return False
        return False

    async def _probe_minimax(self) -> bool:
        if (
            not self._settings.minimax_enabled
            or not self._settings.minimax_api_key
            or not self._settings.minimax_group_id
        ):
            return False
        url = f"{self._settings.minimax_base_url.rstrip('/')}/embeddings"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.minimax_timeout_seconds
            ) as client:
                resp = await client.post(
                    url,
                    params={"GroupId": self._settings.minimax_group_id},
                    headers={
                        "Authorization": f"Bearer {self._settings.minimax_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._settings.minimax_model,
                        "type": "query",
                        "texts": ["probe"],
                    },
                )
                if resp.status_code == 200:
                    body = resp.json()
                    if (
                        body.get("base_resp", {}).get("status_code") == 0
                        and "vectors" in body
                        and body["vectors"]
                    ):
                        self._backend_dim = len(body["vectors"][0])
                        return True
        except httpx.HTTPError:
            return False
        return False

    async def _probe_model2vec(self) -> bool:
        if not self._settings.model2vec_enabled:
            return False
        try:
            from model2vec import StaticModel  # ty: ignore[unresolved-import]
        except ImportError:
            return False
        try:
            model = StaticModel.from_pretrained(self._settings.model2vec_model_name)
            vec = model.encode(["probe"])
            self._backend_dim = int(vec.shape[1])
            # Cache the loaded model for subsequent encode calls.
            self._model2vec_model = model  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    async def _probe_encode_via(
        self,
        client: httpx.AsyncClient,
        url: str,
        model: str,
        texts: list[str],
        ollama: bool = False,
    ) -> np.ndarray | None:
        """Send a probe encode to determine the backend's vector dimension.

        Args:
            client: The httpx client already opened by the caller.
            url: Full encode endpoint URL.
            model: Model name to request.
            texts: Input list (one probe text is enough).
            ollama: If True, use Ollama's ``{"prompt": ..., "model": ...}``
                request shape; else OpenAI ``{"input": ..., "model": ...}``.

        Returns:
            The resulting ``np.ndarray`` on success, ``None`` otherwise.
        """
        try:
            if ollama:
                payload = {"model": model, "prompt": texts[0]}
            else:
                payload = {"model": model, "input": texts}
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                return None
            body = resp.json()
            if ollama:
                vec = body.get("embedding")
                return np.asarray(vec, dtype=np.float32) if vec is not None else None
            data = body.get("data") or []
            if data and "embedding" in data[0]:
                return np.asarray(data[0]["embedding"], dtype=np.float32)
        except (httpx.HTTPError, ValueError, KeyError):
            return None
        return None

    # ------------------------------------------------------------------
    # Per-backend encode
    # ------------------------------------------------------------------

    async def _encode_llama_cpp(self, texts: list[str]) -> list[np.ndarray]:
        url = f"{self._settings.llama_cpp_base_url.rstrip('/')}/v1/embeddings"
        async with httpx.AsyncClient(
            timeout=self._settings.llama_cpp_timeout_seconds
        ) as client:
            resp = await client.post(
                url, json={"model": self._settings.llama_cpp_model, "input": texts}
            )
            resp.raise_for_status()
            body = resp.json()
            return [
                np.asarray(item["embedding"], dtype=np.float32) for item in body["data"]
            ]

    async def _encode_ollama(self, texts: list[str]) -> list[np.ndarray]:
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/embeddings"
        results: list[np.ndarray] = []
        async with httpx.AsyncClient(
            timeout=self._settings.ollama_timeout_seconds
        ) as client:
            for text in texts:
                resp = await client.post(
                    url, json={"model": self._settings.ollama_model, "prompt": text}
                )
                resp.raise_for_status()
                body = resp.json()
                results.append(np.asarray(body["embedding"], dtype=np.float32))
        return results

    async def _encode_minimax(self, texts: list[str]) -> list[np.ndarray]:
        url = f"{self._settings.minimax_base_url.rstrip('/')}/embeddings"
        async with httpx.AsyncClient(
            timeout=self._settings.minimax_timeout_seconds
        ) as client:
            resp = await client.post(
                url,
                params={"GroupId": self._settings.minimax_group_id or ""},
                headers={
                    "Authorization": f"Bearer {self._settings.minimax_api_key or ''}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._settings.minimax_model,
                    "type": "db",
                    "texts": texts,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            return [np.asarray(vec, dtype=np.float32) for vec in body["vectors"]]

    def _encode_model2vec(self, texts: list[str]) -> list[np.ndarray]:
        model = getattr(self, "_model2vec_model", None)
        if model is None:
            from model2vec import StaticModel  # ty: ignore[unresolved-import]

            model = StaticModel.from_pretrained(self._settings.model2vec_model_name)
            self._model2vec_model = model  # type: ignore[attr-defined]
        arr = model.encode(texts.copy())
        return [np.asarray(row, dtype=np.float32) for row in arr]
