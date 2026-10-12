"""Pin ``build_oneiric_settings`` memoization (Phase 4.7a, migration plan §4.7a).

The factory memoizes per-(project_name, project_root) so repeated
``load_settings(project_name=..., project_root=...)`` calls reuse the
same subclass and pydantic-settings' per-class ``env_prefix`` config is
not re-declared. Distinct projects / distinct roots must produce
distinct subclasses so their env vars don't cross-contaminate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oneiric.core.build_settings import (
    build_oneiric_settings,
    clear_project_settings_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Tests assert on memoization identity; start every test from a
    clean cache so the order of test execution does not matter.
    """
    clear_project_settings_cache()


class TestBuildOneiricSettingsMemoization:
    def test_same_args_return_same_class(self) -> None:
        a = build_oneiric_settings("oneiric")
        b = build_oneiric_settings("oneiric")
        assert a is b

    def test_different_names_return_distinct_classes(self) -> None:
        a = build_oneiric_settings("oneiric")
        b = build_oneiric_settings("mahavishnu")
        assert a is not b

    def test_different_roots_return_distinct_classes(self, tmp_path: Path) -> None:
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        root_a.mkdir()
        root_b.mkdir()
        a = build_oneiric_settings("oneiric", project_root=root_a)
        b = build_oneiric_settings("oneiric", project_root=root_b)
        assert a is not b

    def test_env_prefix_bound_to_project_name(self) -> None:
        """The factory's whole reason for existing: a per-project env_prefix
        so ``ONEIRIC_*`` does not flow into ``MahavishnuSettings`` and vice
        versa. Pin the prefix on the returned class's model_config.
        """
        cls = build_oneiric_settings("mahavishnu")
        assert cls.model_config["env_prefix"] == "MAHAVISHNU_"
        cls2 = build_oneiric_settings("akosha")
        assert cls2.model_config["env_prefix"] == "AKOSHA_"

    def test_clear_project_settings_cache_resets_memoization(
        self, tmp_path: Path
    ) -> None:
        a = build_oneiric_settings("oneiric", project_root=tmp_path)
        clear_project_settings_cache()
        b = build_oneiric_settings("oneiric", project_root=tmp_path)
        # Different class objects — the cache is the only thing that
        # made the previous call's subclass survive.
        assert a is not b

    def test_nested_delimiter_is_underscore_double(
        self, tmp_path: Path
    ) -> None:
        """Nested scalar fields become reachable via ``{PREFIX}_{SECTION}__{FIELD}``."""
        cls = build_oneiric_settings("oneiric", project_root=tmp_path)
        assert cls.model_config["env_nested_delimiter"] == "__"
