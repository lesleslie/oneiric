"""Demo components for testing and examples."""

from __future__ import annotations


class DemoAdapter:
    """Minimal demo adapter used by tests and examples."""

    def __call__(self, *args: object, **kwargs: object) -> dict[str, str]:
        return {"type": "demo"}
