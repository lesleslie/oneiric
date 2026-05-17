from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def test_ulid_import_uses_druva_branch_without_mutating_package_module():
    fake_druva = types.ModuleType("druva")

    class FakeULID:
        def __init__(self, value: str | bytes | None = None):
            self.value = "0" * 26 if value is None else value
            self.timestamp = 123456789

        def __str__(self) -> str:
            return self.value if isinstance(self.value, str) else "0" * 26

    fake_druva.ULID = FakeULID
    fake_druva.generate = lambda: "1" * 26
    fake_druva.get_timestamp = lambda value: 123456789
    fake_druva.is_ulid = lambda value: isinstance(value, str) and len(value) == 26

    module_path = Path(__file__).resolve().parents[2] / "oneiric" / "core" / "ulid.py"
    spec = importlib.util.spec_from_file_location("ulid_druva_branch", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    original_druva = sys.modules.get("druva")
    try:
        sys.modules["druva"] = fake_druva
        spec.loader.exec_module(module)

        assert module.DHURUVA_AVAILABLE is True
        assert module.generate_config_id() == "1" * 26
        assert module.extract_timestamp("1" * 26) == 123456789
        assert module.is_config_ulid("1" * 26) is True
    finally:
        if original_druva is None:
            sys.modules.pop("druva", None)
        else:
            sys.modules["druva"] = original_druva
