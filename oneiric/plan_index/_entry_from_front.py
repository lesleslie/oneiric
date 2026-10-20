"""Convert parsed frontmatter into an Entry."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from oneiric.plan_index.entry import Entry


def entry_from_front(
    abs_path: Path, rel: str, store: str, text: str, front: dict[str, Any]
) -> Entry:
    raw_date = front.get("date")
    if isinstance(raw_date, date) and not isinstance(raw_date, datetime):
        date_str = raw_date.isoformat()
    elif isinstance(raw_date, datetime):
        date_str = raw_date.date().isoformat()
    elif isinstance(raw_date, str):
        date_str = raw_date
    else:
        date_str = ""
    status_raw: object = front.get("status")
    role_raw: object = front.get("role")
    kind_raw: object = front.get("kind")
    topic_raw: object = front.get("topic")
    status = status_raw if isinstance(status_raw, str) else "unknown"
    role = role_raw if isinstance(role_raw, str) else "unknown"
    kind = kind_raw if isinstance(kind_raw, str) else "plan"
    topic = topic_raw if isinstance(topic_raw, str) else "—"
    fallback = abs_path.stem.replace("-", " ").replace("_", " ")
    title = next(
        (
            line[2:].strip()
            for line in text.splitlines()
            if line.strip().startswith("# ")
        ),
        fallback,
    )
    return Entry(
        rel=rel,
        store=store,
        date=date_str,
        status=status,
        role=role,
        kind=kind,
        topic=topic,
        title=title,
    )
