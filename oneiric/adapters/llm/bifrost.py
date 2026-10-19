"""Bifrost gateway as a oneiric LLM router.

This module is the canonical entry point for resolving LLM provider
URLs through the local Bifrost gateway (``localhost:8471`` by default).
It does **not** perform HTTP transport — it returns gateway URLs that
callers hand to their existing transport (e.g. ``mcp_common.llm.OpenAICompatibleProvider``).

Why a standalone class instead of subclassing ``LLMBase``?
---------------------------------------------------------

``LLMBase`` is a full HTTP-transport ABC with 8 abstract methods
(``init``, ``health``, ``cleanup``, ``_chat``, ``_chat_stream``,
``_get_model_info``, ``_list_models``, ``_ensure_client``). A URL
resolver does not need any of those — implementing them would be
theater. ``LLMBaseSettings`` similarly carries 21 LLM-client fields
the router doesn't need, including a silent-accept ``api_key: SecretStr``
that would mask operator misconfiguration.

The router therefore extends ``pydantic_settings.BaseSettings`` directly
and exposes a single ``resolve(provider) -> str | None`` method. The
oneiric adapter catalog picks it up via ``BifrostLLMRouter.metadata``,
which is registered lazily in ``builtin_adapter_metadata()`` to avoid
importing the new module on every oneiric cold start (per 3-agent
review F8 fix).

SSRF defense — responsibility boundary
--------------------------------------

The :meth:`BifrostLLMSettings._check_loopback_and_imds` validator
inspects the **URL string** at settings-construction time. It
rejects:

- Non-loopback hosts (unless ``BIFROST_ALLOW_REMOTE=1`` is set)
- AWS / GCP / Azure IMDS IPs and hostnames (``169.254.169.254``,
  ``metadata.google.internal``, etc.)
- RFC1918 ranges (``10/8``, ``172.16/12``, ``192.168/16``) when
  the opt-in flag is set

**What the validator does NOT catch — DNS rebinding.** A hostname
like ``attacker.com`` that resolves to ``127.0.0.1`` at config
time (passing the loopback default) could resolve to
``169.254.169.254`` at request time. Static URL-string validation
cannot prevent this. The defense belongs to the **transport layer**
(``mcp_common.llm.OpenAICompatibleProvider`` and downstream HTTP
clients): resolve the host, validate the resolved IP against the
same loopback / IMDS / RFC1918 rules, and reject mismatches.

**What the validator does NOT catch — HTTPS downgrade.** A config
that points at ``https://attacker.com`` and resolves to a private
IP is still rejected at config time (the IP is checked, not the
scheme), but operators who flip to ``BIFROST_ALLOW_REMOTE=1`` to
test against a public gateway and then forget to unset the flag
are creating a wider attack surface than they intended. The opt-in
log line records the operator identity so audit trails surface the
flag flip.

Privacy posture
---------------

By default the router does **not** log operator identity or hostname.
``BIFROST_LOG_OPERATOR_IDENTITY=1`` opts IN to recording the
operator's ``getpass.getuser()`` and ``socket.gethostname()`` in
the structured log line emitted when the non-loopback opt-in is
used. The default is OFF (PII-safe).

Public API
----------

- :class:`RouteKind` — the set of routable gateway roles
  (``CLAUDE_ROUTE``, ``QWEN_ROUTE``).
- :class:`BifrostLLMSettings` — Pydantic v2 settings with
  ``env_prefix="ONEIRIC_BIFROST_"`` and a back-compat shim for
  ``MAHAVISHNU_BIFROST__*`` (deprecated).
- :class:`BifrostLLMRouter` — the URL resolver. Has a class-level
  ``metadata`` for the oneiric catalog and a ``resolve`` method.
- :func:`get_router` — process-cached singleton. The canonical entry
  point for every consumer; structural guarantee against config drift.
- :func:`reset_router_for_tests` — test seam. Clears the cache.
"""

from __future__ import annotations

import getpass
import ipaddress
import os
import socket
import warnings
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .llm_interface import LLMProvider

logger = get_logger("adapter.llm.bifrost")

# ---------------------------------------------------------------------------
# SSRF / IMDS / RFC1918 blocklist
# ---------------------------------------------------------------------------

# AWS / GCP / Azure metadata IPs and hostnames
_IMDS_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.azure.com",
    }
)

# IPv4 / IPv6 ranges the opt-in path explicitly rejects
_RFC1918_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.169.254/32"),  # AWS + Azure IMDS
    ipaddress.IPv4Network("169.254.169.253/32"),  # AWS IMDS alt
    ipaddress.IPv4Network("100.100.100.200/32"),  # GCP IMDS
    ipaddress.IPv6Network("fd00:ec2::254/128"),  # AWS IMDS IPv6
    ipaddress.IPv6Network("fe80::/10"),  # link-local
    ipaddress.IPv6Network("::1/128"),  # loopback IPv6
)


def _strip_brackets(host: str) -> str:
    """Strip IPv6 brackets from a Pydantic ``HttpUrl.host`` value.

    Pydantic v2 returns IPv6 hosts with surrounding brackets (e.g.
    ``[fd00:ec2::254]``) so callers that compare against a bare
    hostname stay aligned. The stdlib ``ipaddress.ip_address`` parser
    does not accept the bracketed form, so we normalize here.
    """
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _is_loopback(host: str) -> bool:
    """Return True for loopback hosts (127.0.0.1, ::1, localhost)."""
    normalized = _strip_brackets(host)
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_blocked_remote(host: str) -> bool:
    """Return True for IMDS / RFC1918 hosts that the opt-in path rejects."""
    normalized = _strip_brackets(host)
    if normalized.lower() in _IMDS_HOSTNAMES:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    for net in _RFC1918_NETWORKS:
        # The `ip in net` operator is type-strict on the network side:
        # IPv4Address in IPv4Network returns True/False; an IPv4Address
        # in an IPv6Network raises TypeError. Filter by version first
        # to keep the loop safe and explicit.
        if ip.version != net.version:
            continue
        if ip in net:
            return True
    return False


# ---------------------------------------------------------------------------
# RouteKind — 2-value routing policy
# ---------------------------------------------------------------------------


class RouteKind(StrEnum):
    """The set of routable gateway roles.

    Renamed from ``CLAUDE_CODE`` / ``QWEN_CODE`` to avoid the value-
    collision footgun with ``worker_type == "terminal-claude"`` (3-agent
    review F5 fix). The values are explicit strings, not the enum name.
    """

    CLAUDE_ROUTE = "claude_route"
    QWEN_ROUTE = "qwen_route"


# ---------------------------------------------------------------------------
# BifrostLLMSettings — Pydantic v2 settings, NOT LLMBaseSettings
# ---------------------------------------------------------------------------


# Map from the legacy env-var name to the settings field name. Used by
# the back-compat shim in :meth:`BifrostLLMSettings._load_legacy_env`.
_LEGACY_ENV_TO_FIELD: Mapping[str, str] = {
    "MAHAVISHNU_BIFROST__ENABLED": "enabled",
    "MAHAVISHNU_BIFROST__BASE_URL": "base_url",
    "MAHAVISHNU_BIFROST__ANTHROPIC_BASE_URL": "anthropic_base_url",
    "MAHAVISHNU_BIFROST__ROUTES": "routes",
    "MAHAVISHNU_BIFROST__QWEN_ENV_VAR": "qwen_env_var",
    "MAHAVISHNU_BIFROST__CALLER_ID": "caller_id",
    "MAHAVISHNU_BIFROST__AUTH_ENV": "auth_env",
    "MAHAVISHNU_BIFROST__CACHE_MODE": "cache_mode",
    "MAHAVISHNU_BIFROST__CACHE_TTL_SECONDS": "cache_ttl_seconds",
    "MAHAVISHNU_BIFROST__LOCAL_PROVIDER_ENABLED": "local_provider_enabled",
    "MAHAVISHNU_BIFROST__LOCAL_PROVIDER_URL": "local_provider_url",
}

# Fields that need explicit type coercion when read from env vars
_LEGACY_BOOL_FIELDS: frozenset[str] = frozenset({"enabled", "local_provider_enabled"})
_LEGACY_INT_FIELDS: frozenset[str] = frozenset({"cache_ttl_seconds"})


class BifrostLLMSettings(BaseSettings):
    """Settings for the Bifrost router.

    Extends :class:`pydantic_settings.BaseSettings` directly. Does
    **not** subclass :class:`LLMBaseSettings` — the inherited 21
    LLM-client fields (and the silent-accept ``api_key: SecretStr``)
    are intentionally excluded (3-agent review type F3 + security F-09).

    Env-var prefix: ``ONEIRIC_BIFROST_`` (e.g. ``ONEIRIC_BIFROST__ENABLED``).
    Legacy ``MAHAVISHNU_BIFROST__*`` env vars are honored via a back-compat
    shim that emits one ``DeprecationWarning`` and one structured INFO
    log line ``legacy_env_prefix_in_use`` (REQ-BIFROST-011).
    """

    model_config = SettingsConfigDict(
        env_prefix="ONEIRIC_BIFROST_",
        env_nested_delimiter="__",
        extra="allow",
        populate_by_name=True,
    )

    enabled: bool = Field(default=False)
    # The default MUST include ``/v1``: the OpenAI-compatible endpoint on
    # the Bifrost gateway is served at ``/v1/chat/completions`` (not
    # ``/chat/completions``). The legacy ``BifrostClient.DEFAULT_BASE_URL``
    # was ``http://localhost:8471/v1``; this default restores that
    # contract. Without the ``/v1``, every gateway call returns 404
    # unless the operator explicitly sets ``ONEIRIC_BIFROST_BASE_URL``
    # (cross-repo B2 BLOCKER documented in plan 6 / Phase 4 commits).
    base_url: HttpUrl = Field(default=HttpUrl("http://127.0.0.1:8471/v1"))
    anthropic_base_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8471/anthropic")
    )
    # ``NoDecode`` tells pydantic-settings to NOT try to parse the env-var
    # value as a complex type (set[StrEnum]) — the raw string is
    # forwarded to ``_split_routes`` below, which splits commas and
    # hands the result to Pydantic's normal field coercion. Without
    # ``NoDecode``, the env source's ``prepare_field_value`` raises
    # ``SettingsError: error parsing value for field "routes"`` for any
    # value containing a comma (3-agent general-purpose BLOCKER).
    routes: Annotated[set[RouteKind], NoDecode] = Field(default_factory=set)
    qwen_env_var: str = Field(default="OPENAI_BASE_URL")
    caller_id: str = Field(default="")

    # Redeclared fields for consumer compatibility (3-agent B-1 fix).
    # These have live consumers in mahavishnu/health.py,
    # mahavishnu/core/health.py, and the (deleted-in-Phase-7)
    # mahavishnu/llm_gateway/contract.py — they cannot be dropped.
    auth_env: str = Field(default="MAHAVISHNU_BIFROST_AUTH_TOKEN")
    cache_mode: Literal["off", "direct", "semantic"] = "off"
    cache_ttl_seconds: int = 0
    local_provider_enabled: bool = Field(default=False)
    local_provider_url: HttpUrl | None = None

    # Centralized exclusion list for the /health.bifrost.config probe
    # and any other surface that serializes the settings (REQ-BIFROST-017,
    # 3-agent security F-02 fix).
    _SENSITIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"auth_env"})

    @field_validator("routes", mode="before")
    @classmethod
    def _split_routes(cls, value: Any) -> Any:
        """Split a comma-separated env-var string for the ``routes`` set.

        Pydantic v2 does not natively split comma-separated values for
        ``set[StrEnum]`` — the env-var value comes in as a single
        string like ``"claude_route,qwen_route"``. Without this
        validator, ``ONEIRIC_BIFROST_ROUTES=claude_route,qwen_route``
        raises ``SettingsError: error parsing value for field
        "routes"`` (3-agent general-purpose BLOCKER finding).
        """
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return value

    @model_validator(mode="before")
    @classmethod
    def _load_legacy_env(cls, data: Any) -> Any:
        """Back-compat shim for the legacy ``MAHAVISHNU_BIFROST__*`` env prefix.

        REQ-BIFROST-011. Emits one ``DeprecationWarning`` AND one
        structured INFO log line ``legacy_env_prefix_in_use`` with
        ``prefix`` and ``operator`` fields (security F-06 fix —
        ``DeprecationWarning`` is silent in production, so the log is
        the operator-visible surface).
        """
        if not isinstance(data, dict):
            return data

        legacy_used = any(key.startswith("MAHAVISHNU_BIFROST__") for key in os.environ)
        new_used = any(key.startswith("ONEIRIC_BIFROST_") for key in os.environ)

        if not legacy_used or new_used:
            return data

        warnings.warn(
            (
                "MAHAVISHNU_BIFROST__* env vars are deprecated; "
                "use ONEIRIC_BIFROST__* instead. The legacy prefix "
                "will be removed in a future release."
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        logger.info(
            "legacy_env_prefix_in_use",
            prefix="MAHAVISHNU_BIFROST__",
            operator=getpass.getuser(),
        )

        for env_key, field_name in _LEGACY_ENV_TO_FIELD.items():
            if field_name in data:
                # New prefix value wins
                continue
            if env_key not in os.environ:
                continue
            raw = os.environ[env_key]
            if field_name in _LEGACY_BOOL_FIELDS:
                data[field_name] = raw.strip().lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )
            elif field_name in _LEGACY_INT_FIELDS:
                # Skip empty / whitespace values — ``int("")`` would
                # raise ``ValueError`` and surface a confusing error
                # to operators who set ``MAHAVISHNU_BIFROST__CACHE_TTL_SECONDS=``
                # intending to clear the value. The Pydantic default
                # ``0`` then wins (3-agent MED finding).
                if raw.strip():
                    try:
                        data[field_name] = int(raw)
                    except ValueError:
                        # Non-integer values fall through to Pydantic's
                        # own validator, which reports a precise error.
                        pass
            elif field_name == "routes":
                data[field_name] = [
                    value.strip() for value in raw.split(",") if value.strip()
                ]
            else:
                data[field_name] = raw
        return data

    @model_validator(mode="after")
    def _check_loopback_and_imds(self) -> BifrostLLMSettings:
        """SSRF defense: Pydantic HttpUrl + loopback-only default + IMDS/RFC1918 blocklist.

        REQ-BIFROST-016. Defense layers:

        1. Scheme allowlist: only ``http`` and ``https`` are accepted
           (Pydantic's ``HttpUrl`` already validates the scheme as
           ``http`` or ``https`` per the URL spec, so this is automatic).
        2. Default: loopback-only. Non-loopback URLs raise
           ``ValueError`` unless ``BIFROST_ALLOW_REMOTE=1`` is set.
        3. Opt-in path: even with ``BIFROST_ALLOW_REMOTE=1``, AWS / GCP
           / Azure IMDS IPs and RFC1918 ranges are rejected. A
           metadata hostname (``metadata.google.internal``) is also
           rejected.
        4. Opt-in is logged at INFO. By default the log line
           records **only** the ``allow_remote_opt_in=true`` flag
           flip — no operator identity. Set
           ``BIFROST_LOG_OPERATOR_IDENTITY=1`` to opt IN to recording
           the operator's ``getpass.getuser()`` and
           ``socket.gethostname()``. The default is OFF so a
           non-loopback flip on a shared host does not leak PII into
           the audit log.
        """
        allow_remote = os.environ.get("BIFROST_ALLOW_REMOTE") == "1"

        for field_name in ("base_url", "anthropic_base_url", "local_provider_url"):
            url: HttpUrl | None = getattr(self, field_name, None)
            if url is None:
                continue
            scheme = url.scheme
            if scheme not in {"http", "https"}:
                raise ValueError(
                    f"BifrostLLMSettings.{field_name}: scheme '{scheme}' not "
                    f"allowed; must be one of {{'http', 'https'}}"
                )
            host = url.host or ""
            if _is_loopback(host):
                continue
            if not allow_remote:
                raise ValueError(
                    f"BifrostLLMSettings.{field_name}: non-loopback host "
                    f"'{host}' rejected. Set BIFROST_ALLOW_REMOTE=1 to "
                    f"opt in to non-loopback URLs."
                )
            if _is_blocked_remote(host):
                raise ValueError(
                    f"BifrostLLMSettings.{field_name}: host '{host}' is on "
                    f"the IMDS / RFC1918 blocklist. Non-loopback opt-in "
                    f"does not permit AWS / GCP / Azure metadata endpoints "
                    f"or RFC1918 ranges."
                )

        if allow_remote:
            # Operator identity is **opt-IN**. The default is OFF so
            # operators who flip the non-loopback flag do not
            # inadvertently leak PII into the audit log on a
            # shared-host deployment. Set ``BIFROST_LOG_OPERATOR_IDENTITY=1``
            # to record the operator's ``getpass.getuser()`` and
            # ``socket.gethostname()`` alongside the opt-in event.
            log_identity = os.environ.get("BIFROST_LOG_OPERATOR_IDENTITY", "0") == "1"
            extra: dict[str, Any] = {"allow_remote_opt_in": True}
            if log_identity:
                extra["operator"] = getpass.getuser()
                extra["hostname"] = socket.gethostname()
            logger.info("bifrost_allow_remote_opt_in", **extra)
        return self

    def _effective_exclude(self, exclude: Any) -> Any:
        """Merge ``_SENSITIVE_FIELDS`` with the caller's ``exclude``.

        Pydantic v2's native ``IncEx`` is
        ``set[int] | set[str] | dict[int, Any] | dict[str, Any] | None``
        (defined in ``pydantic.main`` but not re-exported from
        ``pydantic.__init__``). We type the parameter as ``Any`` and
        handle every form so the override does not narrow the type:

        - ``None`` (default) → exclude ``_SENSITIVE_FIELDS``
        - empty ``set()`` → opt-in to inclusion of everything
          (including sensitive fields)
        - non-empty ``set`` → caller-supplied fields + sensitive fields
        - ``dict`` (nested exclusion) → merge sensitive field names
          into the str-keyed dict so they're also excluded
        - empty ``dict`` → opt-in via the dict path
        """
        if exclude is None:
            return set(self._SENSITIVE_FIELDS)
        if isinstance(exclude, set):
            if not exclude:  # empty set = explicit opt-in
                return set()
            return exclude | set(self._SENSITIVE_FIELDS)
        if isinstance(exclude, dict):
            merged = dict(exclude)
            for field_name in self._SENSITIVE_FIELDS:
                merged.setdefault(field_name, True)
            return merged
        return exclude

    def model_dump(
        self,
        *,
        exclude: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Override ``model_dump`` to exclude ``_SENSITIVE_FIELDS`` by default.

        The override keeps the ``exclude`` parameter so explicit
        ``exclude=set()`` opts in to inclusion of sensitive fields.
        All other code paths inherit the default exclusion. The
        parameter type is the full Pydantic ``IncEx`` (set or dict
        forms both supported) so callers can use nested exclusion.
        """
        return super().model_dump(exclude=self._effective_exclude(exclude), **kwargs)

    def model_dump_json(
        self,
        *,
        exclude: Any = None,
        **kwargs: Any,
    ) -> str:
        """Override ``model_dump_json`` to exclude ``_SENSITIVE_FIELDS`` by default.

        Mirrors :meth:`model_dump` for the JSON path so the
        ``/health.bifrost.config`` probe never serializes ``auth_env``.
        """
        return super().model_dump_json(
            exclude=self._effective_exclude(exclude), **kwargs
        )


# ---------------------------------------------------------------------------
# BifrostLLMRouter — standalone URL resolver
# ---------------------------------------------------------------------------


class BifrostLLMRouter:
    """URL resolver for the local Bifrost gateway.

    Not a subclass of :class:`LLMBase` (REQ-BIFROST-015). The router
    only returns URLs; HTTP transport is the caller's responsibility
    (typically ``mcp_common.llm.OpenAICompatibleProvider``).

    The 7-value :class:`LLMProvider` enum maps to the 2-value
    :class:`RouteKind` enum via ``_PROVIDER_ROUTE``. The other 5
    providers (AZURE_OPENAI, GOOGLE_VERTEX, AWS_BEDROCK, LOCAL, ZAI,
    LLAMA_SERVER) are not currently routable through Bifrost and
    raise :class:`KeyError` if passed to :meth:`resolve` (3-agent
    type F1 fix — explicit mapping makes the contract unmissable).
    """

    # 2-value mapping: ANTHROPIC → CLAUDE_ROUTE, OPENAI → QWEN_ROUTE.
    # Provider values without an entry raise KeyError on resolve.
    _PROVIDER_ROUTE: ClassVar[Mapping[LLMProvider, RouteKind]] = {
        LLMProvider.ANTHROPIC: RouteKind.CLAUDE_ROUTE,
        LLMProvider.OPENAI: RouteKind.QWEN_ROUTE,
    }

    # AdapterMetadata shape mirrors oneiric.adapters.llm.anthropic.
    # The factory string has a space after the colon per 3-agent
    # review F7. ``priority=450`` is below AnthropicLLM's 480
    # (Bifrost is a transparent proxy; clients should prefer the real
    # provider and have it routed through Bifrost via the URL it
    # returns from resolve()).
    metadata = AdapterMetadata(
        category="llm",
        provider="bifrost",
        factory="oneiric.adapters.llm.bifrost: BifrostLLMRouter",
        description=(
            "Bifrost gateway URL resolver for OpenAI-compatible and "
            "Anthropic-compatible routing"
        ),
        capabilities=["routing"],
        stack_level=14,
        priority=450,
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=False,
        settings_model=BifrostLLMSettings,
    )

    def __init__(self, settings: BifrostLLMSettings | None = None) -> None:
        self._settings = settings or BifrostLLMSettings()

    def resolve(self, provider: LLMProvider) -> str | None:
        """Return the gateway URL for the given provider, or ``None``.

        Returns ``None`` when:
        - ``settings.enabled`` is ``False`` (REQ-BIFROST-002), OR
        - the required route for the provider is not in
          ``settings.routes``.

        Raises :class:`KeyError` if the provider has no
        ``_PROVIDER_ROUTE`` entry — that's a caller bug, not a
        configuration error (e.g. calling ``resolve(LLMProvider.AZURE_OPENAI)``
        when no Azure gateway route exists).
        """
        if not self._settings.enabled:
            return None
        route = self._PROVIDER_ROUTE[provider]  # KeyError on unmapped provider
        if route not in self._settings.routes:
            return None
        if provider == LLMProvider.ANTHROPIC:
            return str(self._settings.anthropic_base_url)
        return str(self._settings.base_url)


# ---------------------------------------------------------------------------
# Process-cached singleton + test seam
# ---------------------------------------------------------------------------


_ROUTER_SINGLETON: BifrostLLMRouter | None = None


def get_router() -> BifrostLLMRouter:
    """Return the process-cached :class:`BifrostLLMRouter` instance.

    Canonical entry point. Every consumer should call
    ``from oneiric.adapters.llm.bifrost import get_router`` and then
    ``get_router().resolve(LLMProvider.ANTHROPIC)``. Constructing
    custom ``BifrostLLMRouter`` instances is allowed for tests but
    every production path should use the singleton — the cache is
    the structural guarantee against config drift across call sites
    (per the 5-agent review's "centralization guarantee recovered
    via singleton" argument).
    """
    global _ROUTER_SINGLETON
    if _ROUTER_SINGLETON is None:
        _ROUTER_SINGLETON = BifrostLLMRouter()
    return _ROUTER_SINGLETON


def reset_router_for_tests() -> None:
    """Clear the :func:`get_router` singleton cache.

    Test seam. Production code MUST NOT call this. The pytest
    fixture in ``tests/adapters/llm/conftest.py`` invokes it on
    setup so test ordering doesn't pollute the singleton state
    (REQ-BIFROST-018, 3-agent type F6 + security F-11 fix).
    """
    global _ROUTER_SINGLETON
    _ROUTER_SINGLETON = None


__all__ = [
    "BifrostLLMRouter",
    "BifrostLLMSettings",
    "RouteKind",
    "get_router",
    "reset_router_for_tests",
]
