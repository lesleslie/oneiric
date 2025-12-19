"""Builtin compression and hashing action kits."""

from __future__ import annotations

import base64
import bz2
import hashlib
import json
import lzma
import zlib
from typing import Literal

from pydantic import BaseModel, Field

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class CompressionActionSettings(BaseModel):
    """Settings for the compression action kit."""

    algorithm: Literal["zlib", "bz2", "lzma"] = Field(
        default="zlib",
        description="Default compression algorithm.",
    )
    level: int = Field(
        default=6,
        ge=0,
        le=9,
        description="Compression level handed to the underlying algorithm.",
    )


class CompressionAction:
    """Action kit that compresses/decompresses payloads."""

    metadata = ActionMetadata(
        key="compression.encode",
        provider="builtin-compression",
        factory="oneiric.actions.compression:CompressionAction",
        description="Utility action for compressing/decompressing short payloads",
        domains=["task", "workflow"],
        capabilities=["compress", "decompress"],
        stack_level=25,
        priority=450,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=CompressionActionSettings,
    )

    def __init__(self, settings: CompressionActionSettings | None = None) -> None:
        self._settings = settings or CompressionActionSettings()
        self._logger = get_logger("action.compression")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        mode = payload.get("mode", "compress")
        algorithm = payload.get("algorithm", self._settings.algorithm)
        if mode not in {"compress", "decompress"}:
            raise LifecycleError("compression-action-invalid-mode")
        if mode == "compress":
            text = payload.get("text", "")
            if not isinstance(text, str):
                raise LifecycleError("compression-action-text-required")
            raw = text.encode("utf-8")
            compressed = self._compress(raw, algorithm)
            token = base64.b64encode(compressed).decode("ascii")
            self._logger.debug(
                "compression-action-compress", algorithm=algorithm, size=len(token)
            )
            return {
                "mode": "compress",
                "algorithm": algorithm,
                "data": token,
            }
        data = payload.get("data")
        if not isinstance(data, str):
            raise LifecycleError("compression-action-data-required")
        try:
            raw = base64.b64decode(data.encode("ascii"))
        except Exception as exc:  # pragma: no cover - base64 error path
            raise LifecycleError("compression-action-decode-error") from exc
        text = self._decompress(raw, algorithm).decode("utf-8")
        self._logger.debug(
            "compression-action-decompress", algorithm=algorithm, size=len(text)
        )
        return {
            "mode": "decompress",
            "algorithm": algorithm,
            "text": text,
        }

    def _compress(self, data: bytes, algorithm: str) -> bytes:
        level = self._settings.level
        if algorithm == "zlib":
            return zlib.compress(data, level)
        if algorithm == "bz2":
            return bz2.compress(data, compresslevel=level)
        if algorithm == "lzma":
            preset = max(0, min(9, level))
            return lzma.compress(data, preset=preset)
        raise LifecycleError("compression-action-unknown-algorithm")

    def _decompress(self, data: bytes, algorithm: str) -> bytes:
        if algorithm == "zlib":
            return zlib.decompress(data)
        if algorithm == "bz2":
            return bz2.decompress(data)
        if algorithm == "lzma":
            return lzma.decompress(data)
        raise LifecycleError("compression-action-unknown-algorithm")


class HashActionSettings(BaseModel):
    """Settings for the hashing action kit."""

    algorithm: Literal["sha256", "sha512", "blake2b"] = Field(
        default="sha256",
        description="Digest algorithm used when hashing payloads.",
    )
    encoding: Literal["hex", "base64"] = Field(
        default="hex",
        description="Encoding applied to the digest output.",
    )
    salt: str | None = Field(
        default=None,
        description="Optional salt prepended to the payload before hashing.",
    )


class HashAction:
    """Action kit that computes deterministic hashes for payloads."""

    metadata = ActionMetadata(
        key="compression.hash",
        provider="builtin-hash",
        factory="oneiric.actions.compression:HashAction",
        description="Stateless hashing helper that emits hex/base64 digests",
        domains=["task", "service", "workflow"],
        capabilities=["hash", "checksum", "validate"],
        stack_level=25,
        priority=445,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=HashActionSettings,
    )

    _ALGORITHMS = {
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
        "blake2b": hashlib.blake2b,
    }

    def __init__(self, settings: HashActionSettings | None = None) -> None:
        self._settings = settings or HashActionSettings()
        self._logger = get_logger("action.compression.hash")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        algorithm = (payload.get("algorithm") or self._settings.algorithm).lower()
        if algorithm not in self._ALGORITHMS:
            raise LifecycleError("hash-action-algorithm-invalid")
        encoding = (payload.get("encoding") or self._settings.encoding).lower()
        if encoding not in {"hex", "base64"}:
            raise LifecycleError("hash-action-encoding-invalid")
        data_value = payload.get("value") or payload.get("text") or payload.get("data")
        if data_value is None:
            raise LifecycleError("hash-action-value-required")
        data_bytes = self._to_bytes(data_value)
        salt = payload.get("salt") or self._settings.salt
        if salt:
            data_bytes = salt.encode("utf-8") + data_bytes
        digest = self._ALGORITHMS[algorithm]()
        digest.update(data_bytes)
        raw = digest.digest()
        if encoding == "hex":
            token = raw.hex()
        else:
            token = base64.b64encode(raw).decode("ascii")
        self._logger.info("hash-action-digest", algorithm=algorithm, encoding=encoding)
        return {
            "status": "hashed",
            "algorithm": algorithm,
            "encoding": encoding,
            "digest": token,
            "salted": bool(salt),
        }

    def _to_bytes(self, value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        except TypeError as exc:  # pragma: no cover - serialization edge
            raise LifecycleError("hash-action-value-invalid") from exc
