"""Serialization encode/decode action kit."""

from __future__ import annotations

import asyncio
import base64
import json
import pickle
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class SerializationActionSettings(BaseModel):
    """Settings for the serialization action kit."""

    default_format: Literal["json", "yaml", "pickle"] = Field(
        default="json",
        description="Default serialization format when payload omits one.",
    )
    sort_keys: bool = Field(
        default=False,
        description="Sort keys for deterministic JSON/YAML output.",
    )
    ensure_ascii: bool = Field(
        default=False,
        description="Force ASCII output for JSON encoding.",
    )


class SerializationAction:
    """Action kit that encodes/decodes payloads across common formats.

    Security Warning:
        The pickle format can execute arbitrary code during deserialization.
        Only use pickle with data from trusted sources within your internal
        workflows. For external data or untrusted sources, use JSON or YAML.

    Supported Formats:
        - json: Safe for untrusted data, human-readable
        - yaml: Safe for untrusted data, more flexible than JSON
        - pickle: TRUSTED DATA ONLY - supports arbitrary Python objects
    """

    metadata = ActionMetadata(
        key="serialization.encode",
        provider="builtin-serialization",
        factory="oneiric.actions.serialization:SerializationAction",
        description="Serializes/deserializes payloads across JSON, YAML, and pickle",
        domains=["task", "service", "workflow"],
        capabilities=["encode", "decode", "serialize"],
        stack_level=30,
        priority=430,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=SerializationActionSettings,
    )

    _TEXT_FORMATS = {"json", "yaml"}

    def __init__(self, settings: SerializationActionSettings | None = None) -> None:
        self._settings = settings or SerializationActionSettings()
        self._logger = get_logger("action.serialization")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        mode = (payload.get("mode") or "encode").lower()
        fmt = (payload.get("format") or self._settings.default_format).lower()
        if fmt not in {"json", "yaml", "pickle"}:
            raise LifecycleError("serialization-unsupported-format")

        # Log security warning when pickle format is used
        if fmt == "pickle":
            self._logger.warning(
                "pickle-format-security-warning",
                message="Using pickle format - ensure data is from trusted sources only",
                mode=mode,
            )

        if mode == "encode":
            return await self._encode(fmt, payload)
        if mode == "decode":
            return await self._decode(fmt, payload)
        raise LifecycleError("serialization-invalid-mode")

    async def _encode(self, fmt: str, payload: dict) -> dict:
        value = payload.get("value")
        if value is None and "data" in payload:
            value = payload["data"]
        if value is None:
            raise LifecycleError("serialization-value-required")
        sort_keys = payload.get("sort_keys")
        if sort_keys is None:
            sort_keys = self._settings.sort_keys
        ensure_ascii = payload.get("ensure_ascii")
        if ensure_ascii is None:
            ensure_ascii = self._settings.ensure_ascii
        if fmt == "json":
            text = json.dumps(value, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
            data_bytes = text.encode("utf-8")
        elif fmt == "yaml":
            text = yaml.safe_dump(value, sort_keys=sort_keys)
            data_bytes = text.encode("utf-8")
        else:
            # Security Note: pickle.dumps is used here for internal workflow serialization.
            # This format should ONLY be used with trusted data from internal sources.
            # For external/untrusted data, use JSON or YAML formats instead.
            text = None
            # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
            data_bytes = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        await self._maybe_write_path(payload.get("path"), data_bytes, fmt)
        self._logger.info("serialization-action-encoded", fmt=fmt, mode="encode")
        result = {
            "status": "encoded",
            "format": fmt,
        }
        if fmt in self._TEXT_FORMATS:
            result["text"] = text if text is not None else data_bytes.decode("utf-8")
        else:
            result["encoding"] = "base64"
            result["data"] = base64.b64encode(data_bytes).decode("ascii")
        return result

    async def _decode(self, fmt: str, payload: dict) -> dict:
        raw = await self._resolve_source(fmt, payload)
        if fmt == "json":
            text = raw.decode("utf-8")
            data = json.loads(text)
        elif fmt == "yaml":
            text = raw.decode("utf-8")
            data = yaml.safe_load(text)
        else:
            # Security Note: pickle.loads can execute arbitrary code.
            # This should ONLY deserialize data from trusted internal sources.
            # Never use pickle format with data from external or untrusted sources.
            # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
            data = pickle.loads(raw)
        self._logger.info("serialization-action-decoded", fmt=fmt, mode="decode")
        return {
            "status": "decoded",
            "format": fmt,
            "data": data,
        }

    async def _resolve_source(self, fmt: str, payload: dict) -> bytes:
        # Read from path if provided
        if path := payload.get("path"):
            return await self._read_path(path, fmt)

        # Extract value from payload
        value = self._extract_value_from_payload(payload)
        if value is None:
            raise LifecycleError("serialization-source-required")

        # Handle text formats
        if fmt in self._TEXT_FORMATS:
            return self._process_text_value(value)

        # Handle binary formats (pickle)
        return self._process_binary_value(value)

    def _extract_value_from_payload(self, payload: dict) -> Any:
        """Extract value from payload, checking multiple keys."""
        value = payload.get("data")
        if value is None and "text" in payload:
            value = payload["text"]
        if value is None and "value" in payload:
            value = payload["value"]
        return value

    def _process_text_value(self, value: Any) -> bytes:
        """Process value for text formats (JSON/YAML)."""
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        raise LifecycleError("serialization-text-required")

    def _process_binary_value(self, value: Any) -> bytes:
        """Process value for binary formats (pickle)."""
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            try:
                return base64.b64decode(value.encode("ascii"))
            except Exception as exc:  # pragma: no cover - invalid base64 path
                raise LifecycleError("serialization-b64-invalid") from exc
        raise LifecycleError("serialization-binary-required")

    async def _maybe_write_path(self, path_value: Any, data: bytes, fmt: str) -> None:
        if not path_value:
            return
        path = Path(path_value)
        if fmt in self._TEXT_FORMATS:
            text = data.decode("utf-8")
            await asyncio.to_thread(path.write_text, text, encoding="utf-8")
        else:
            await asyncio.to_thread(path.write_bytes, data)

    async def _read_path(self, path_value: Any, fmt: str) -> bytes:
        path = Path(path_value)
        if fmt in self._TEXT_FORMATS:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            return text.encode("utf-8")
        return await asyncio.to_thread(path.read_bytes)


__all__ = ["SerializationAction", "SerializationActionSettings"]
