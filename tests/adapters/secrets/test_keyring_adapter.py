"""Tests for KeyringSecretAdapter.

Covers both the keyring-available and keyring-unavailable paths via monkeypatching.
"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from oneiric.adapters.secrets.keyring import KeyringSecretAdapter, KeyringSecretSettings


# ---------------------------------------------------------------------------
# Tests — Settings
# ---------------------------------------------------------------------------


def test_settings_defaults() -> None:
    s = KeyringSecretSettings()
    assert s.service_name == "oneiric"
    assert s.key_prefix == ""


def test_settings_custom() -> None:
    s = KeyringSecretSettings(service_name="myapp", key_prefix="prod:")
    assert s.service_name == "myapp"
    assert s.key_prefix == "prod:"


# ---------------------------------------------------------------------------
# Tests — Lifecycle (keyring unavailable)
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter_no_keyring(monkeypatch: pytest.MonkeyPatch) -> KeyringSecretAdapter:
    monkeypatch.setattr(
        "oneiric.adapters.secrets.keyring.KEYRING_AVAILABLE", False
    )
    adapter = KeyringSecretAdapter(KeyringSecretSettings())
    adapter._available = False
    return adapter


@pytest.mark.asyncio
async def test_init_no_keyring(adapter_no_keyring: KeyringSecretAdapter) -> None:
    await adapter_no_keyring.init()  # should not raise


@pytest.mark.asyncio
async def test_health_false_when_unavailable(
    adapter_no_keyring: KeyringSecretAdapter,
) -> None:
    assert await adapter_no_keyring.health() is False


@pytest.mark.asyncio
async def test_get_secret_returns_none_when_unavailable(
    adapter_no_keyring: KeyringSecretAdapter,
) -> None:
    result = await adapter_no_keyring.get_secret("some-key")
    assert result is None


@pytest.mark.asyncio
async def test_cleanup_no_keyring(adapter_no_keyring: KeyringSecretAdapter) -> None:
    await adapter_no_keyring.cleanup()  # should not raise


# ---------------------------------------------------------------------------
# Tests — Lifecycle (keyring available)
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter_with_keyring(monkeypatch: pytest.MonkeyPatch) -> KeyringSecretAdapter:
    monkeypatch.setattr(
        "oneiric.adapters.secrets.keyring.KEYRING_AVAILABLE", True
    )
    adapter = KeyringSecretAdapter(KeyringSecretSettings(service_name="svc"))
    adapter._available = True
    return adapter


@pytest.mark.asyncio
async def test_init_with_keyring(adapter_with_keyring: KeyringSecretAdapter) -> None:
    await adapter_with_keyring.init()  # should not raise


@pytest.mark.asyncio
async def test_health_true_when_available(
    adapter_with_keyring: KeyringSecretAdapter,
) -> None:
    assert await adapter_with_keyring.health() is True


@pytest.mark.asyncio
async def test_get_secret_returns_value(
    adapter_with_keyring: KeyringSecretAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_keyring = MagicMock()
    fake_keyring.get_password.return_value = "super-secret"
    fake_keyring.errors = MagicMock()
    fake_keyring.errors.KeyringError = Exception

    with patch.dict("sys.modules", {"keyring": fake_keyring, "keyring.errors": fake_keyring.errors}):
        result = await adapter_with_keyring.get_secret("api-key")

    assert result == "super-secret"
    fake_keyring.get_password.assert_called_once_with("svc", "api-key")


@pytest.mark.asyncio
async def test_get_secret_with_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("oneiric.adapters.secrets.keyring.KEYRING_AVAILABLE", True)
    adapter = KeyringSecretAdapter(
        KeyringSecretSettings(service_name="svc", key_prefix="prod:")
    )
    adapter._available = True

    fake_keyring = MagicMock()
    fake_keyring.get_password.return_value = "prefixed-value"
    fake_keyring.errors = MagicMock()
    fake_keyring.errors.KeyringError = Exception

    with patch.dict("sys.modules", {"keyring": fake_keyring, "keyring.errors": fake_keyring.errors}):
        result = await adapter.get_secret("mykey")

    assert result == "prefixed-value"
    fake_keyring.get_password.assert_called_once_with("svc", "prod:mykey")


@pytest.mark.asyncio
async def test_get_secret_returns_none_on_keyring_error(
    adapter_with_keyring: KeyringSecretAdapter,
) -> None:
    class FakeKeyringError(Exception):
        pass

    fake_keyring = MagicMock()
    fake_keyring.get_password.side_effect = FakeKeyringError("locked")
    fake_keyring.errors = MagicMock()
    fake_keyring.errors.KeyringError = FakeKeyringError

    with patch.dict("sys.modules", {"keyring": fake_keyring, "keyring.errors": fake_keyring.errors}):
        result = await adapter_with_keyring.get_secret("fail-key")

    assert result is None


@pytest.mark.asyncio
async def test_get_secret_returns_none_on_generic_exception(
    adapter_with_keyring: KeyringSecretAdapter,
) -> None:
    class FakeKeyringError(Exception):
        pass

    fake_keyring = MagicMock()
    fake_keyring.get_password.side_effect = RuntimeError("unexpected")
    fake_keyring.errors = MagicMock()
    fake_keyring.errors.KeyringError = FakeKeyringError

    with patch.dict("sys.modules", {"keyring": fake_keyring, "keyring.errors": fake_keyring.errors}):
        result = await adapter_with_keyring.get_secret("weird-error")

    assert result is None


@pytest.mark.asyncio
async def test_get_secret_none_value_not_logged_as_resolved(
    adapter_with_keyring: KeyringSecretAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A None response from keyring is returned without the 'resolved' log."""
    fake_keyring = MagicMock()
    fake_keyring.get_password.return_value = None
    fake_keyring.errors = MagicMock()
    fake_keyring.errors.KeyringError = Exception

    with patch.dict("sys.modules", {"keyring": fake_keyring, "keyring.errors": fake_keyring.errors}):
        result = await adapter_with_keyring.get_secret("missing")

    assert result is None


@pytest.mark.asyncio
async def test_cleanup_with_keyring(adapter_with_keyring: KeyringSecretAdapter) -> None:
    await adapter_with_keyring.cleanup()  # should not raise


# ---------------------------------------------------------------------------
# Tests — Module-level KEYRING_AVAILABLE detection
# ---------------------------------------------------------------------------


def test_keyring_available_flag_type() -> None:
    import oneiric.adapters.secrets.keyring as keyring_mod

    assert isinstance(keyring_mod.KEYRING_AVAILABLE, bool)


def test_adapter_metadata() -> None:
    assert KeyringSecretAdapter.metadata.category == "secrets"
    assert KeyringSecretAdapter.metadata.provider == "keyring"
    assert KeyringSecretAdapter.metadata.requires_secrets is False
