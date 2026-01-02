"""Runtime cache management for MCP servers."""

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
    """Cache entry data structure."""

    key: str
    value: Any
    timestamp: float
    ttl: float | None = None  # Time-to-live in seconds

    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        if self.ttl is None:
            return False
        return time.time() > self.timestamp + self.ttl

    def to_dict(self) -> dict[str, Any]:
        """Convert cache entry to dictionary."""
        return {
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEntry:
        """Create cache entry from dictionary."""
        return cls(
            key=data["key"],
            value=data["value"],
            timestamp=data["timestamp"],
            ttl=data.get("ttl"),
        )


class RuntimeCacheManager:
    """Manages runtime cache for MCP servers."""

    def __init__(
        self,
        cache_dir: str = ".oneiric_cache",
        server_name: str = "mcp-server",
        max_entries: int = 1000,
        default_ttl: float | None = 3600,  # 1 hour default TTL
    ):
        self.cache_dir = Path(cache_dir)
        self.server_name = server_name
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self.cache_file = self.cache_dir / f"{server_name}_cache.json"
        self.cache: dict[str, CacheEntry] = {}
        self.initialized = False

    async def initialize(self) -> None:
        """Initialize cache manager."""
        logger.info(f"Initializing RuntimeCacheManager for {self.server_name}")

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(exist_ok=True)

        # Load cache from disk if it exists
        await self._load_cache()

        self.initialized = True
        logger.info(f"Cache manager initialized: {self.cache_file}")

    async def _load_cache(self) -> None:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with self.cache_file.open(encoding="utf-8") as f:
                    data = json.load(f)
                    self.cache = {}

                    for entry_data in data:
                        try:
                            entry = CacheEntry.from_dict(entry_data)
                            # Only add non-expired entries
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
        """Set a value in the cache."""
        if not self.initialized:
            await self.initialize()

        # Use default TTL if not specified
        if ttl is None:
            ttl = self.default_ttl

        entry = CacheEntry(key=key, value=value, timestamp=time.time(), ttl=ttl)

        self.cache[key] = entry

        # Save cache to disk
        await self._save_cache()

        # Clean up expired entries
        await self._cleanup_expired_entries()

        logger.debug(f"Cache set: {key}")

    async def get(self, key: str) -> Any | None:
        """Get a value from the cache."""
        if not self.initialized:
            await self.initialize()

        entry = self.cache.get(key)

        if entry is None:
            return None

        # Check if entry is expired
        if entry.is_expired():
            await self.delete(key)
            return None

        logger.debug(f"Cache hit: {key}")
        return entry.value

    async def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        if not self.initialized:
            await self.initialize()

        if key in self.cache:
            del self.cache[key]
            await self._save_cache()
            logger.debug(f"Cache deleted: {key}")
            return True

        return False

    async def clear(self) -> None:
        """Clear the entire cache."""
        self.cache = {}
        await self._save_cache()
        logger.info("Cache cleared")

    async def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            # Convert cache entries to serializable format
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
        """Clean up expired cache entries."""
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
        """Get cache statistics."""
        return {
            "total_entries": len(self.cache),
            "max_entries": self.max_entries,
            "cache_file": str(self.cache_file),
            "initialized": self.initialized,
        }

    async def cleanup(self) -> None:
        """Clean up cache manager resources."""
        logger.info(f"Cleaning up RuntimeCacheManager for {self.server_name}")

        # Save final cache state
        await self._save_cache()

        # Clear in-memory cache
        self.cache = {}
        self.initialized = False


__all__ = ["RuntimeCacheManager", "CacheEntry"]
