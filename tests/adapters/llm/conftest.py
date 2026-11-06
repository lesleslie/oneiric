"""Shared fixtures for the bifrost router tests.

REQ-BIFROST-018 (3-agent type F6 + security F-11 fix): the
``reset_router_for_tests`` helper exists in
``oneiric.adapters.llm.bifrost`` so test ordering cannot pollute
the singleton state. The autouse fixture below clears the cache
before AND after every test for belt-and-braces safety.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

from oneiric.adapters.llm.bifrost import reset_router_for_tests


@pytest.fixture(autouse=True)
def _reset_bifrost_router_singleton() -> Generator[None]:
    """Clear the ``get_router()`` singleton cache between tests."""
    reset_router_for_tests()
    yield
    reset_router_for_tests()


@pytest.fixture(autouse=True)
def _clear_bifrost_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every BIFROST env var so tests don't see operator shell state.

    This lives in the shared conftest rather than in one test module
    because the leak is ambient: an operator shell exporting
    ``ONEIRIC_BIFROST_ENABLED`` or ``ONEIRIC_BIFROST_ANTHROPIC_BASE_URL``
    silently changes what the router resolves, in every test file that
    touches it. A test asserting "the defaults" must not be decided by
    whatever the developer's shell happened to export.
    """
    for key in list(os.environ):
        if key.startswith(("ONEIRIC_BIFROST_", "MAHAVISHNU_BIFROST__")):
            monkeypatch.delenv(key, raising=False)
