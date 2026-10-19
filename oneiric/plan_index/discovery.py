"""Store discovery + file enumeration for the plan_index library.

Pins the dedup invariant: discover_stores returns a Sequence that
preserves first-seen order and never duplicates paths, even when the
filesystem contains anomalies. Tested by
test_dedup_handles_duplicate_dirs_in_scan.

SYSTEM_DIR_PARTS is imported from exclusions to keep the pruning rules
in one place.
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oneiric.plan_index.exclusions import SYSTEM_DIR_PARTS, is_excluded
from oneiric.plan_index.frontmatter import extract_frontmatter

if TYPE_CHECKING:
    from collections.abc import Sequence
    from oneiric.plan_index.entry import Entry

MIN_STORE_DOCS: int = 2

def discover_stores(repo_root: Path, yaml_module: Any) -> "Sequence[str]":
    """Return POSIX-relative store paths, deduped, first-seen order."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for dirpath, dirnames, filenames in _walk(repo_root):
        # Prune system directories in-place
        dirnames[:] = [d for d in dirnames if d not in SYSTEM_DIR_PARTS]
        md_files = [f for f in filenames if f.endswith(".md")]
        if not md_files:
            continue
        rel_dir = Path(dirpath).resolve().relative_to(repo_root.resolve()).as_posix()
        if rel_dir == ".":
            continue
        store_rel = rel_dir + "/"
        # Count frontmatter'd files in this dir
        fm_count = 0
        for fname in md_files:
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if extract_frontmatter_local(text, yaml_module) is not None:
                fm_count += 1
                if fm_count >= MIN_STORE_DOCS:
                    break
        if fm_count >= MIN_STORE_DOCS and store_rel not in seen_set:
            seen.append(store_rel)
            seen_set.add(store_rel)
    return seen

def _walk(repo_root: Path):
    """Wrapper around os.walk for testability."""
    import os
    yield from os.walk(str(repo_root.resolve()), followlinks=False)

# Local import to avoid circular: frontmatter imports stdlib only.
def extract_frontmatter_local(text: str, yaml_module: Any) -> dict | None:
    from oneiric.plan_index.frontmatter import extract_frontmatter
    return extract_frontmatter(text, yaml_module)

def discover_files(repo_root: Path, store_rel: str, *, skip_deeper_stores=frozenset()) -> list[tuple[Path, str]]:
    """Return [(absolute_path, repo_relative_posix)] for each .md under the store."""
    root = repo_root / store_rel.rstrip("/")
    if not root.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        if is_excluded(rel):
            continue
        if any(ds != store_rel and rel.startswith(ds.rstrip("/") + "/") for ds in skip_deeper_stores):
            continue
        out.append((path, rel))
    return out

def scan_entries(repo_root: Path, *, exclude: "Sequence[str]" = ()) -> dict[str, list[Entry]]:
    """Walk the repo's stores and return {store: [Entry, ...]}."""
    import yaml as _yaml
    stores = discover_stores(repo_root, _yaml)
    out: dict[str, list[Entry]] = {}
    for store in stores:
        entries: list[Entry] = []
        for abs_path, rel in discover_files(repo_root, store):
            if any(rel == e for e in exclude):
                continue
            try:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            front = extract_frontmatter(text, _yaml)
            if front is None:
                continue
            from oneiric.plan_index.entry import Entry as _Entry
            from oneiric.plan_index._entry_from_front import entry_from_front  # see note
            entries.append(entry_from_front(abs_path, rel, store, text, front))
        if entries:
            out[store] = entries
    return out
