"""Phase 0 infrastructure health gate.

REQ-BIFROST-018 (Phase 0). Before adding a new adapter to the
oneiric catalog, confirm the existing catalog is healthy — the
``builtin_adapter_metadata()`` list loads without error, the eager
import path on ``oneiric.adapters.bootstrap`` works in a clean venv,
and the existing LLM adapters (``AnthropicLLM``, ``OpenAILLMAdapter``)
have valid ``AdapterMetadata``.

This test runs as part of the regular test suite. If it ever fails,
Phase 1 should be blocked until the underlying oneiric infrastructure
is fixed — adding a new adapter on top of a broken catalog is a
silent regression.
"""

from __future__ import annotations

from oneiric.adapters.bootstrap import (
    builtin_adapter_metadata,
    register_builtin_adapters,
)
from oneiric.adapters.llm.anthropic import AnthropicLLM
from oneiric.adapters.llm.openai import OpenAILLMAdapter
from oneiric.core.resolution import Resolver


def test_builtin_metadata_loads() -> None:
    """The catalog loads without raising — eager imports succeed."""
    metadata = builtin_adapter_metadata()
    assert len(metadata) >= 57  # the pre-Phase-1 catalog count


def test_anthropic_metadata_present() -> None:
    """``AnthropicLLM`` is in the catalog (the reference shape the new
    router mirrors per REQ-BIFROST-019).
    """
    providers = {m.provider for m in builtin_adapter_metadata()}
    assert "anthropic" in providers


def test_openai_metadata_present() -> None:
    """``OpenAILLMAdapter`` is in the catalog."""
    providers = {m.provider for m in builtin_adapter_metadata()}
    assert "openai" in providers


def test_register_builtin_adapters_runs() -> None:
    """The registration path is a no-error side effect when called on a
    fresh ``Resolver``. This is the path ``oneiric.adapters.bootstrap.
    register_builtin_adapters`` takes — the lazy ``BifrostLLMRouter``
    entry is added inside the same call, so the lazy-import branch
    must also succeed (covered by ``test_metadata_registered`` in
    ``test_bifrost.py``)."""
    resolver = Resolver()
    register_builtin_adapters(resolver)
    # No assertion: success is the test. The Resolver is populated
    # in-memory; inspecting it would couple the test to the resolver
    # internals, which are not part of REQ-BIFROST-018's contract.


def test_existing_llm_metadata_shape_is_valid() -> None:
    """Sanity check: every existing LLM adapter has a non-empty
    ``category``, ``provider``, and ``factory``. The new router
    follows the same shape (REQ-BIFROST-019).
    """
    llm_entries = [
        m for m in builtin_adapter_metadata() if m.category == "llm"
    ]
    assert len(llm_entries) >= 2  # anthropic + openai
    for entry in llm_entries:
        assert entry.category == "llm"
        assert entry.provider in {"anthropic", "openai", "bifrost"}
        assert entry.factory  # non-empty
        assert " " in entry.factory  # per 3-agent F7 fix (space after colon)


def test_anthropic_llm_importable() -> None:
    """The AnthropicLLM class is importable (eager import path works)."""
    assert AnthropicLLM.metadata is not None
    assert AnthropicLLM.metadata.provider == "anthropic"


def test_openai_llm_importable() -> None:
    """The OpenAILLMAdapter class is importable."""
    assert OpenAILLMAdapter.metadata is not None
    assert OpenAILLMAdapter.metadata.provider == "openai"
