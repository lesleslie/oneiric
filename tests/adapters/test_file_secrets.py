from __future__ import annotations

import json
from pathlib import Path

import pytest

from oneiric.adapters.secrets.file import FileSecretAdapter, FileSecretSettings


@pytest.mark.asyncio
async def test_file_secret_adapter_reads_values(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"api": "123"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path))
    await adapter.init()
    assert adapter.get_secret("api") == "123"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_file_secret_adapter_reload_on_access(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"api": "123"}))
    adapter = FileSecretAdapter(FileSecretSettings(path=path, reload_on_access=True))
    await adapter.init()
    assert adapter.get_secret("api") == "123"
    path.write_text(json.dumps({"api": "456"}))
    assert adapter.get_secret("api") == "456"
    await adapter.cleanup()
