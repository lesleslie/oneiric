"""Pin the nested-BaseSettings sharp edge on ``observability`` (Phase 4.7a).

``OneiricSettings.observability`` is a nested ``OTelStorageSettings``
(itself a ``BaseSettings``). Pydantic-settings' nested-delimiter
(``__``) should resolve ``ONEIRIC_OBSERVABILITY__CONNECTION_STRING=...``
to ``settings.observability.connection_string``. Without the nested
field, the env var would land in ``__pydantic_extra__`` and consumers
would silently fall back to defaults.

This test pins the "nested BaseSettings in BaseSettings" idiom so
future substrate changes do not silently regress it.
"""

from __future__ import annotations

import pytest

from oneiric.adapters.observability.settings import OTelStorageSettings
from oneiric.core.config import OneiricSettings


def _clear_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ONEIRIC_OBSERVABILITY__CONNECTION_STRING",
        "ONEIRIC_OBSERVABILITY__EMBEDDING_MODEL",
        "ONEIRIC_OBSERVABILITY",
        "ONEIRIC_OTEL_STORAGE__CONNECTION_STRING",
        "ONEIRIC_OTEL_STORAGE__EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


class TestNestedBaseSettings:
    def test_default_observability_is_typed_submodel(self) -> None:
        settings = OneiricSettings()
        assert isinstance(settings.observability, OTelStorageSettings)

    def test_observability_nested_delimiter_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_OBSERVABILITY__CONNECTION_STRING`` flows into the
        nested ``OTelStorageSettings.connection_string``. This is the
        exact contract the migration plan §1.7 promises.
        """
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv(
            "ONEIRIC_OBSERVABILITY__CONNECTION_STRING",
            "postgresql://user:pw@host/db",
        )
        settings = OneiricSettings()
        assert (
            settings.observability.connection_string
            == "postgresql://user:pw@host/db"
        )

    def test_observability_embedding_model_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second nested field to confirm the delimiter isn't a one-off."""
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv(
            "ONEIRIC_OBSERVABILITY__EMBEDDING_MODEL", "all-mpnet-base-v2"
        )
        settings = OneiricSettings()
        assert settings.observability.embedding_model == "all-mpnet-base-v2"

    def test_unrelated_env_var_raises_settings_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare ``ONEIRIC_OBSERVABILITY`` (no ``__`` delimiter) is
        treated by pydantic-settings as a complex-value payload
        for the ``observability`` field, JSON-decoded, and rejected
        because ``"should-be-ignored"`` is not valid JSON. Pin the
        known sharp edge: operators must use the ``__`` nested
        delimiter, not the bare field name.
        """
        from pydantic_settings import SettingsError

        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_OBSERVABILITY", "should-be-ignored")
        with pytest.raises(SettingsError):
            OneiricSettings()
