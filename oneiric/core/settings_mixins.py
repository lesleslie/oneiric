"""Reusable settings fragments."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, Field


class BaseURLSettings(BaseModel):
    base_url: AnyHttpUrl | None = Field(
        default=None, description="Optional base URL for outbound requests."
    )


class TimeoutSettings(BaseModel):
    timeout: float = Field(
        default=10.0, ge=0.5, description="Request timeout in seconds."
    )
