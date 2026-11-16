"""Tests for the version stamper's contract.

``scripts/stamp_version.py`` is what keeps a release from moving
``pyproject.toml`` without moving the doc claims with it. Two callers
depend on its behaviour, and they depend on different halves of it:

- the **pre-commit hook** calls it with ``--stage``, because the hook has no
  other staging step — the commit that bumps the version has to carry the
  claims with it;
- the **release path** calls it with no flags, because crackerjack's publish
  flow stages the rewritten files itself as part of the commit that carries
  the version bump.

That split is the reason staging is opt-in. When ``--stage`` was parsed but
ignored, the second caller silently got staging it never asked for — and the
flag itself advertised a behaviour it did not have. These tests pin the
contract so neither half rots again.

The same script ships in akosha and mcp-common with different surfaces;
this module pins the behaviour, not the surface list.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path("scripts") / "stamp_version.py"


def _make_repo(root: Path, version: str = "1.2.3") -> Path:
    """Lay out a repo whose claims are one version behind pyproject."""
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n',
    )
    (root / "CLAUDE.md").write_text(f"**Status:** Production Ready (0.0.1)\n")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "CLI_REFERENCE.md").write_text("**Version:** 0.0.1\n")
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
class TestStampVersionContract:
    """The stamper rewrites claims; staging is opt-in."""

    def test_rewrites_the_claims(self, tmp_path: Path) -> None:
        """A plain run moves every claim onto the pyproject version."""
        root = _make_repo(tmp_path)

        result = _run(root)

        assert result.returncode == 0
        assert "(1.2.3)" in (root / "CLAUDE.md").read_text()
        assert "**Version:** 1.2.3" in (root / "docs" / "CLI_REFERENCE.md").read_text()

    def test_plain_run_does_not_stage(self, tmp_path: Path) -> None:
        """Without ``--stage`` the claims are rewritten and left unstaged."""
        root = _make_repo(tmp_path)
        subprocess.run(
            ["git", "init", "-q", str(root)],
            check=True,
            capture_output=True,
        )

        result = _run(root)

        assert result.returncode == 0
        staged = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert staged.stdout.strip() == ""

    def test_stage_flag_stages_the_claims(self, tmp_path: Path) -> None:
        """``--stage`` adds the rewritten claims to the index."""
        root = _make_repo(tmp_path)
        subprocess.run(
            ["git", "init", "-q", str(root)],
            check=True,
            capture_output=True,
        )

        result = _run(root, "--stage")

        assert result.returncode == 0
        staged = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert "CLAUDE.md" in staged.stdout
        assert "docs/CLI_REFERENCE.md" in staged.stdout

    def test_check_reports_drift_without_writing(self, tmp_path: Path) -> None:
        """``--check`` exits 1 on drift and leaves the claims alone."""
        root = _make_repo(tmp_path)

        result = _run(root, "--check")

        assert result.returncode == 1
        assert "(0.0.1)" in (root / "CLAUDE.md").read_text()

    def test_check_passes_when_in_sync(self, tmp_path: Path) -> None:
        """``--check`` exits 0 once the claims match."""
        root = _make_repo(tmp_path)
        assert _run(root).returncode == 0

        result = _run(root, "--check")

        assert result.returncode == 0

    def test_missing_claim_is_an_error(self, tmp_path: Path) -> None:
        """A surface with no recognisable claim exits 2, not 0."""
        root = _make_repo(tmp_path)
        (root / "CLAUDE.md").write_text("no version here\n")

        result = _run(root)

        assert result.returncode == 2
        assert "CLAUDE.md" in result.stderr

    def test_works_outside_a_git_checkout(self, tmp_path: Path) -> None:
        """The stamper does not need git unless it is asked to stage."""
        root = _make_repo(tmp_path)

        result = _run(root)

        assert result.returncode == 0
        assert "1.2.3" in (root / "CLAUDE.md").read_text()
