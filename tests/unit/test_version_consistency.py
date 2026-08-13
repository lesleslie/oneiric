"""Version-string consistency guard for Oneiric.

Single-file pytest module that asserts every documented version stamp
(README banner, CLI_REFERENCE header, CLAUDE.md status line) agrees with the
canonical version declared in ``pyproject.toml``. Modeled on the Bodai
ci-version-guard-template and on
``tests/unit/test_task_router.py::TestYAMLRoutingSync`` in mahavishnu.

Adoption notes (oneiric-specific)
---------------------------------
- Oneiric's CLI is typer-based and does not expose ``--version``. The CLI
  guard is intentionally absent (template's skip-on-None contract).
- Oneiric is a library, not an MCP server. The MCP ``/health`` guard is also
  absent.
- Three docs surfaces are pinned: README, docs/CLI_REFERENCE.md, CLAUDE.md.
  Each is a one-line assertion; mismatch messages name the file + line so the
  next bump author can fix without re-running the audit.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

# Configuration — points at oneiric-specific surfaces.
PYPROJECT_PATH: Path = Path("pyproject.toml")
README_PATH: Path = Path("README.md")
CLI_REFERENCE_PATH: Path = Path("docs/CLI_REFERENCE.md")
CLAUDE_MD_PATH: Path = Path("CLAUDE.md")

# Patterns use one capture group for the semver.
README_BANNER_PATTERN: str = r"current\s+v?(\d+\.\d+\.\d+(?:[.\-+]\w+)*)"
CLI_REFERENCE_HEADER_PATTERN: str = r"\*\*Version:\*\*\s+v?(\d+\.\d+\.\d+(?:[.\-+]\w+)*)"
CLAUDE_STATUS_PATTERN: str = (
    r"\*\*Status:\*\*\s+Production\s+Ready\s+\(v?(\d+\.\d+\.\d+(?:[.\-+]\w+)*)\)"
)

# Only the first N lines of each doc are scanned — version banners almost
# always live near the top, and limiting the scan avoids matching an unrelated
# changelog entry buried in the file.
README_BANNER_SEARCH_LINES: int = 30
CLI_REFERENCE_SEARCH_LINES: int = 30
CLAUDE_STATUS_SEARCH_LINES: int = 30

_SEMVER_RE = re.compile(r"(\d+\.\d+\.\d+(?:[.\-+]\w+)*)")


def _normalize_version(raw: str) -> str:
    return raw.strip().lstrip("v").strip()


def _read_pyproject_version(pyproject_path: Path) -> str:
    if not pyproject_path.is_file():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(
            f"[project].version missing or empty in {pyproject_path}",
        )
    return _normalize_version(version)


def _scan_head(path: Path, pattern: str, max_lines: int) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    with path.open(encoding="utf-8") as f:
        head = "".join(line for _, line in zip(range(max_lines), f))
    match = re.search(pattern, head)
    if not match or not match.group(1):
        raise ValueError(
            f"No version banner matched {pattern!r} in the first "
            f"{max_lines} lines of {path}",
        )
    return _normalize_version(match.group(1))


class TestVersionConsistency:
    """Every documented version stamp must equal ``pyproject.toml``."""

    def test_pyproject_baseline(self) -> None:
        """Sanity: pyproject.toml has a parseable [project].version."""
        version = _read_pyproject_version(PYPROJECT_PATH)
        assert _SEMVER_RE.fullmatch(version), (
            f"pyproject version {version!r} is not a valid semver-shaped token"
        )

    def test_readme_banner_matches(self) -> None:
        """README's "current vX.Y.Z" stamp must equal pyproject."""
        expected = _read_pyproject_version(PYPROJECT_PATH)
        actual = _scan_head(
            README_PATH, README_BANNER_PATTERN, README_BANNER_SEARCH_LINES
        )
        assert actual == expected, (
            f"README banner says {actual!r} but pyproject says {expected!r}.\n"
            f"Update the version near the top of {README_PATH} "
            f"(within the first {README_BANNER_SEARCH_LINES} lines)."
        )

    def test_cli_reference_header_matches(self) -> None:
        """docs/CLI_REFERENCE.md "**Version:**" header must equal pyproject."""
        expected = _read_pyproject_version(PYPROJECT_PATH)
        actual = _scan_head(
            CLI_REFERENCE_PATH,
            CLI_REFERENCE_HEADER_PATTERN,
            CLI_REFERENCE_SEARCH_LINES,
        )
        assert actual == expected, (
            f"docs/CLI_REFERENCE.md header says {actual!r} but pyproject "
            f"says {expected!r}.\nUpdate the **Version:** line near the top "
            f"of {CLI_REFERENCE_PATH}."
        )

    def test_claude_status_matches(self) -> None:
        """CLAUDE.md "Status: Production Ready (X.Y.Z)" must equal pyproject."""
        expected = _read_pyproject_version(PYPROJECT_PATH)
        actual = _scan_head(
            CLAUDE_MD_PATH, CLAUDE_STATUS_PATTERN, CLAUDE_STATUS_SEARCH_LINES
        )
        assert actual == expected, (
            f"CLAUDE.md Status line says {actual!r} but pyproject says "
            f"{expected!r}.\nUpdate the **Status:** line near the top of "
            f"{CLAUDE_MD_PATH}."
        )

    def test_python_version_matches(self) -> None:
        """`requires-python` in pyproject must equal the version we document.

        Oneiric docs say ``Python 3.13+``. ``pyproject.toml:6`` is the source
        of truth; if it changes, the docs must follow.
        """
        with PYPROJECT_PATH.open("rb") as f:
            data = tomllib.load(f)
        required = data.get("project", {}).get("requires-python", "")
        # Acceptable forms: ">=3.13", ">=3.13.5", ">=3.13,<4"
        match = re.search(r">=\s*(\d+\.\d+)", str(required))
        assert match, f"could not parse requires-python {required!r}"
        actual = match.group(1)

        # Spot-check the README badge (canonical, kept in sync by maintainers)
        with README_PATH.open(encoding="utf-8") as f:
            head = "".join(line for _, line in zip(range(20), f))
        badge_match = re.search(
            r"\[[!]\[Python:\s*(\d+\.\d+)\+?\(", head
        )
        if badge_match is None:
            pytest.skip("README Python badge pattern not found")
        badge_version = badge_match.group(1)
        assert badge_version == actual, (
            f"README badge says Python {badge_version}+ but pyproject "
            f"requires-python is {required!r}. Update the badge."
        )
