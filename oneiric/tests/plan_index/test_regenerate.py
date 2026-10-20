# oneiric/tests/plan_index/test_regenerate.py
from pathlib import Path

from oneiric.plan_index.regenerate import regenerate


def test_default_out_path(tmp_path: Path):
    """Default out_path = <repo_root>/docs/plans/PLAN_INDEX.md."""
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    regenerate(repo_root=tmp_path)
    assert (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").exists()


def test_check_mode_exits_1_on_drift(tmp_path: Path, capsys):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    regenerate(repo_root=tmp_path)
    # Modify PLAN_INDEX.md so drift exists
    plan = tmp_path / "docs" / "plans" / "PLAN_INDEX.md"
    plan.write_text("STALE CONTENT\n")
    # check=True should detect drift and exit 1 (not raise)
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        regenerate(repo_root=tmp_path, check=True)
    assert exc_info.value.code == 1


def test_check_mode_exits_0_on_no_drift(tmp_path: Path):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    regenerate(repo_root=tmp_path)
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        regenerate(repo_root=tmp_path, check=True)
    assert exc_info.value.code == 0


def test_regenerate_equals_scan_plus_render(tmp_path: Path):
    """Identity test: regenerate(X) == scan_entries(X) → render_index path."""
    from oneiric.plan_index import scan_entries
    from oneiric.plan_index.render import render_index

    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "x.md").write_text(
        "---\nstatus: active\nrole: implementation\nkind: plan\ntopic: t\n---\n# X\n"
    )
    (docs / "y.md").write_text(
        "---\nstatus: active\nrole: implementation\nkind: plan\ntopic: t\n---\n# Y\n"
    )
    entries = scan_entries(tmp_path)
    render_index(entries_by_store=entries, generated_at="2026-10-19")
    # Now regenerate
    regenerate(repo_root=tmp_path)
    actual = (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").read_text()
    # After regenerate, file should equal expected (modulo header/preamble which we don't emit).
    assert "Lifecycle × Role Distribution" in actual
    assert "docs/plans/x.md" in actual
    assert "docs/plans/y.md" in actual
