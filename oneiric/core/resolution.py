"""Resolver and candidate registry."""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any,
)

from pydantic import BaseModel, ConfigDict, Field

from .logging import get_logger
from .observability import DecisionEvent, traced_decision

FactoryType = Callable[..., Any] | str
HealthCheck = Callable[[], bool] | None

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
    provider: str | None = None
    priority: int | None = None
    stack_level: int | None = None
    factory: FactoryType
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: CandidateSource = CandidateSource.LOCAL_PKG
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    health: HealthCheck = None
    registry_sequence: int | None = Field(default=None, exclude=True)

    def with_priority(self, priority: int) -> Candidate:
        return self.model_copy(update={"priority": priority})


class ResolverSettings(BaseModel):
    """Resolver behavior toggles and overrides."""

    default_priority: int = 0
    selections: dict[str, dict[str, str]] = Field(default_factory=dict)

    def selection_for(self, domain: str, key: str) -> str | None:
        return self.selections.get(domain, {}).get(key)


@dataclass
class CandidateRank:
    candidate: Candidate
    score: tuple[int, int, int, int]
    reasons: list[str]
    selected: bool = False


@dataclass
class ResolutionExplanation:
    domain: str
    key: str
    ordered: list[CandidateRank]

    @property
    def winner(self) -> Candidate | None:
        for entry in self.ordered:
            if entry.selected:
                return entry.candidate
        return None

    def as_dict(self) -> dict[str, Any]:
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

    def __init__(self, settings: ResolverSettings | None = None) -> None:
        self.settings = settings or ResolverSettings()
        self._logger = get_logger("resolver")
        self._candidates: defaultdict[tuple[str, str], list[Candidate]] = defaultdict(
            list
        )
        self._active: dict[tuple[str, str], Candidate | None] = {}
        self._shadowed: dict[tuple[str, str], list[Candidate]] = {}
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

    def resolve(
        self,
        domain: str,
        key: str,
        provider: str | None = None,
        capabilities: Iterable[str] | None = None,
        *,
        require_all: bool = True,
    ) -> Candidate | None:
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
            if provider:
                candidates = self._candidates.get((domain, key), [])
                for cand in candidates:
                    if cand.provider != provider:
                        continue
                    if capabilities and not _candidate_supports_capabilities(
                        cand, capabilities, require_all=require_all
                    ):
                        continue
                    return cand
                return None

            explanation = self._score_candidates(
                domain,
                key,
                capabilities=capabilities,
                require_all=require_all,
            )
            return explanation.winner

    def list_active(self, domain: str) -> list[Candidate]:
        """List all active candidates for a domain (thread-safe).

        Args:
            domain: Component domain

        Returns:
            List of active candidates

        Thread Safety:
            Acquires lock to ensure consistent snapshot.
        """
        with self._lock:
            return [
                cand
                for (cand_domain, _), cand in self._active.items()
                if cand_domain == domain and cand
            ]

    def list_shadowed(self, domain: str) -> list[Candidate]:
        """List all shadowed candidates for a domain (thread-safe).

        Args:
            domain: Component domain

        Returns:
            List of shadowed candidates

        Thread Safety:
            Acquires lock to ensure consistent snapshot.
        """
        with self._lock:
            shadowed: list[Candidate] = []
            for (cand_domain, _), cands in self._shadowed.items():
                if cand_domain == domain:
                    shadowed.extend(cands)
            return shadowed

    def explain(
        self,
        domain: str,
        key: str,
        *,
        capabilities: Iterable[str] | None = None,
        require_all: bool = True,
    ) -> ResolutionExplanation:
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
            return self._score_candidates(
                domain,
                key,
                capabilities=capabilities,
                require_all=require_all,
            )

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

    def _score_candidates(
        self,
        domain: str,
        key: str,
        *,
        capabilities: Iterable[str] | None = None,
        require_all: bool = True,
    ) -> ResolutionExplanation:
        candidates = self._candidates.get((domain, key), [])
        override_provider = self.settings.selection_for(domain, key)
        required = _normalize_capabilities(capabilities)
        ranked: list[CandidateRank] = []
        for cand in candidates:
            reasons: list[str] = []
            if required and not _candidate_supports_capabilities(
                cand, required, require_all=require_all
            ):
                continue
            override_score = int(
                bool(override_provider and cand.provider == override_provider)
            )
            if override_provider:
                if override_score:
                    reasons.append(f"matched selection override {override_provider}")
                else:
                    reasons.append(f"selection override prefers {override_provider}")
            priority = (
                cand.priority
                if cand.priority is not None
                else self.settings.default_priority
            )
            reasons.append(f"priority={priority}")
            capability_score = _capability_match_score(cand, required)
            if required:
                reasons.append(f"capability_match={capability_score}/{len(required)}")
            stack = cand.stack_level or 0
            reasons.append(f"stack_level={stack}")
            sequence = cand.registry_sequence or 0
            reasons.append(f"registration_order={sequence}")
            score = (override_score, capability_score, priority, stack, sequence)
            ranked.append(CandidateRank(candidate=cand, score=score, reasons=reasons))

        ranked.sort(key=lambda entry: entry.score, reverse=True)
        if ranked:
            ranked[0].selected = True

        return ResolutionExplanation(domain=domain, key=key, ordered=ranked)


def _env_priority_map() -> dict[str, int]:
    mapping: dict[str, int] = {}
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


def infer_priority(package_name: str | None, path: str | None) -> int:
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
    priority: int | None = None,
) -> None:
    inferred = priority if priority is not None else infer_priority(package_name, path)
    for cand in candidates:
        metadata = {"package": package_name, "path": path} | cand.metadata
        normalized = cand.model_copy(
            update={
                "priority": cand.priority if cand.priority is not None else inferred,
                "metadata": metadata,
                "source": cand.source or CandidateSource.LOCAL_PKG,
            }
        )
        registry.register_candidate(normalized)


class Resolver:
    """High-level facade that wraps the candidate registry."""

    def __init__(self, settings: ResolverSettings | None = None) -> None:
        self.settings = settings or ResolverSettings()
        self.registry = CandidateRegistry(self.settings)

    def register(self, candidate: Candidate) -> None:
        self.registry.register_candidate(candidate)

    def register_from_pkg(
        self,
        package_name: str,
        path: str,
        candidates: Iterable[Candidate],
        priority: int | None = None,
    ) -> None:
        register_pkg(self.registry, package_name, path, candidates, priority=priority)

    def resolve(
        self,
        domain: str,
        key: str,
        provider: str | None = None,
        capabilities: Iterable[str] | None = None,
        *,
        require_all: bool = True,
    ) -> Candidate | None:
        return self.registry.resolve(
            domain,
            key,
            provider=provider,
            capabilities=capabilities,
            require_all=require_all,
        )

    def list_active(self, domain: str) -> list[Candidate]:
        return self.registry.list_active(domain)

    def list_shadowed(self, domain: str) -> list[Candidate]:
        return self.registry.list_shadowed(domain)

    def explain(
        self,
        domain: str,
        key: str,
        *,
        capabilities: Iterable[str] | None = None,
        require_all: bool = True,
    ) -> ResolutionExplanation:
        return self.registry.explain(
            domain, key, capabilities=capabilities, require_all=require_all
        )


def _normalize_capabilities(
    capabilities: Iterable[str] | None,
) -> list[str]:
    if not capabilities:
        return []
    return [str(cap).strip() for cap in capabilities if str(cap).strip()]


def _candidate_supports_capabilities(
    candidate: Candidate,
    capabilities: Iterable[str] | None,
    *,
    require_all: bool,
) -> bool:
    required = _normalize_capabilities(capabilities)
    if not required:
        return True
    available = _candidate_capabilities(candidate)
    if require_all:
        return all(cap in available for cap in required)
    return any(cap in available for cap in required)


def _candidate_capabilities(candidate: Candidate) -> set[str]:
    metadata = candidate.metadata or {}
    capabilities = metadata.get("capabilities") or []
    descriptors = metadata.get("capability_descriptors") or []
    result: set[str] = set()
    if isinstance(capabilities, str):
        result.add(capabilities)
    elif isinstance(capabilities, Iterable):
        for item in capabilities:
            if isinstance(item, str):
                result.add(item)
    if isinstance(descriptors, Iterable):
        for item in descriptors:
            if isinstance(item, dict) and item.get("name"):
                result.add(str(item["name"]))
    return result


def _capability_match_score(candidate: Candidate, required: Iterable[str]) -> int:
    if not required:
        return 0
    available = _candidate_capabilities(candidate)
    return sum(1 for cap in required if cap in available)
