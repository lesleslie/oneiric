"""Pin ``arbitrary_types_allowed=True`` round-trip on the ``auth`` field (Phase 4.7a).

``OneiricMCPAuthConfig`` is a stdlib ``@dataclass``. Pydantic v2 normally
rejects arbitrary non-BaseModel fields; the ``model_config`` flag is
required to construct ``OneiricSettings`` at all, and the round-trip
through ``model_dump()`` / ``model_validate()`` must preserve every
dataclass field without coercion errors.
"""

from __future__ import annotations

import pytest

from oneiric.core.config import OneiricSettings
from oneiric.mcp.config import OneiricMCPAuthConfig


class TestArbitraryTypesRoundTrip:
    def test_auth_default_is_dataclass(self) -> None:
        settings = OneiricSettings()
        assert isinstance(settings.auth, OneiricMCPAuthConfig)

    def test_model_dump_preserves_auth(self) -> None:
        settings = OneiricSettings()
        dumped = settings.model_dump()
        assert "auth" in dumped
        # ``model_dump`` returns the dataclass as a dict (pydantic's
        # default behavior for arbitrary types). Verify the
        # structural shape round-trips.
        assert isinstance(dumped["auth"], dict)
        assert dumped["auth"]["enabled"] is False
        assert dumped["auth"]["default_provider"] is None
        assert dumped["auth"]["trusted_issuers"] == []
        assert dumped["auth"]["providers"] == {}

    def test_model_validate_round_trip(self) -> None:
        settings = OneiricSettings()
        dumped = settings.model_dump()
        # Re-validate from the dumped dict — must succeed and yield
        # the same observable shape.
        rebuilt = OneiricSettings.model_validate(dumped)
        assert isinstance(rebuilt.auth, OneiricMCPAuthConfig)
        assert rebuilt.auth.enabled is False
        assert rebuilt.auth.default_provider is None
        assert rebuilt.auth.trusted_issuers == []
        assert rebuilt.auth.providers == {}

    def test_dataclass_field_is_required_to_have_arbitrary_types_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sanity: the ``OneiricSettings`` ``model_config`` MUST have
        ``arbitrary_types_allowed=True`` or model construction will
        raise ``TypeError``. Pin so a future refactor that drops the
        flag (e.g., by switching the auth field to a Pydantic model)
        gets caught here rather than at consumer import time.
        """
        assert (
            OneiricSettings.model_config.get("arbitrary_types_allowed") is True
        )
