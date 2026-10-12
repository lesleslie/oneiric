"""Pin ``auth`` field exclusion from the env-source chain (Phase 4.7a).

``OneiricMCPAuthConfig`` is a stdlib ``@dataclass``; pydantic-settings
cannot decorate it for env-var / YAML merge. The custom
``_AuthExcludingEnvSource`` / ``_AuthExcludingYamlSource`` strip the
``auth:`` key from every source's payload, and the CLI applies the
``ONEIRIC_AUTH_*`` overlay via ``OneiricMCPAuthConfig.from_env()`` at
the call site. ``settings.auth`` must therefore be a *pure* field
default — env vars must not leak in.
"""

from __future__ import annotations

import pytest

from oneiric.core.config import OneiricSettings
from oneiric.mcp.config import OneiricMCPAuthConfig


def _clear_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ONEIRIC_CONFIG",
        "ONEIRIC_AUTH_ENABLED",
        "ONEIRIC_AUTH_DEFAULT_PROVIDER",
        "ONEIRIC_AUTH_TRUSTED_ISSUERS",
        "ONEIRIC_AUTH__ENABLED",
        "ONEIRIC_AUTH__DEFAULT_PROVIDER",
        "ONEIRIC_AUTH__TRUSTED_ISSUERS",
        "ONEIRIC_PROFILE",
    ):
        monkeypatch.delenv(key, raising=False)


class TestAuthFieldExclusion:
    def test_top_level_oneiric_auth_env_does_not_set_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_AUTH=`` (top-level, no ``__`` delimiter) is the
        path the ``_AuthExcludingEnvSource`` blocks. pydantic-settings
        would otherwise try to JSON-decode the env var as a dict and
        coerce it into the dataclass. Pin the top-level exclusion
        so the stdlib dataclass stays at field defaults.
        """
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_AUTH", '{"enabled": true}')
        settings = OneiricSettings()
        assert settings.auth.enabled is False  # dataclass default

    def test_auth_field_is_typed_dataclass(self) -> None:
        """The field is the stdlib dataclass, NOT a Pydantic model. This
        is why the custom exclusion is required in the first place.
        """
        settings = OneiricSettings()
        assert isinstance(settings.auth, OneiricMCPAuthConfig)

    def test_from_env_overlay_is_the_sole_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_AUTH_ENABLED`` (single-segment) is read by
        ``from_env()`` directly, not by pydantic-settings' env source.
        Pin both directions: env → dataclass via from_env(), and
        settings.auth.enabled stays at default until the CLI overlays.
        """
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_AUTH_ENABLED", "true")
        # The bare-settings view must NOT pick this up.
        settings = OneiricSettings()
        assert settings.auth.enabled is False
        # The from_env() channel DOES pick it up.
        overlay = OneiricMCPAuthConfig.from_env(raw={})
        assert overlay.enabled is True

    def test_yaml_auth_block_is_dropped_by_exclusion(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A project-layer ``auth:`` block MUST be dropped by
        ``_AuthExcludingYamlSource.strip_auth``. The CLI reads
        ``settings.auth`` (the typed field) and the YAML source
        must not double-merge it. If the exclusion regressed, the
        stdlib dataclass would receive a coerced dict and
        downstream ``from_env(raw=vars(settings.auth))`` would
        double-apply values.
        """
        _clear_oneiric_env(monkeypatch)
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "oneiric.yaml").write_text(
            "auth:\n  enabled: true\n  default_provider: oauth\n"
        )
        from oneiric.core.config import load_settings

        settings = load_settings(project_root=tmp_path, project_name="oneiric")
        # The dataclass stays at defaults — the YAML block was stripped.
        assert settings.auth.enabled is False
        assert settings.auth.default_provider is None
        # But the auth field IS still typed and present.
        assert isinstance(settings.auth, OneiricMCPAuthConfig)

    def test_nested_delimiter_env_does_not_leak_into_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_AUTH__ENABLED=true`` must NOT flip settings.auth.enabled.

        Pydantic-settings' nested-delimiter resolution walks the
        ``auth`` field for subkeys (``auth.enabled``) even when
        ``get_field_value`` returns None for the top-level. The
        ``_AuthExcludingEnvSource.__call__`` post-process strips the
        ``auth:`` key so the dataclass stays at defaults. Pins the
        plan §Phase 1 task 1.10 contract.
        """
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_AUTH__ENABLED", "true")
        settings = OneiricSettings()
        assert settings.auth.enabled is False

    def test_nested_delimiter_profile_does_not_leak(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_PROFILE=serverless`` must NOT raise ``SettingsError``.

        Without the post-hoc ``strip_auth`` on the env source, pydantic-
        settings tries to JSON-decode ``"serverless"`` for the complex
        ``profile`` field and raises. The strip drops ``profile:`` from
        the env payload; the CLI applies the profile via
        ``apply_profile_with_fallback`` at the call site.
        """
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_PROFILE", "serverless")
        settings = OneiricSettings()
        assert settings.profile.name == "default"
