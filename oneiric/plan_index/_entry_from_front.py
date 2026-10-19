"""Convert parsed frontmatter into an Entry."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import Any
from oneiric.plan_index.entry import Entry

def entry_from_front(abs_path: Path, rel: str, store: str, text: str, front: dict[str, Any]) -> Entry:
    raw_date = front.get("date")
    if isinstance(raw_date, date) and not isinstance(raw_date, datetime):
        date_str = raw_date.isoformat()
    elif isinstance(raw_date, datetime):
        date_str = raw_date.date().isoformat()
    elif isinstance(raw_date, str):
        date_str = raw_date
    else:
        date_str = ""
    status = front.get("status") if isinstance(front.get("status"), str) else "unknown"
    role = front.get("role") if isinstance(front.get("role"), str) else "unknown"
    kind = front.get("kind") if isinstance(front.get("kind"), str) else "plan"
    topic = front.get("topic") if isinstance(front.get("topic"), str) else "—"
    fallback = abs_path.stem.replace("-", " ").replace("_", " ")
    title = next(
        (line[2:].strip() for line in text.splitlines() if line.strip().startswith("# ")),
        fallback,
    )
    return Entry(rel=rel, store=store, date=date_str, status=status, role=role, kind=kind, topic=topic, title=title)
