# oneiric/tests/plan_index/test_scan_entries.py
import os
from pathlib import Path
from oneiric.plan_index.discovery import discover_stores, discover_files
from oneiric.plan_index.frontmatter import extract_frontmatter
from oneiric.plan_index import scan_entries  # exported via oneiric/plan_index/__init__.py (Task 2 step 15)

def test_scan_entries_returns_dict(tmp_path: Path):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("---\nstatus: active\n---\n# A\n")
    (docs / "b.md").write_text("---\nstatus: draft\n---\n# B\n")
    entries = scan_entries(tmp_path)
    assert "docs/plans/" in entries
    assert len(entries["docs/plans/"]) == 2
