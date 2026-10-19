"""Env-var back-compat tests for ``BifrostLLMSettings``.

REQ-BIFROST-011. The legacy ``MAHAVISHNU_BIFROST__*`` prefix keeps
working via a back-compat shim. The shim emits one ``DeprecationWarning``
AND one structured INFO log line ``legacy_env_prefix_in_use`` with
``prefix`` and ``operator`` fields (security F-06 fix —
``DeprecationWarning`` is silent in production, so the log is the
operator-visible surface).
"""

from __future__ import annotations

import os
import warnings

import pytest
import structlog

from oneiric.adapters.llm.bifrost import BifrostLLMSettings


@pytest.fixture(autouse=True)
def _clear_bifrost_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every BIFROST env var so tests don't see operator shell state."""
    for key in list(os.environ):
        if key.startswith("ONEIRIC_BIFROST_") or key.startswith(
            "MAHAVISHNU_BIFROST__"
        ):
            monkeypatch.delenv(key, raising=False)


def test_legacy_prefix_applies_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting ``MAHAVISHNU_BIFROST__*`` populates the settings fields."""
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ENABLED", "true")
    monkeypatch.setenv("MAHAVISHNU_BIFROST__BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ANTHROPIC_BASE_URL", "http://127.0.0.1:9999/anthropic")
    monkeypatch.setenv("MAHAVISHNU_BIFROST__CALLER_ID", "test-operator")

    with warnings.catch_warnings():
        warnings.simplefilter("always")
        s = BifrostLLMSettings()

    assert s.enabled is True
    assert s.base_url.host == "127.0.0.1"
    # Pydantic v2 HttpUrl.port is an int (not a str).
    assert s.base_url.port == 9999
    assert s.anthropic_base_url.port == 9999
    assert s.caller_id == "test-operator"


def test_legacy_prefix_emits_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-BIFROST-011: a single ``DeprecationWarning`` is emitted."""
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ENABLED", "true")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        BifrostLLMSettings()

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1
    assert "MAHAVISHNU_BIFROST" in str(deprecations[0].message)


def test_legacy_prefix_emits_structured_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-BIFROST-011 + security F-06: a single ``legacy_env_prefix_in_use``
    INFO log line is emitted with ``prefix`` and ``operator`` fields.
    """
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ENABLED", "true")
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        with structlog.testing.capture_logs() as captured:
            BifrostLLMSettings()

    legacy_logs = [
        entry
        for entry in captured
        if entry.get("event") == "legacy_env_prefix_in_use"
    ]
    assert len(legacy_logs) == 1
    assert legacy_logs[0]["prefix"] == "MAHAVISHNU_BIFROST__"
    assert legacy_logs[0]["log_level"] == "info"
    # operator identity is recorded
    assert legacy_logs[0].get("operator")


def test_new_prefix_silences_legacy_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``ONEIRIC_BIFROST_*`` is set, the legacy shim does not run
    and no deprecation is emitted. (We can't fully verify "shim did not
    run" from outside, but no warning + no log is the observable signal.)
    """
    # Pydantic v2 BaseSettings with env_prefix="ONEIRIC_BIFROST_" looks
    # for ONEIRIC_BIFROST_ENABLED (single underscore before the field
    # name, NOT the doubled "__" the plan's validation matrix example
    # shows — that's a typo in the plan text). The shim's env-var
    # detection only fires when ONEIRIC_BIFROST_* env vars are absent.
    monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with structlog.testing.capture_logs() as captured:
            s = BifrostLLMSettings()

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations == []

    legacy_logs = [
        entry
        for entry in captured
        if entry.get("event") == "legacy_env_prefix_in_use"
    ]
    assert legacy_logs == []

    # The new-prefix value was applied (not overridden by legacy)
    assert s.enabled is True


def test_legacy_routes_field_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``routes`` field accepts a comma-separated env-var string."""
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ENABLED", "true")
    monkeypatch.setenv(
        "MAHAVISHNU_BIFROST__ROUTES", "claude_route,qwen_route"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        s = BifrostLLMSettings()

    assert s.enabled is True
    assert "claude_route" in s.routes
    assert "qwen_route" in s.routes


def test_legacy_bool_coercion(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``enabled`` / ``local_provider_enabled`` fields are coerced from
    string env vars to bool (handles 'true'/'false'/'1'/'0'/'yes'/'on').
    """
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ENABLED", "true")
    monkeypatch.setenv("MAHAVISHNU_BIFROST__LOCAL_PROVIDER_ENABLED", "1")
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        s = BifrostLLMSettings()

    assert s.enabled is True
    assert s.local_provider_enabled is True


def test_legacy_int_coercion(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``cache_ttl_seconds`` field is coerced from string env var to int."""
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ENABLED", "true")
    monkeypatch.setenv("MAHAVISHNU_BIFROST__CACHE_TTL_SECONDS", "3600")
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        s = BifrostLLMSettings()

    assert s.cache_ttl_seconds == 3600


def test_legacy_int_empty_string_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty ``MAHAVISHNU_BIFROST__CACHE_TTL_SECONDS=`` value does not
    raise — the Pydantic default ``0`` wins (3-agent MED finding)."""
    monkeypatch.setenv("MAHAVISHNU_BIFROST__ENABLED", "true")
    monkeypatch.setenv("MAHAVISHNU_BIFROST__CACHE_TTL_SECONDS", "")
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        s = BifrostLLMSettings()

    assert s.cache_ttl_seconds == 0


def test_new_prefix_routes_via_comma_separated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The BLOCKER fix: Pydantic v2 does not natively split comma-separated
    values for ``set[StrEnum]``. The field_validator on ``routes`` handles
    this for the new env prefix path (the legacy shim was already doing it
    manually). The general-purpose review caught this gap because the
    legacy shim short-circuits when the new prefix is set.
    """
    monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
    monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", "claude_route,qwen_route")
    s = BifrostLLMSettings()
    assert "claude_route" in s.routes
    assert "qwen_route" in s.routes


def test_new_prefix_routes_single_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-value routes env var (no comma) also works."""
    monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
    monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", "claude_route")
    s = BifrostLLMSettings()
    assert "claude_route" in s.routes


def test_model_dump_supports_dict_form_exclude() -> None:
    """The ``IncEx`` widening supports the Pydantic v2 dict-form exclusion.

    Both agents flagged that narrowing ``exclude`` to ``set[str] | None``
    would break callers using dict-form exclusion. This test pins the
    wider contract.
    """
    s = BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    dumped = s.model_dump(exclude={"auth_env": True})
    assert "auth_env" not in dumped


def test_model_dump_explicit_dict_merges_sensitive() -> None:
    """A non-empty dict-form ``exclude`` still applies the ``_SENSITIVE_FIELDS``
    merge, so ``auth_env`` is excluded even when the caller's dict doesn't
    mention it.
    """
    s = BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    dumped = s.model_dump(exclude={"caller_id": True})
    # caller-supplied
    assert "caller_id" not in dumped
    # auto-merged from _SENSITIVE_FIELDS
    assert "auth_env" not in dumped
