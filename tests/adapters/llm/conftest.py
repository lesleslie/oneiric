"""Shared fixtures for the bifrost router tests.

REQ-BIFROST-018 (3-agent type F6 + security F-11 fix): the
``reset_router_for_tests`` helper exists in
``oneiric.adapters.llm.bifrost`` so test ordering cannot pollute
the singleton state. The autouse fixture below clears the cache
before AND after every test for belt-and-braces safety.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from oneiric.adapters.llm.bifrost import reset_router_for_tests


@pytest.fixture(autouse=True)
def _reset_bifrost_router_singleton() -> Generator[None, None, None]:
    """Clear the ``get_router()`` singleton cache between tests."""
    reset_router_for_tests()
    yield
    reset_router_for_tests()
