"""Demo components for testing and examples."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DemoAdapter:
    """Demo adapter for testing."""

    greeting: str = "Hello from demo adapter"

    def handle(self) -> str:
        return self.greeting


@dataclass
class RedisAdapter:
    """Demo Redis adapter for testing."""

    host: str = "localhost"
    port: int = 6379

    def connect(self) -> dict:
        return {"host": self.host, "port": self.port, "connected": True}


@dataclass
class MemcachedAdapter:
    """Demo Memcached adapter for testing."""

    servers: list[str] = None

    def __post_init__(self):
        if self.servers is None:
            self.servers = ["localhost:11211"]

    def get(self, key: str) -> None:
        return None

    def set(self, key: str, value: str) -> bool:
        return True


def demo_factory() -> DemoAdapter:
    """Factory function for creating demo adapters."""
    return DemoAdapter(greeting="Created by factory")
