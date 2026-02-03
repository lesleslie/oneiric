from __future__ import annotations


class DemoAdapter:
    def __call__(self, *args: object, **kwargs: object) -> dict[str, str]:
        return {"type": "demo"}
