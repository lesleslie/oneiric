from __future__ import annotations

import json
from pathlib import Path

import pytest

from oneiric.adapters.secrets.file import FileSecretAdapter, FileSecretSettings
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_file_secret_adapter_reads_values(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"api": "123"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    await adapter.init()
    assert await adapter.get_secret("api") == "123"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_file_secret_adapter_reload_on_access(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"api": "123"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path, reload_on_access=True))
    await adapter.init()
    assert await adapter.get_secret("api") == "123"
    path.write_text(json.dumps({"api": "456"}))
    assert await adapter.get_secret("api") == "456"
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — init failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    with pytest.raises(LifecycleError, match="secrets-file-missing"):
        await adapter.init()


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_true(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"x": "1"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_health_returns_false_on_bad_file(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text("not-json")
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# Tests — invalidate_cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_cache(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"k": "v1"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    await adapter.init()
    assert adapter._cache is not None

    await adapter.invalidate_cache()
    assert adapter._cache is None

    # next get_secret should reload
    result = await adapter.get_secret("k")
    assert result == "v1"


# ---------------------------------------------------------------------------
# Tests — get_secret missing key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_secret_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"a": "1"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    await adapter.init()
    assert await adapter.get_secret("nonexistent") is None


# ---------------------------------------------------------------------------
# Tests — _load edge cases
# ---------------------------------------------------------------------------


def test_load_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "s.toml"
    path.write_text("[secrets]\nkey = 'val'")
    settings = FileSecretSettings(path=path, format="toml")
    adapter = FileSecretAdapter(settings)
    with pytest.raises(LifecycleError, match="unsupported-secrets-file-format"):
        adapter._load(force=True)


def test_load_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text("{{invalid}}")
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    with pytest.raises(LifecycleError, match="invalid-secrets-file"):
        adapter._load(force=True)


def test_load_non_dict_json(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps([1, 2, 3]))
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    with pytest.raises(LifecycleError, match="secrets-file-must-be-object"):
        adapter._load(force=True)


def test_load_skips_when_cached(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"k": "v"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    adapter._cache = {"k": "cached"}  # pre-populate cache
    adapter._load()  # force=False → should return early without reading file
    assert adapter._cache == {"k": "cached"}
