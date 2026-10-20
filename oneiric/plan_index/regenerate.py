"""Compose scan_entries + render_index + atomic_write."""

from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from oneiric.plan_index.discovery import scan_entries

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_OUT_PATH = "docs/plans/PLAN_INDEX.md"


def regenerate(
    repo_root: Path,
    *,
    out_path: Path | None = None,
    exclude: Sequence[str] = (),
    check: bool = False,
) -> int:
    """Render and atomically write PLAN_INDEX.md. Exit 1 on drift if check=True."""
    if out_path is None:
        out_path = repo_root / DEFAULT_OUT_PATH
    entries_by_store = scan_entries(repo_root, exclude=exclude)

    from oneiric.plan_index.render import render_index

    rendered = render_index(
        entries_by_store=entries_by_store,
        generated_at=datetime.datetime.now(datetime.UTC).date().isoformat(),
    )

    if check:
        existing = out_path.read_text() if out_path.is_file() else ""
        if existing != rendered:
            print(
                f"--check: drift detected ({out_path}); rendered vs current differ.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(f"--check: {out_path} is up-to-date.")
            sys.exit(0)

    # Atomic write
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(out_path.parent),
        prefix=f".{out_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(rendered)
        tmp_path = Path(tmp.name)
    tmp_path.replace(out_path)
    return sum(len(es) for es in entries_by_store.values())
