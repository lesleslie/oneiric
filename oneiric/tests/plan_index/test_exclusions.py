from oneiric.plan_index.exclusions import is_excluded, SYSTEM_DIR_PARTS


def test_drafts_subdirectory_excluded():
    assert is_excluded("docs/plans/drafts/foo.md")


def test_archive_segment_excluded():
    assert is_excluded("docs/plans/.archive/foo.md")
    assert is_excluded("docs/plans/archive/foo.md")


def test_backup_suffix_excluded():
    assert is_excluded("docs/plans/foo.md.backup")
    assert is_excluded("docs/plans/foo.md.backup.json")


def test_self_skip_excluded():
    assert is_excluded("docs/plans/PLAN_INDEX.md")


def test_hyphenated_drafts_archive_NOT_excluded():
    assert not is_excluded("docs/plans/drafts-archive/foo.md")


def test_toplevel_archived_NOT_excluded():
    assert not is_excluded("docs/archived.md")


def test_system_dir_parts_pinned():
    """Pinned verbatim from the spec — every entry must be in the exclusion set."""
    expected = {".git", ".venv", "venv", "__pycache__", "node_modules", "htmlcov",
                "dist", ".pytest_cache", ".archive", "archive", "backups", ".backups",
                "coverage_report", "assets", ".vscode", ".idea", "cache", ".cache",
                ".playwright-mcp", "worktree-snapshots"}
    assert SYSTEM_DIR_PARTS == expected
