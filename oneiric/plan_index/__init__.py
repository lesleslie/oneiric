"""Public surface of the oneiric plan_index library."""

from __future__ import annotations

# MIN_STORE_DOCS is sourced from discovery (verbatim per brief) — exclusions.py
# is "Files to NOT touch" from Task 1, so we don't add the constant there.
from oneiric.plan_index.discovery import (
    MIN_STORE_DOCS,
    discover_files,
    discover_stores,
    scan_entries,
)
from oneiric.plan_index.entry import Entry
from oneiric.plan_index.exclusions import SYSTEM_DIR_PARTS, is_excluded
from oneiric.plan_index.frontmatter import extract_frontmatter
from oneiric.plan_index.regenerate import regenerate
from oneiric.plan_index.render import render_index

__all__ = [
    "MIN_STORE_DOCS",
    "SYSTEM_DIR_PARTS",
    "Entry",
    "discover_files",
    "discover_stores",
    "extract_frontmatter",
    "is_excluded",
    "regenerate",
    "render_index",
    "scan_entries",
]
