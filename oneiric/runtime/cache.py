from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oneiric.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    key: str
    value: Any
    timestamp: float
    ttl: float | None = None

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return time.time() > self.timestamp + self.ttl

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEntry:
        return cls(
            key=data["key"],
            value=data["value"],
            timestamp=data["timestamp"],
            ttl=data.get("ttl"),
        )


class RuntimeCacheManager:
    def __init__(
        self,
        cache_dir: str = ".oneiric_cache",
        server_name: str = "mcp-server",
        max_entries: int = 1000,
        default_ttl: float | None = 3600,
    ):
        self.cache_dir = Path(cache_dir)
        self.server_name = server_name
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self.cache_file = self.cache_dir / f"{server_name}_cache.json"
        self.cache: dict[str, CacheEntry] = {}
        self.initialized = False

    async def initialize(self) -> None:
        logger.info(f"Initializing RuntimeCacheManager for {self.server_name}")

        self.cache_dir.mkdir(exist_ok=True)

        await self._load_cache()

        self.initialized = True
        logger.info(f"Cache manager initialized: {self.cache_file}")

    async def _load_cache(self) -> None:
        if self.cache_file.exists():
            try:
                with self.cache_file.open(encoding="utf-8") as f:
                    data = json.load(f)
                    self.cache = {}

                    for entry_data in data:
                        try:
                            entry = CacheEntry.from_dict(entry_data)

                            if not entry.is_expired():
                                self.cache[entry.key] = entry
                        except (KeyError, TypeError) as e:
                            logger.error(f"Failed to load cache entry: {e}")

                logger.info(
                    f"Loaded {len(self.cache)} cache entries from {self.cache_file}"
                )
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"Failed to load cache {self.cache_file}: {e}")

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        if not self.initialized:
            await self.initialize()

        if ttl is None:
            ttl = self.default_ttl

        entry = CacheEntry(key=key, value=value, timestamp=time.time(), ttl=ttl)

        self.cache[key] = entry

        await self._save_cache()

        await self._cleanup_expired_entries()

        logger.debug(f"Cache set: {key}")

    async def get(self, key: str) -> Any | None:
        if not self.initialized:
            await self.initialize()

        entry = self.cache.get(key)

        if entry is None:
            return None

        if entry.is_expired():
            await self.delete(key)
            return None

        logger.debug(f"Cache hit: {key}")
        return entry.value

    async def delete(self, key: str) -> bool:
        if not self.initialized:
            await self.initialize()

        if key in self.cache:
            del self.cache[key]
            await self._save_cache()
            logger.debug(f"Cache deleted: {key}")
            return True

        return False

    async def clear(self) -> None:
        self.cache = {}
        await self._save_cache()
        logger.info("Cache cleared")

    async def _save_cache(self) -> None:
        try:
            cache_data = []
            for entry in self.cache.values():
                cache_data.append(entry.to_dict())

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)

            logger.debug(f"Cache saved to {self.cache_file}")
        except OSError as e:
            logger.error(f"Failed to save cache {self.cache_file}: {e}")
            raise

    async def _cleanup_expired_entries(self) -> None:
        expired_keys = []

        for key, entry in self.cache.items():
            if entry.is_expired():
                expired_keys.append(key)

        for key in expired_keys:
            del self.cache[key]
            logger.debug(f"Cache expired entry removed: {key}")

        if expired_keys:
            await self._save_cache()

    async def get_cache_stats(self) -> dict[str, Any]:
        return {
            "total_entries": len(self.cache),
            "max_entries": self.max_entries,
            "cache_file": str(self.cache_file),
            "initialized": self.initialized,
        }

    async def cleanup(self) -> None:
        logger.info(f"Cleaning up RuntimeCacheManager for {self.server_name}")

        await self._save_cache()

        self.cache = {}
        self.initialized = False


__all__ = ["RuntimeCacheManager", "CacheEntry"]
