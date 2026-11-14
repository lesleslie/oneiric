"""Conformance tests for the LLM subsystem's OneiricAdapter slice.

The LLM chaining layer moved from ``mcp_common.llm`` into
``oneiric.adapters.llm``. Both moved classes now satisfy the structural
``OneiricAdapter`` Protocol: a class-level ``AdapterMetadata``, plus
``init`` / ``health`` / ``cleanup``.

The Protocol is *structural* -- no inheritance -- so these tests assert the
shape rather than a base class.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.adapters.bootstrap import builtin_adapter_metadata
from oneiric.adapters.llm.config import ProviderConfig
from oneiric.adapters.llm.fallback import FallbackChain
from oneiric.adapters.llm.provider import OpenAICompatibleProvider
from oneiric.adapters.protocol import OneiricAdapter
from oneiric.core.lifecycle import resolve_factory


class _TransportError(Exception):
    """A transport failure the provider's narrow except clause does not cover."""


def _mock_openai(client: Any | None = None) -> MagicMock:
    module = MagicMock()
    module.AsyncOpenAI = MagicMock(return_value=client or MagicMock())
    return module


def _make_provider(
    config: ProviderConfig, client: Any | None = None
) -> OpenAICompatibleProvider:
    """Construct a provider with the ``openai`` package mocked out."""
    with patch.dict(sys.modules, {"openai": _mock_openai(client)}):
        return OpenAICompatibleProvider(config)


def _mock_provider(name: str = "provider") -> MagicMock:
    """A stand-in provider for the chain.

    ``name`` is an instance attribute of the real class, so a spec'd mock
    does not carry it -- the chain reads it to key its circuit breakers.
    """
    provider = MagicMock(spec=OpenAICompatibleProvider)
    provider.name = name
    provider.init = AsyncMock()
    provider.health = AsyncMock(return_value=True)
    provider.cleanup = AsyncMock()
    return provider


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_provider_satisfies_the_adapter_protocol() -> None:
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1")
    )
    assert isinstance(provider, OneiricAdapter)


def test_fallback_chain_satisfies_the_adapter_protocol() -> None:
    chain = FallbackChain()
    assert isinstance(chain, OneiricAdapter)


def test_provider_metadata_declares_the_new_factory_path() -> None:
    metadata = OpenAICompatibleProvider.metadata
    assert metadata.category == "llm"
    assert metadata.provider == "openai-compatible"
    assert metadata.factory == "oneiric.adapters.llm.provider: OpenAICompatibleProvider"


def test_fallback_chain_metadata_declares_the_new_factory_path() -> None:
    metadata = FallbackChain.metadata
    assert metadata.category == "llm"
    assert metadata.provider == "fallback"
    assert metadata.factory == "oneiric.adapters.llm.fallback: FallbackChain"


def test_declared_factory_paths_resolve_to_the_moved_classes() -> None:
    """A factory path the runtime cannot load is a registration that explodes.

    ``resolve_factory`` is the same call the lifecycle manager makes when
    it instantiates a candidate, so this proves the registered path is
    both syntactically valid and importable.
    """
    assert resolve_factory(FallbackChain.metadata.factory) is FallbackChain
    assert (
        resolve_factory(OpenAICompatibleProvider.metadata.factory)
        is OpenAICompatibleProvider
    )


def test_the_moved_classes_are_not_in_the_resolution_catalog() -> None:
    """They are consumer-constructed, so a catalog entry could never work.

    The catalog instantiates a factory with **no arguments** and then
    runs its health check; an adapter that fails that health check cannot
    be activated. ``FallbackChain()`` is an empty chain and
    ``OpenAICompatibleProvider()`` has no configuration, so both are
    permanently unhealthy and neither can ever be resolved by provider
    name.

    The classes keep their ``AdapterMetadata`` and the lifecycle methods
    -- that is what the ``OneiricAdapter`` Protocol asks for, and it is
    what the conformance tooling reads. What they do not get is a
    catalog entry that looks resolvable and is not.
    """
    providers = {m.provider for m in builtin_adapter_metadata()}
    assert "fallback" not in providers
    assert "openai-compatible" not in providers


def test_the_moved_classes_are_still_discoverable_as_adapters() -> None:
    """Conformance is by shape: the metadata is what a validator reads."""
    for cls in (FallbackChain, OpenAICompatibleProvider):
        metadata = cls.metadata
        assert metadata.category == "llm"
        assert metadata.factory
        assert metadata.capabilities


# ---------------------------------------------------------------------------
# Zero-argument construction (the registry instantiates factories with no args)
# ---------------------------------------------------------------------------


def test_provider_constructs_without_arguments() -> None:
    provider = OpenAICompatibleProvider()
    assert provider.name == ""


def test_fallback_chain_constructs_without_arguments() -> None:
    chain = FallbackChain()
    assert chain._providers == []


# ---------------------------------------------------------------------------
# init / health / cleanup
# ---------------------------------------------------------------------------


async def test_provider_init_warms_the_client_up() -> None:
    client = MagicMock()
    provider = OpenAICompatibleProvider()
    provider._config = ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1")

    with patch.dict(sys.modules, {"openai": _mock_openai(client)}):
        await provider.init()

    assert provider._client is client


async def test_provider_init_is_idempotent() -> None:
    client = MagicMock()
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"), client=client
    )

    await provider.init()

    assert provider._client is client


async def test_provider_init_without_configuration_is_a_no_op() -> None:
    provider = OpenAICompatibleProvider()
    await provider.init()
    assert provider._client is None


async def test_provider_health_is_true_when_the_provider_answers() -> None:
    client = MagicMock()
    client.models.list = AsyncMock(return_value=MagicMock())
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"), client=client
    )

    assert await provider.health() is True


async def test_provider_health_never_raises() -> None:
    """``health()`` must return a bool even when the transport raises.

    The narrower ``health_check`` only catches a fixed tuple of exception
    types; a transport error outside that tuple still has to surface as
    ``False`` here, because the monitoring layer relies on the bool.
    """
    client = MagicMock()
    client.models.list = AsyncMock(side_effect=_TransportError("connection reset"))
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"), client=client
    )

    assert await provider.health() is False


async def test_provider_cleanup_releases_the_client_and_is_idempotent() -> None:
    client = MagicMock()
    client.close = AsyncMock()
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"), client=client
    )

    await provider.cleanup()
    await provider.cleanup()

    assert provider._client is None
    client.close.assert_awaited_once()


async def test_provider_cleanup_never_raises() -> None:
    client = MagicMock()
    client.close = AsyncMock(side_effect=_TransportError("boom"))
    provider = _make_provider(
        ProviderConfig(name="minimax", base_url="https://127.0.0.1/v1"), client=client
    )

    await provider.cleanup()

    assert provider._client is None


async def test_fallback_chain_init_warms_every_provider() -> None:
    providers = [_mock_provider("p0"), _mock_provider("p1")]
    chain = FallbackChain(providers)

    await chain.init()

    for provider in providers:
        provider.init.assert_awaited_once()


async def test_fallback_chain_health_is_true_when_one_provider_answers() -> None:
    healthy = _mock_provider("healthy")
    healthy.health = AsyncMock(return_value=True)
    unhealthy = _mock_provider("unhealthy")
    unhealthy.health = AsyncMock(return_value=False)
    chain = FallbackChain([unhealthy, healthy])

    assert await chain.health() is True


async def test_fallback_chain_health_is_false_when_no_provider_answers() -> None:
    unhealthy = _mock_provider("unhealthy")
    unhealthy.health = AsyncMock(return_value=False)
    chain = FallbackChain([unhealthy])

    assert await chain.health() is False


async def test_fallback_chain_health_is_false_with_no_providers() -> None:
    assert await FallbackChain().health() is False


async def test_fallback_chain_health_never_raises() -> None:
    raising = _mock_provider("raising")
    raising.health = AsyncMock(side_effect=_TransportError("boom"))
    chain = FallbackChain([raising])

    assert await chain.health() is False


async def test_fallback_chain_init_is_fault_tolerant() -> None:
    """One provider failing to warm up must not strand the others."""
    failing = _mock_provider("failing")
    failing.init = AsyncMock(side_effect=_TransportError("boom"))
    working = _mock_provider("working")
    chain = FallbackChain([failing, working])

    with pytest.raises(Exception) as excinfo:
        await chain.init()

    working.init.assert_awaited_once()
    assert "failing" in str(excinfo.value)


async def test_fallback_chain_cleanup_releases_every_provider() -> None:
    providers = [_mock_provider("p0"), _mock_provider("p1")]
    chain = FallbackChain(providers)

    await chain.cleanup()

    for provider in providers:
        provider.cleanup.assert_awaited_once()


async def test_fallback_chain_cleanup_never_raises() -> None:
    raising = _mock_provider("raising")
    raising.cleanup = AsyncMock(side_effect=_TransportError("boom"))
    chain = FallbackChain([raising])

    await chain.cleanup()


def test_public_health_check_is_kept_on_the_provider() -> None:
    """``health_check`` stays public -- three repos call it by name.

    The protocol adds ``health``; it does not rename the existing method.
    """
    assert hasattr(OpenAICompatibleProvider, "health_check")
