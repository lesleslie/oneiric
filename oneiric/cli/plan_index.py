"""Typer subcommand for the plan_index library."""

from __future__ import annotations

from pathlib import Path

import typer

plan_index_app = typer.Typer(
    name="plan-index",
    help="Regenerate PLAN_INDEX.md from per-store frontmatter.",
)


@plan_index_app.command(name="regenerate")
def regenerate(
    repo_root: Path = typer.Option(..., "--repo-root", help="Repo root to walk"),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Override output path (default: <repo_root>/docs/plans/PLAN_INDEX.md)",
    ),
) -> None:
    """Regenerate the PLAN_INDEX.md for the given repo."""
    from oneiric.plan_index import regenerate as regen_fn

    count = regen_fn(
        repo_root=repo_root.resolve(), out_path=(out.resolve() if out else None)
    )
    typer.echo(f"wrote {count} entries", err=False)
