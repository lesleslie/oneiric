"""Path-segment exclusion rules for the regenerator's filesystem walk.

SYSTEM_DIR_PARTS is a verbatim copy of the legacy script's exclusion
list (mahavishnu/scripts/regenerate_plan_index.py:99-127). Test
`test_system_dir_parts_pinned` pins every entry.
"""

from __future__ import annotations

SELF_SKIP_REL = "docs/plans/PLAN_INDEX.md"
DRAFTS_PREFIX = "docs/plans/drafts/"
ARCHIVE_PARTS = ("archive", ".archive")
BACKUP_SUFFIXES = (".backup", ".backup.json")

# Verbatim from legacy script (mahavishnu/scripts/regenerate_plan_index.py:99-127)
SYSTEM_DIR_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "htmlcov",
        "dist",
        ".pytest_cache",
        ".archive",
        "archive",
        "backups",
        ".backups",
        "coverage_report",
        "assets",
        ".vscode",
        ".idea",
        "cache",
        ".cache",
        ".playwright-mcp",
        "worktree-snapshots",
    }
)


def is_excluded(rel: str) -> bool:
    """True if `rel` matches the regenerator's exclusion rules."""
    if rel == SELF_SKIP_REL:
        return True
    if rel.startswith(DRAFTS_PREFIX):
        return True
    parts = rel.split("/")
    for part in parts:
        if part in ARCHIVE_PARTS:
            return True
    for suffix in BACKUP_SUFFIXES:
        if rel.endswith(suffix):
            return True
    return False
