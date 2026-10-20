from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Entry:
    rel: str
    store: str
    date: str
    status: str
    role: str
    kind: str
    topic: str
    title: str
