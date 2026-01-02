from __future__ import annotations

from importlib import metadata

from .demo import DemoAdapter

__all__ = ["DemoAdapter", "__version__"]

try:
    __version__ = metadata.version("oneiric")
except metadata.PackageNotFoundError:  # pragma: no cover - fallback for local dev
    __version__ = "0.0.0"
