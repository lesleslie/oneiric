"""Pin ``OneiricManifestSource`` behavior (Phase 4.7a, migration plan §4.7a).

The source returns an empty dict when no manifest URL is configured, reads
the cached manifest YAML at ``{cache_dir}/manifest.yaml`` when present,
and silently swallows parse errors so a malformed cache file does not
break settings load. Pinned here so future cache-layout changes surface
as test failures rather than silent prod drift.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from oneiric.core._sources import OneiricManifestSource
from oneiric.core.config import OneiricSettings


def _settings_cls_stub() -> type[OneiricSettings]:
    """Return a throwaway subclass — OneiricManifestSource only reads it for
    parent class machinery; we never need a real per-project build.
    """

    class _Stub(OneiricSettings):
        pass

    return _Stub


class TestOneiricManifestSource:
    def test_no_op_when_cache_dir_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No cache_dir → empty dict. The source must never raise."""
        monkeypatch.delenv("ONEIRIC_CONFIG", raising=False)
        source = OneiricManifestSource(_settings_cls_stub(), cache_dir=None)
        assert source() == {}

    def test_no_op_when_manifest_file_missing(self, tmp_path: Path) -> None:
        """cache_dir set, but no manifest.yaml on disk → empty dict."""
        source = OneiricManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
        assert source() == {}

    def test_reads_cached_manifest(self, tmp_path: Path) -> None:
        """A valid manifest.yaml on disk → parsed payload is returned flat."""
        (tmp_path / "manifest.yaml").write_text(
            dedent(
                """
                adapters:
                  llm:
                    openai:
                      provider: openai
                      api_key: cached-key
                """
            ).lstrip()
        )
        source = OneiricManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
        payload = source()
        assert payload == {
            "adapters": {
                "llm": {"openai": {"provider": "openai", "api_key": "cached-key"}}
            }
        }

    def test_swallows_invalid_yaml(self, tmp_path: Path) -> None:
        """A malformed cache file must NOT propagate exceptions — the
        settings loader treats OneiricManifestSource as best-effort.
        """
        (tmp_path / "manifest.yaml").write_text("::: not yaml :::\n  - [bad")
        source = OneiricManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
        assert source() == {}

    def test_non_dict_payload_returns_empty(self, tmp_path: Path) -> None:
        """A YAML scalar/list at the top level is not a settings payload;
        return empty dict so the merge is a no-op rather than a TypeError.
        """
        (tmp_path / "manifest.yaml").write_text("- one\n- two\n")
        source = OneiricManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
        assert source() == {}

    def test_falls_back_to_class_attribute_cache_dir(
        self, tmp_path: Path
    ) -> None:
        """When the constructor receives no ``cache_dir``, the source
        falls back to ``settings_cls.oneiric_cache_dir`` (a ClassVar
        populated by ``build_oneiric_settings._Project`` or a
        downstream caller). Pin the wiring so the chain can opt in
        to a real cache by setting the class attribute, without
        needing to refactor the chain construction.
        """
        from typing import ClassVar

        class _WithCacheDir(OneiricSettings):
            oneiric_cache_dir: ClassVar[Path] = tmp_path

        (tmp_path / "manifest.yaml").write_text(
            "adapters:\n  llm:\n    openai: {}\n"
        )
        source = OneiricManifestSource(_WithCacheDir)  # no cache_dir kwarg
        assert source() == {"adapters": {"llm": {"openai": {}}}}

    def test_strip_auth_also_removes_profile(
        self, tmp_path: Path
    ) -> None:
        """``strip_auth`` strips both ``auth:`` and ``profile:`` keys per
        the Phase 1 amendment (avoids ``SettingsError`` on
        ``ONEIRIC_PROFILE=serverless``). Pin both keys so a regression
        on either is caught.
        """
        from oneiric.core._sources import strip_auth

        # auth as a dict value (nested-delimiter form) → popped
        assert strip_auth({"auth": {"enabled": "true"}, "other": 1}) == {
            "other": 1
        }
        # profile as a dict value → popped
        assert strip_auth({"profile": {"name": "x"}, "other": 1}) == {
            "other": 1
        }
        # auth as non-dict value (e.g. raw env-var JSON) → not popped
        # (the value isn't a dict so the strip pass leaves it; this
        # is intentional — env-source would still pass through a
        # non-dict value to dataclass coercion, which is a separate
        # concern handled by the __call__ override + get_field_value
        # return-None on the top-level field)
        assert strip_auth({"auth": "raw-string", "other": 1}) == {
            "auth": "raw-string",
            "other": 1,
        }
        # Neither key present → identity
        assert strip_auth({"other": 1}) == {"other": 1}
