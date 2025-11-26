"""Shared persistence helpers for domain pause/drain state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from oneiric.core.logging import get_logger

logger = get_logger("activity")


@dataclass
class DomainActivity:
    paused: bool = False
    draining: bool = False
    note: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "paused": self.paused,
            "draining": self.draining,
            "note": self.note,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DomainActivity":
        return cls(
            paused=bool(data.get("paused", False)),
            draining=bool(data.get("draining", False)),
            note=data.get("note"),
        )

    def is_default(self) -> bool:
        return not self.paused and not self.draining and self.note is None


class DomainActivityStore:
    """JSON-backed persistence for domain pause/drain activity."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._cache: Dict[str, Dict[str, DomainActivity]] = {}
        self._loaded = False
        self._mtime: Optional[float] = None

    def get(self, domain: str, key: str) -> DomainActivity:
        data = self._load()
        state = data.get(domain, {}).get(key)
        if state:
            return state
        return DomainActivity()

    def all_for_domain(self, domain: str) -> Dict[str, DomainActivity]:
        data = self._load()
        return dict(data.get(domain, {}))

    def set(self, domain: str, key: str, state: DomainActivity) -> None:
        data = self._load()
        domain_map = data.setdefault(domain, {})
        if state.is_default():
            if key in domain_map:
                del domain_map[key]
            if not domain_map:
                data.pop(domain, None)
        else:
            domain_map[key] = state
        self._write(data)

    def snapshot(self) -> Dict[str, Dict[str, DomainActivity]]:
        data = self._load()
        return {domain: dict(entries) for domain, entries in data.items()}

    # internal -----------------------------------------------------------------

    def _load(self) -> Dict[str, Dict[str, DomainActivity]]:
        current_mtime = self._stat_mtime()
        if self._loaded and current_mtime == self._mtime:
            return self._cache
        payload = self._read_payload()
        cache: Dict[str, Dict[str, DomainActivity]] = {}
        for domain, entries in payload.items():
            domain_map: Dict[str, DomainActivity] = {}
            if not isinstance(entries, Mapping):
                continue
            for key, raw_state in entries.items():
                if not isinstance(raw_state, Mapping):
                    continue
                domain_map[str(key)] = DomainActivity.from_mapping(raw_state)
            if domain_map:
                cache[str(domain)] = domain_map
        self._cache = cache
        self._loaded = True
        self._mtime = current_mtime
        return self._cache

    def _read_payload(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except Exception as exc:  # pragma: no cover - log diagnostic
            logger.warning("activity-load-failed", path=str(self.path), error=str(exc))
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write(self, data: Dict[str, Dict[str, DomainActivity]]) -> None:
        payload: Dict[str, Dict[str, Any]] = {}
        for domain, entries in data.items():
            if not entries:
                continue
            payload[domain] = {key: state.as_dict() for key, state in entries.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(self.path)
        self._cache = data
        self._loaded = True
        self._mtime = self._stat_mtime()

    def _stat_mtime(self) -> Optional[float]:
        try:
            return self.path.stat().st_mtime
        except FileNotFoundError:
            return None
