"""Render per-store tables + distribution footer.

Verbatim port of the rendering logic from
`mahavishnu/scripts/regenerate_plan_index.py:_render_with_components`,
adapted to receive pre-parsed Entry dicts instead of filesystem walks.
"""

from __future__ import annotations

from collections import Counter
from itertools import chain

from oneiric.plan_index.entry import Entry

LIFECYCLE_VALUES: tuple[str, ...] = (
    "draft",
    "active",
    "partial",
    "shipped",
    "complete",
)


def render_index(*, entries_by_store: dict[str, list[Entry]], generated_at: str) -> str:
    """Render the per-store tables + distribution footer as one Markdown string."""
    # Per-store tables
    sections: list[str] = [
        _render_store_table(
            store, sorted(entries, key=lambda e: (-_date_key(e.date), e.rel))
        )
        for store, entries in entries_by_store.items()
    ]
    # Distribution footer
    sections.append(
        _render_distribution(
            all_entries=list(chain.from_iterable(entries_by_store.values()))
        )
    )
    return "\n\n".join(sections) + "\n"


def _date_key(value: str) -> int:
    if not value:
        return 0
    from re import match

    m = match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    if not m:
        return 0
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))


def _render_store_table(store: str, entries: list[Entry]) -> str:
    label = store.rstrip("/").replace("docs/", "Docs: ").replace(".claude/", ".claude/")
    rows = [
        f"### {label}",
        "",
        "| Path | Date | Status | Role | Kind | Topic | Title |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        rows.append(
            f"| `{e.rel}` | {e.date or '—'} | `{e.status}` | `{e.role}` | `{e.kind}` | `{e.topic}` | {e.title} |"
        )
    return "\n".join(rows)


def _render_distribution(all_entries: list[Entry]) -> str:
    counts: Counter[tuple[str, str]] = Counter()
    for e in all_entries:
        if e.status not in LIFECYCLE_VALUES or e.role == "unknown":
            continue
        counts[(e.status, e.role)] += 1
    rows = [
        "## Lifecycle × Role Distribution",
        "",
        "| Role \\ Lifecycle | " + " | ".join(LIFECYCLE_VALUES) + " | Total |",
        "|---|" + "|".join(["---"] * (len(LIFECYCLE_VALUES) + 1)) + "|",
    ]
    grand = 0
    for role in ("canonical", "implementation", "umbrella", "historical", "superseded"):
        cells, row_total = [], 0
        for lc in LIFECYCLE_VALUES:
            v = counts.get((lc, role), 0)
            row_total += v
            cells.append(str(v) if v else "·")
        rows.append(f"| `{role}` | " + " | ".join(cells) + f" | **{row_total}** |")
        grand += row_total
    rows.append(
        "| **Total** | "
        + " | ".join(
            f"**{counts.get((lc, role), 0)}**"
            for role in (
                "canonical",
                "implementation",
                "umbrella",
                "historical",
                "superseded",
            )
            for lc in LIFECYCLE_VALUES
        )
        + f" | **{grand}** |"
    )
    return "\n".join(rows)
