"""Pin ``BodaiManifestSource`` behavior (Phase 4.7a, migration plan §4.7a).

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

from oneiric.core._sources import BodaiManifestSource
from oneiric.core.config import OneiricSettings


def _settings_cls_stub() -> type[OneiricSettings]:
    """Return a throwaway subclass — BodaiManifestSource only reads it for
    parent class machinery; we never need a real per-project build.
    """

    class _Stub(OneiricSettings):
        pass

    return _Stub


class TestBodaiManifestSource:
    def test_no_op_when_cache_dir_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No cache_dir → empty dict. The source must never raise."""
        monkeypatch.delenv("ONEIRIC_CONFIG", raising=False)
        source = BodaiManifestSource(_settings_cls_stub(), cache_dir=None)
        assert source() == {}

    def test_no_op_when_manifest_file_missing(self, tmp_path: Path) -> None:
        """cache_dir set, but no manifest.yaml on disk → empty dict."""
        source = BodaiManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
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
        source = BodaiManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
        payload = source()
        assert payload == {
            "adapters": {
                "llm": {"openai": {"provider": "openai", "api_key": "cached-key"}}
            }
        }

    def test_swallows_invalid_yaml(self, tmp_path: Path) -> None:
        """A malformed cache file must NOT propagate exceptions — the
        settings loader treats BodaiManifestSource as best-effort.
        """
        (tmp_path / "manifest.yaml").write_text("::: not yaml :::\n  - [bad")
        source = BodaiManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
        assert source() == {}

    def test_non_dict_payload_returns_empty(self, tmp_path: Path) -> None:
        """A YAML scalar/list at the top level is not a settings payload;
        return empty dict so the merge is a no-op rather than a TypeError.
        """
        (tmp_path / "manifest.yaml").write_text("- one\n- two\n")
        source = BodaiManifestSource(_settings_cls_stub(), cache_dir=tmp_path)
        assert source() == {}
