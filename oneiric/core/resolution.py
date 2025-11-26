"""Resolver and candidate registry."""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, DefaultDict, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .logging import get_logger
from .observability import DecisionEvent, traced_decision

FactoryType = Callable[..., Any] | str
HealthCheck = Optional[Callable[[], bool]]

STACK_ORDER_ENV = "ONEIRIC_STACK_ORDER"
PATH_PRIORITY_HINTS = [
    ("adapters", 80),
    ("services", 70),
    ("tasks", 60),
    ("events", 60),
    ("workflows", 60),
    ("vendor", 90),
]


class CandidateSource(str, Enum):
    LOCAL_PKG = "local_pkg"
    REMOTE_MANIFEST = "remote_manifest"
    ENTRY_POINT = "entry_point"
    MANUAL = "manual"


class Candidate(BaseModel):
    """Normalized representation of a resolvable component."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    domain: str
    key: str
    provider: Optional[str] = None
    priority: Optional[int] = None
    stack_level: Optional[int] = None
    factory: FactoryType
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source: CandidateSource = CandidateSource.LOCAL_PKG
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    health: HealthCheck = None
    registry_sequence: Optional[int] = Field(default=None, exclude=True)

    def with_priority(self, priority: int) -> "Candidate":
        return self.model_copy(update={"priority": priority})


class ResolverSettings(BaseModel):
    """Resolver behavior toggles and overrides."""

    default_priority: int = 0
    selections: Dict[str, Dict[str, str]] = Field(default_factory=dict)

    def selection_for(self, domain: str, key: str) -> Optional[str]:
        return self.selections.get(domain, {}).get(key)


@dataclass
class CandidateRank:
    candidate: Candidate
    score: Tuple[int, int, int, int]
    reasons: List[str]
    selected: bool = False


@dataclass
class ResolutionExplanation:
    domain: str
    key: str
    ordered: List[CandidateRank]

    @property
    def winner(self) -> Optional[Candidate]:
        for entry in self.ordered:
            if entry.selected:
                return entry.candidate
        return None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "key": self.key,
            "ordered": [
                {
                    "provider": entry.candidate.provider,
                    "score": entry.score,
                    "selected": entry.selected,
                    "reasons": entry.reasons,
                }
                for entry in self.ordered
            ],
        }


class CandidateRegistry:
    """Thread-safe registry for component candidates.

    This registry manages component resolution with 4-tier precedence:
    1. Explicit override (selections in config)
    2. Inferred priority (from ONEIRIC_STACK_ORDER or path hints)
    3. Stack level (Z-index style layering)
    4. Registration order (last registered wins)

    Thread Safety:
        All public methods are thread-safe using a reentrant lock (RLock).
        The lock allows the same thread to acquire it multiple times,
        which is necessary for methods that call other methods internally.

    Example:
        >>> registry = CandidateRegistry()
        >>> registry.register_candidate(candidate)  # Thread-safe
        >>> active = registry.resolve("adapter", "cache")  # Thread-safe
    """

    def __init__(self, settings: Optional[ResolverSettings] = None) -> None:
        self.settings = settings or ResolverSettings()
        self._logger = get_logger("resolver")
        self._candidates: DefaultDict[Tuple[str, str], List[Candidate]] = defaultdict(list)
        self._active: Dict[Tuple[str, str], Optional[Candidate]] = {}
        self._shadowed: Dict[Tuple[str, str], List[Candidate]] = {}
        self._sequence = 0
        self._lock = threading.RLock()  # Reentrant lock for thread safety

    # Public API -----------------------------------------------------------------

    def register_candidate(self, candidate: Candidate) -> None:
        """Register a new candidate (thread-safe).

        Args:
            candidate: Candidate to register

        Thread Safety:
            Uses internal lock to ensure atomic registration and recomputation.
        """
        with self._lock:
            stored = candidate.model_copy(deep=True)
            if stored.priority is None:
                stored.priority = self.settings.default_priority
            self._sequence += 1
            stored.registry_sequence = self._sequence
            key = (stored.domain, stored.key)
            self._candidates[key].append(stored)
            self._logger.debug(
                "candidate-registered",
                domain=stored.domain,
                key=stored.key,
                provider=stored.provider,
                priority=stored.priority,
                stack_level=stored.stack_level,
                source=stored.source.value,
            )
            self._recompute(stored.domain, stored.key)

    def resolve(self, domain: str, key: str, provider: Optional[str] = None) -> Optional[Candidate]:
        """Resolve a candidate (thread-safe).

        Args:
            domain: Component domain
            key: Component key
            provider: Optional provider filter

        Returns:
            Resolved candidate or None

        Thread Safety:
            Read operation protected by lock for consistency.
        """
        with self._lock:
            active = self._active.get((domain, key))
            if provider:
                candidates = self._candidates.get((domain, key), [])
                for cand in candidates:
                    if cand.provider == provider:
                        return cand
                return None
            return active

    def list_active(self, domain: str) -> List[Candidate]:
        """List all active candidates for a domain (thread-safe).

        Args:
            domain: Component domain

        Returns:
            List of active candidates

        Thread Safety:
            Acquires lock to ensure consistent snapshot.
        """
        with self._lock:
            return [cand for (cand_domain, _), cand in self._active.items() if cand_domain == domain and cand]

    def list_shadowed(self, domain: str) -> List[Candidate]:
        """List all shadowed candidates for a domain (thread-safe).

        Args:
            domain: Component domain

        Returns:
            List of shadowed candidates

        Thread Safety:
            Acquires lock to ensure consistent snapshot.
        """
        with self._lock:
            shadowed: List[Candidate] = []
            for (cand_domain, _), cands in self._shadowed.items():
                if cand_domain == domain:
                    shadowed.extend(cands)
            return shadowed

    def explain(self, domain: str, key: str) -> ResolutionExplanation:
        """Explain resolution decision (thread-safe).

        Args:
            domain: Component domain
            key: Component key

        Returns:
            Detailed resolution explanation

        Thread Safety:
            Acquires lock to ensure consistent scoring.
        """
        with self._lock:
            return self._score_candidates(domain, key)

    # Internal helpers -----------------------------------------------------------

    def _recompute(self, domain: str, key: str) -> None:
        explanation = self._score_candidates(domain, key)
        winner = explanation.winner
        self._active[(domain, key)] = winner
        self._shadowed[(domain, key)] = [
            entry.candidate for entry in explanation.ordered if not entry.selected
        ]

        event = DecisionEvent(
            domain=domain,
            key=key,
            provider=winner.provider if winner else None,
            decision="resolved",
            details=explanation.as_dict(),
        )
        with traced_decision(event):
            pass

    def _score_candidates(self, domain: str, key: str) -> ResolutionExplanation:
        candidates = self._candidates.get((domain, key), [])
        override_provider = self.settings.selection_for(domain, key)
        ranked: List[CandidateRank] = []
        for cand in candidates:
            reasons: List[str] = []
            override_score = int(bool(override_provider and cand.provider == override_provider))
            if override_provider:
                if override_score:
                    reasons.append(f"matched selection override {override_provider}")
                else:
                    reasons.append(f"selection override prefers {override_provider}")
            priority = cand.priority or self.settings.default_priority
            reasons.append(f"priority={priority}")
            stack = cand.stack_level or 0
            reasons.append(f"stack_level={stack}")
            sequence = cand.registry_sequence or 0
            reasons.append(f"registration_order={sequence}")
            score = (override_score, priority, stack, sequence)
            ranked.append(CandidateRank(candidate=cand, score=score, reasons=reasons))

        ranked.sort(key=lambda entry: entry.score, reverse=True)
        if ranked:
            ranked[0].selected = True

        return ResolutionExplanation(domain=domain, key=key, ordered=ranked)


def _env_priority_map() -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    raw = os.getenv(STACK_ORDER_ENV, "")
    if not raw:
        return mapping
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            name, value = token.split(":", 1)
            mapping[name.strip()] = int(value.strip())
        else:
            mapping[token] = len(mapping) * 10
    return mapping


def infer_priority(package_name: Optional[str], path: Optional[str]) -> int:
    env_map = _env_priority_map()
    if package_name and package_name in env_map:
        return env_map[package_name]
    if path:
        path_obj = Path(path)
        depth_penalty = min(len(path_obj.parts), 10)
        for marker, value in PATH_PRIORITY_HINTS:
            if marker in path_obj.parts:
                return value - depth_penalty
    return 0


def register_pkg(
    registry: CandidateRegistry,
    package_name: str,
    path: str,
    candidates: Iterable[Candidate],
    priority: Optional[int] = None,
) -> None:
    inferred = priority if priority is not None else infer_priority(package_name, path)
    for cand in candidates:
        metadata = {"package": package_name, "path": path, **cand.metadata}
        normalized = cand.model_copy(
            update={
                "priority": cand.priority if cand.priority is not None else inferred,
                "metadata": metadata,
                "source": cand.source if cand.source else CandidateSource.LOCAL_PKG,
            }
        )
        registry.register_candidate(normalized)


class Resolver:
    """High-level facade that wraps the candidate registry."""

    def __init__(self, settings: Optional[ResolverSettings] = None) -> None:
        self.settings = settings or ResolverSettings()
        self.registry = CandidateRegistry(self.settings)

    def register(self, candidate: Candidate) -> None:
        self.registry.register_candidate(candidate)

    def register_from_pkg(
        self,
        package_name: str,
        path: str,
        candidates: Iterable[Candidate],
        priority: Optional[int] = None,
    ) -> None:
        register_pkg(self.registry, package_name, path, candidates, priority=priority)

    def resolve(self, domain: str, key: str, provider: Optional[str] = None) -> Optional[Candidate]:
        return self.registry.resolve(domain, key, provider=provider)

    def list_active(self, domain: str) -> List[Candidate]:
        return self.registry.list_active(domain)

    def list_shadowed(self, domain: str) -> List[Candidate]:
        return self.registry.list_shadowed(domain)

    def explain(self, domain: str, key: str) -> ResolutionExplanation:
        return self.registry.explain(domain, key)
