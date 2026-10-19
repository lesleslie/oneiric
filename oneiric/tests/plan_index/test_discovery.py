# oneiric/tests/plan_index/test_discovery.py
import os
from pathlib import Path
from oneiric.plan_index.discovery import discover_stores, discover_files, MIN_STORE_DOCS
from oneiric.plan_index.entry import Entry
from oneiric.plan_index.frontmatter import extract_frontmatter
from oneiric.plan_index import exclusions as exclusions_module
from oneiric.plan_index import frontmatter as frontmatter_module
import yaml

def _make_repo(tmp: Path, name: str, frontmatter_count: int) -> Path:
    repo = tmp / name
    docs = repo / "docs" / "plans"
    docs.mkdir(parents=True)
    for i in range(frontmatter_count):
        (docs / f"plan_{i}.md").write_text(f"---\nstatus: active\n---\n# Plan {i}\n")
    return repo

def test_promote_at_min_store_docs(tmp_path: Path):
    repo = _make_repo(tmp_path, "r1", MIN_STORE_DOCS)
    stores = discover_stores(repo, yaml)
    assert "docs/plans/" in stores

def test_demote_below_min_store_docs(tmp_path: Path):
    repo = _make_repo(tmp_path, "r1", MIN_STORE_DOCS - 1)
    stores = discover_stores(repo, yaml)
    assert "docs/plans/" not in stores

def test_system_dir_parts_pruned(tmp_path: Path):
    """A node_modules directory with frontmatter'd files must NOT be a store."""
    repo = tmp_path / "r1"
    (repo / "node_modules" / "docs" / "plans").mkdir(parents=True)
    (repo / "node_modules" / "docs" / "plans" / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    (repo / "docs" / "plans").mkdir(parents=True)
    (repo / "docs" / "plans" / "bar.md").write_text("---\nstatus: active\n---\n# Bar\n")
    (repo / "docs" / "plans" / "baz.md").write_text("---\nstatus: active\n---\n# Baz\n")
    stores = discover_stores(repo, yaml)
    assert "docs/plans/" in stores
    assert "node_modules/docs/plans/" not in stores

def test_dedup_handles_duplicate_dirs_in_scan(tmp_path: Path):
    """Sequence, not Set — duplicates from filesystem anomalies dedupe first-wins."""
    repo = tmp_path / "r1"
    plans = repo / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    (plans / "foo2.md").write_text("---\nstatus: active\n---\n# Foo2\n")
    stores = discover_stores(repo, yaml)
    assert list(stores).count("docs/plans/") == 1
