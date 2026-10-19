"""Public surface of the oneiric plan_index library."""
from __future__ import annotations
from oneiric.plan_index.entry import Entry
from oneiric.plan_index.frontmatter import extract_frontmatter
from oneiric.plan_index.exclusions import is_excluded, SYSTEM_DIR_PARTS
# MIN_STORE_DOCS is sourced from discovery (verbatim per brief) — exclusions.py
# is "Files to NOT touch" from Task 1, so we don't add the constant there.
from oneiric.plan_index.discovery import MIN_STORE_DOCS, discover_stores, discover_files, scan_entries
from oneiric.plan_index.render import render_index
from oneiric.plan_index.regenerate import regenerate

__all__ = [
    "Entry",
    "extract_frontmatter",
    "is_excluded",
    "SYSTEM_DIR_PARTS",
    "MIN_STORE_DOCS",
    "discover_stores",
    "discover_files",
    "scan_entries",
    "render_index",
    "regenerate",
]
