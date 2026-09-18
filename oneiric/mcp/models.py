"""Pydantic input models for the oneiric FastMCP server tools.

Includes the BoundedMetadata type that addresses the
unbounded-input-disk-fill-dos security finding (REQ-005):
metadata is primitives-only with finite per-field caps.

Pydantic v2 note: we use ``RootModel`` (the canonical v2 way to express
"a value of this single type") rather than the deprecated
``class M(BaseModel): __root__: T`` v1 pattern. The ``BoundedMetadata``
class is a thin wrapper that lets ``model_validate(None)`` return
``None`` at input boundaries, which the tests expect.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, RootModel

# --- Bounded primitive + metadata types ---

# Constraints are encoded as Annotated metadata so they round-trip through
# Pydantic's serialization (visible in .model_json_schema()).

_BoundedStr = Annotated[
    str,
    Field(min_length=1, max_length=1024),
]

_BoundedKey = Annotated[
    str,
    Field(min_length=1, max_length=256),
]

BoundedPrimitive = RootModel[_BoundedStr | int | float | bool | None]
"""Metadata value: primitive only, no nested collections."""


# A RootModel of a constrained dict shape. The Field on the dict enforces
# the per-key and per-value caps transitively (each key/value is run
# through BoundedPrimitive validation), plus the 64-entry cap on the dict
# itself.
_BoundedDict = Annotated[
    dict[_BoundedKey, BoundedPrimitive],
    Field(max_length=64),
]

_BoundedMetadataRoot = RootModel[_BoundedDict]


class BoundedMetadata:
    """Optional metadata dict; primitives-only, ≤64 entries.

    Wraps a RootModel so the public type can accept ``None`` at input
    boundaries (Pydantic's RootModel doesn't have a clean ``None``
    default). Use ``BoundedMetadata.model_validate(value)``:

    - ``None`` -> returns ``None`` (the field-default shape)
    - ``dict`` -> returns a BoundedMetadata instance whose ``.root`` is
      the validated dict

    Iteration (``for k in m``), ``m[key]``, and ``len(m)`` are delegated
    to the underlying dict for ergonomic use inside tool handlers.
    """

    __slots__ = ("_root",)

    def __init__(self, value: dict[str, Any] | None = None) -> None:
        # Bypass validation here; callers should always go through
        # ``model_validate`` so the constraints run exactly once.
        # Unwrap any RootModel values back to plain Python primitives so
        # ``.root`` is a dict[str, str|int|float|bool|None] (test contract).
        if value is None:
            self._root: dict[str, Any] = {}
        else:
            self._root = {
                k: (v.root if isinstance(v, RootModel) else v) for k, v in value.items()
            }

    @property
    def root(self) -> dict[str, Any]:
        return self._root

    @classmethod
    def model_validate(
        cls,
        value: Any,
        *args: Any,
        **kwargs: Any,
    ) -> BoundedMetadata | None:
        if value is None:
            return None
        validated = _BoundedMetadataRoot.model_validate(value, *args, **kwargs)
        return cls(validated.root)

    def __iter__(self):
        return iter(self._root)

    def __getitem__(self, key: str) -> Any:
        return self._root[key]

    def __len__(self) -> int:
        return len(self._root)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BoundedMetadata):
            return self._root == other._root
        return NotImplemented

    def __repr__(self) -> str:
        return f"BoundedMetadata({self._root!r})"

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Pydantic-shaped serializer for substrate storage.

        SubstrateStore.write_*() calls ``payload.model_dump()`` on the parsed
        Pydantic input model. The ``metadata`` field is a ``BoundedMetadata``
        instance (not a plain dict); without this method the wrapper falls
        through to its ``__repr__`` and the on-disk JSON becomes a quoted
        string instead of a nested dict — silently breaking REQ-005's
        unbounded-DOS protection.

        Returns the validated dict (the same shape ``BoundedMetadata`` was
        constructed from). Extra kwargs are accepted for API compatibility
        with Pydantic's ``BaseModel.model_dump`` but are intentionally
        ignored — this wrapper is intentionally NOT a Pydantic model.
        """
        return self._root.copy()


# --- Substrate input models (T3) ---


def _coerce_bounded_metadata(value: Any) -> BoundedMetadata | None:
    """Route dict inputs through ``BoundedMetadata.model_validate``.

    Pydantic v2 cannot introspect ``BoundedMetadata`` (a custom class) for
    field validation; this BeforeValidator intercepts the value before
    Pydantic's type machinery runs.
    """
    if value is None:
        return None
    if isinstance(value, BoundedMetadata):
        return value
    return BoundedMetadata.model_validate(value)


_BoundedMetadataField = Annotated[
    Any,
    BeforeValidator(_coerce_bounded_metadata),
]


class ActiveSettingsVersionIn(BaseModel):
    """Body for the write_settings tool."""

    model_config = {"extra": "forbid"}

    version: str = Field(..., min_length=1, max_length=1024)
    source: str | None = Field(default=None, max_length=1024)
    metadata: _BoundedMetadataField = None


class ContextVersionIn(BaseModel):
    """Body for the write_context tool."""

    model_config = {"extra": "forbid"}

    tenant_id: str = Field(..., min_length=1, max_length=256)
    version: str = Field(..., min_length=1, max_length=1024)
    kind: str | None = Field(default=None, max_length=256)
    metadata: _BoundedMetadataField = None


class ProgressSnapshotIn(BaseModel):
    """Body for the write_progress tool."""

    model_config = {"extra": "forbid"}

    workflow_id: str = Field(..., min_length=1, max_length=256)
    stage: str = Field(..., min_length=1, max_length=256)
    percent: int = Field(..., ge=0, le=100)
    note: str | None = Field(default=None, max_length=1024)
    metadata: _BoundedMetadataField = None


__all__ = [
    "ActiveSettingsVersionIn",
    "BoundedMetadata",
    "BoundedPrimitive",
    "ContextVersionIn",
    "ProgressSnapshotIn",
]
