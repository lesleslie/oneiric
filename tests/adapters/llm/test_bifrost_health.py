"""``/health.bifrost.config`` exclusion tests for ``BifrostLLMSettings``.

REQ-BIFROST-017 + 3-agent security F-02 / F-07 fixes. The
``_SENSITIVE_FIELDS: frozenset`` centralizes the exclusion list, and
``model_dump`` / ``model_dump_json`` overrides apply it by default so
the ``/health.bifrost.config`` probe never serializes ``auth_env``.

The security F-07 fix additionally redacts non-loopback URLs in
unauthenticated ``/health`` responses. That redaction is wired by
Phase 7's call-site rewrite — the oneiric-side contract is the
exclusion of ``_SENSITIVE_FIELDS``, which the Phase 7 call sites
will chain with the loopback check.
"""

from __future__ import annotations

import json

import pytest

from oneiric.adapters.llm.bifrost import BifrostLLMSettings


# ---------------------------------------------------------------------------
# model_dump excludes _SENSITIVE_FIELDS by default
# ---------------------------------------------------------------------------


def test_auth_env_excluded_default() -> None:
    """``auth_env`` is excluded from ``model_dump()`` by default."""
    s = BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    dumped = s.model_dump()
    assert "auth_env" not in dumped
    # Other fields are still present
    assert "enabled" in dumped
    assert "base_url" in dumped


def test_model_dump_json_also_excludes_auth_env() -> None:
    """The JSON path also excludes ``auth_env`` by default."""
    s = BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    as_json = s.model_dump_json()
    parsed = json.loads(as_json)
    assert "auth_env" not in parsed


def test_dict_via_model_dump_excludes_auth_env() -> None:
    """The ``dict()`` shape (which goes through ``model_dump``) also excludes."""
    s = BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    as_dict = s.model_dump()
    assert "auth_env" not in as_dict


# ---------------------------------------------------------------------------
# Explicit opt-in to inclusion
# ---------------------------------------------------------------------------


def test_exclude_set_opts_in_to_inclusion() -> None:
    """``model_dump(exclude=set())`` is the explicit opt-in to inclusion.

    The override preserves the ``exclude`` parameter for callers that
    genuinely need the field (e.g. operator debug tooling, audit log
    export) — but they must say so explicitly.
    """
    s = BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    dumped = s.model_dump(exclude=set())
    assert "auth_env" in dumped
    assert dumped["auth_env"] == "MAHAVISHNU_BIFROST_AUTH_TOKEN"


def test_exclude_set_in_json_path() -> None:
    """Same opt-in semantics for ``model_dump_json``."""
    s = BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    as_json = s.model_dump_json(exclude=set())
    parsed = json.loads(as_json)
    assert parsed["auth_env"] == "MAHAVISHNU_BIFROST_AUTH_TOKEN"


# ---------------------------------------------------------------------------
# Caller-supplied exclude is unioned with _SENSITIVE_FIELDS
# ---------------------------------------------------------------------------


def test_caller_exclude_unioned_with_sensitive() -> None:
    """A non-empty ``exclude`` set is unioned with ``_SENSITIVE_FIELDS``."""
    s = BifrostLLMSettings(
        auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN",
        enabled=True,
    )
    dumped = s.model_dump(exclude={"enabled"})
    # Both 'enabled' (caller-supplied) and 'auth_env' (sensitive) are gone
    assert "enabled" not in dumped
    assert "auth_env" not in dumped
    # Other fields survive
    assert "base_url" in dumped


# ---------------------------------------------------------------------------
# _SENSITIVE_FIELDS contract
# ---------------------------------------------------------------------------


def test_sensitive_fields_is_frozenset() -> None:
    """The centralized exclusion list is a frozenset (immutable)."""
    assert isinstance(BifrostLLMSettings._SENSITIVE_FIELDS, frozenset)


def test_sensitive_fields_contains_auth_env() -> None:
    """``auth_env`` is the only currently-sensitive field."""
    assert "auth_env" in BifrostLLMSettings._SENSITIVE_FIELDS
