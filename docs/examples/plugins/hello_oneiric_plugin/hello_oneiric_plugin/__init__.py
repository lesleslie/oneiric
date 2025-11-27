"""Hello Oneiric plugin entry points."""

from __future__ import annotations

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.resolution import Candidate


def adapter_entries() -> list[AdapterMetadata]:
    """Return adapter metadata payloads registered via entry point."""

    return [
        AdapterMetadata(
            category="cache",
            provider="hello.entrypoint",
            stack_level=20,
            description="Sample cache adapter from the hello plugin.",
            factory=lambda: _HelloAdapter(),
        )
    ]


def service_entries() -> list[Candidate]:
    """Return service candidates registered via entry point."""

    return [
        Candidate(
            domain="service",
            key="hello-status",
            provider="hello.entrypoint",
            stack_level=10,
            factory=lambda: _HelloService(),
        )
    ]


class _HelloAdapter:
    def handle(self) -> str:
        return "hello-from-plugin"


class _HelloService:
    def status(self) -> str:
        return "hello-service-ok"
