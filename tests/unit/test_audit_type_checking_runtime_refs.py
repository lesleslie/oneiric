"""Tests for ``scripts/audit_type_checking_runtime_refs.py``.

The audit reports names imported under ``if TYPE_CHECKING:`` that are
referenced at runtime, where the reference would raise ``NameError``.

It must not report a name that *is* bound at runtime. The idiom that
tripped it is the optional-dependency fallback::

    if TYPE_CHECKING:
        from nats.aio.msg import Msg
    else:
        Msg = Any

The ``else`` branch binds ``Msg`` at runtime, so the TC import is not
TC-only. Counting only imports as runtime bindings reported this as a
violation — a false positive on a pattern oneiric's own queue adapters
use.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_type_checking_runtime_refs.py"
)


def _load_audit():
    """Load the audit script as a module (it lives outside the package)."""
    spec = importlib.util.spec_from_file_location("audit_tc", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the script's dataclasses resolve their own
    # module through sys.modules at class-creation time.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _violations_for(tmp_path: Path, source: str) -> list[str]:
    """Return the runtime-reference violations the audit reports for *source*."""
    audit = _load_audit()
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    result = audit._scan_file(path)
    return [v.name for v in result.violations]


class TestRuntimeFallbackPatterns:
    def test_else_branch_assignment_binds_the_name(self, tmp_path: Path) -> None:
        """``else: Msg = Any`` binds Msg at runtime — not a violation."""
        source = (
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING, Any\n"
            "if TYPE_CHECKING:\n"
            "    from nats.aio.msg import Msg\n"
            "else:\n"
            "    Msg = Any\n"
            "def use(msg: Msg) -> None:\n"
            "    print(msg)\n"
        )
        assert _violations_for(tmp_path, source) == []

    def test_else_branch_import_binds_the_name(self, tmp_path: Path) -> None:
        """``else: from foo import Bar`` binds Bar at runtime."""
        source = (
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from foo import Bar\n"
            "else:\n"
            "    from foo import Bar\n"
            "def use() -> None:\n"
            "    print(Bar)\n"
        )
        assert _violations_for(tmp_path, source) == []

    def test_genuine_tc_only_name_is_reported(self, tmp_path: Path) -> None:
        """A TC import with no runtime binding IS reported."""
        source = (
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from foo import Bar\n"
            "def use() -> None:\n"
            "    print(Bar)\n"
        )
        assert _violations_for(tmp_path, source) == ["Bar"]

    def test_module_level_assignment_is_not_treated_as_a_fallback(
        self, tmp_path: Path
    ) -> None:
        """A plain module-level assignment is not the TC-else idiom."""
        source = (
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from foo import Bar\n"
            "Bar = None\n"
            "def use() -> None:\n"
            "    print(Bar)\n"
        )
        # The assignment is outside the TC else-branch, so the TC import is
        # still reported — matching the conservative rule.
        assert _violations_for(tmp_path, source) == ["Bar"]
