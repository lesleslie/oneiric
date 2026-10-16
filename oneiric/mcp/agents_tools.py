"""Phase 3 server-published agents tools for Oneiric.

Exposes the ``mcp__oneiric__oneiric_list_agents`` and
``mcp__oneiric__oneiric_get_agent`` MCP tools that advertise the
server-defined agents to the Phase 3 installer and the Claude
Code picker. Oneiric is the only Bodai server with a **dynamic
catalog** (path B) — the specialist agents are generated at
server boot from the adapter registry rather than hand-authored
in a static list.

This module is a thin server-specific wrapper around
:func:`mcp_common.agents_tools.build_register_agents_tools`. The
factory owns the mechanism — the B-4 allowlist, B-6 body
normalization + content-hash, the wire shape, the success/error
envelope, and the tool registration plumbing. Oneiric owns the
policy: the catalog is generated at module load by walking
``oneiric/adapters/<domain>/`` for providers, the body_loader
synthesizes a pointed body per domain, the tool name prefix is
``"oneiric_"``, and the signing function uses oneiric's local
canonicalization + signer.

Security gates (per plan §11):

- **B-1** — every ``get_agent`` response carries an ed25519 signature
  over the canonicalized metadata. The Phase 3 installer verifies
  this before any write to ``~/.claude/agents/oneiric-<name>.md``.
- **B-4** — the path-traversal allowlist
  ``^[a-z0-9][a-z0-9._-]{0,62}$`` lives in
  ``mcp_common.canonical_schemas._validators.NAME_OR_SERVER_RE``;
  the factory enforces it at the API boundary. The per-server
  regex copy that used to live here is gone.
- **B-6** — ``get_agent`` returns ``body == system_prompt``. The
  factory computes ``content_hash`` from the stripped body and
  the schema's body-integrity model_validator asserts the hash
  matches the system_prompt bytes.
- **B-7** — each successful tool call invokes ``on_call``,
  which bumps the cycles counter on the signer feed state.

Catalog composition
-------------------

1. **Cross-domain specialist** (``oneiric-specialist``) — one
   static entry covering the foundation surface (adapters,
   scheduler, settings). The body is synthesized from the
   full domain list, so the LLM sees the entire substrate at
   a glance.

2. **Per-domain specialists** (one per domain with ≥2
   providers, e.g. ``vector-specialist``, ``llm-specialist``)
   — dynamic entries generated at module load. Domains with
   a single provider are skipped (a "specialist" with one
   example is just noise). The body for each domain is
   synthesized to mention the registered providers, give a
   pointed example, and tell the LLM to refresh via
   ``oneiric_list_adapters(domain=X)`` for current state.

Staleness: bodies are snapshotted at server boot. A new
adapter added at runtime won't appear in the body until the
next restart. The body explicitly tells the LLM to call
``oneiric_list_adapters`` for current state — the static body
is a hint, not the truth.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_common.agents_tools import build_register_agents_tools
from mcp_common.canonical_schemas.agent import AgentCanonicalSchema

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


# Server key: "oneiric" (matches the Wire convention). The MCP tool
# name prefix is "oneiric_" to match the existing wire names.
_SERVER_KEY = "oneiric"
_TOOL_NAME_PREFIX = f"{_SERVER_KEY}_"

# Directory layout: this module is at oneiric/mcp/agents_tools.py,
# so the adapters tree is oneiric/adapters/<domain>/<provider>.py.
# The filesystem walk is synchronous and runs once at module load.
_ADAPTERS_ROOT = Path(__file__).parent.parent / "adapters"


# --- Domain enumeration (path B core) -------------------------------


def _enumerate_domains() -> dict[str, list[str]]:
    """Walk ``oneiric/adapters/`` and return ``{domain: [providers]}``.

    Each subdirectory is a domain. Each ``.py`` file in that
    directory (excluding ``__init__.py``) is a provider; the file
    stem is the provider name. The result is sorted for a stable
    catalog across boots (the factory preserves insertion order,
    so the install sees the same specialists in the same order).

    The walk is purely filesystem — no async, no registry query.
    This means the catalog is available at import time without
    requiring the adapter registry to be initialized.
    """
    if not _ADAPTERS_ROOT.is_dir():
        return {}
    domains: dict[str, list[str]] = {}
    for entry in sorted(_ADAPTERS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        providers: list[str] = []
        for f in sorted(entry.iterdir()):
            if f.suffix == ".py" and f.stem != "__init__":
                providers.append(f.stem)
        if providers:
            domains[entry.name] = providers
    return domains


# Cache the enumeration at module load so the body_loader doesn't
# re-walk the filesystem on every get_agent call. B-7 is unaffected
# (the factory's on_call is the cycle-bump, not the body source).
_DOMAIN_PROVIDERS: dict[str, list[str]] = _enumerate_domains()

# Domains with 2+ providers get a specialist. Single-adapter domains
# are skipped — a "specialist" with one example is just noise that
# dilutes the picker.
_DOMAINS_WITH_SPECIALIST: dict[str, list[str]] = {
    domain: providers
    for domain, providers in _DOMAIN_PROVIDERS.items()
    if len(providers) >= 2
}


# --- Body synthesis (path B core) ----------------------------------


def _synthesize_oneiric_body() -> str:
    """Body for the cross-domain ``oneiric-specialist`` agent.

    Mentions every domain so the LLM can route the question to
    the right per-domain specialist. Includes the four core
    oneiric MCP tool names so the LLM has a concrete starting
    point.
    """
    domains_section = "\n".join(
        f"- ``{d}`` (with {len(p)} providers)"
        for d, p in sorted(_DOMAIN_PROVIDERS.items())
    )
    return (
        "# oneiric-specialist\n\n"
        "You handle foundation-level questions about the Oneiric substrate: "
        "adapters, runtime state, settings, and the scheduler. When the user "
        "asks about a specific domain, prefer the corresponding per-domain "
        "specialist (``vector-specialist``, ``llm-specialist``, etc.) — this "
        "agent is the cross-domain entry point.\n\n"
        "## Substrate domains\n\n"
        f"{domains_section}\n\n"
        "## Core recipes\n\n"
        "- ``mcp__oneiric__oneiric_list_adapters(domain='<X>')`` to enumerate\n"
        "- ``mcp__oneiric__oneiric_get_adapter(domain, key, provider)`` to inspect one\n"
        "- ``mcp__oneiric__oneiric_validate_adapter(...)`` before deployment\n"
        "- ``mcp__oneiric__oneiric_get_adapter_health(...)`` for runtime state\n"
        "- ``mcp__oneiric__read_context`` / ``write_context`` for substrate state\n"
        "- ``mcp__oneiric__schedule_task`` to dispatch a workflow\n\n"
        "Per-domain specialists refresh via ``oneiric_list_adapters`` for "
        "current state; the bodies are snapshotted at server boot.\n"
    )


def _synthesize_domain_body(domain: str, providers: list[str]) -> str:
    """Body for a per-domain specialist (path B).

    Includes the registered provider list (snapshot at server
    boot), a pointed example, and a note that the LLM should
    refresh via ``oneiric_list_adapters`` for current state.
    """
    providers_section = "\n".join(f"- ``{p}``" for p in providers)
    return (
        f"# {domain}-specialist\n\n"
        f"You handle adapter questions for the ``{domain}`` domain in the "
        f"Oneiric substrate. Prefer this agent over the cross-domain "
        f"``oneiric-specialist`` when the user names a {domain} technology "
        f"or asks for help with a {domain}-domain provider.\n\n"
        "## Currently registered providers\n\n"
        f"This list was snapshotted at server boot; refresh via "
        f"``mcp__oneiric__oneiric_list_adapters(domain='{domain}')`` for "
        f"the current set (new providers may have been added at runtime).\n\n"
        f"{providers_section}\n\n"
        "## Recipes\n\n"
        f"- ``mcp__oneiric__oneiric_list_adapters(domain='{domain}')`` to enumerate\n"
        f"- ``mcp__oneiric__oneiric_get_adapter(domain='{domain}', key='...', provider='...')`` to inspect\n"
        f"- ``mcp__oneiric__oneiric_validate_adapter(...)`` before deployment\n"
        f"- ``mcp__oneiric__oneiric_get_adapter_health(...)`` to check runtime state\n\n"
        "When the registry has changed since boot, call ``list_adapters`` "
        "first so the LLM has the current state. The body is a hint, not "
        "the truth.\n"
    )


# --- Catalog builder ------------------------------------------------


def _build_catalog() -> list[dict[str, Any]]:
    """Build the catalog at module load.

    One static entry (cross-domain ``oneiric-specialist``) plus
    one dynamic entry per domain with ≥2 providers. The dynamic
    entries' bodies are NOT inlined — they're computed by the
    body_loader at request time so the catalog dicts stay small
    and importable without triggering body synthesis.
    """
    catalog: list[dict[str, Any]] = [
        {
            "name": "oneiric-specialist",
            "version": "1.0.0",
            "title": "Oneiric Foundation Specialist",
            "description": (
                "Use proactively for oneiric substrate questions spanning "
                "multiple domains — adapter discovery, runtime state, "
                "settings, workflow scheduling. Routes through the 8 "
                "oneiric adapter tools and 6 substrate tools. For "
                "domain-specific questions, prefer the per-domain "
                "specialists (e.g. ``vector-specialist``, ``llm-specialist``)."
            ),
            "model": "sonnet",
            "tools": [
                "mcp__oneiric__oneiric_list_adapters",
                "mcp__oneiric__oneiric_get_adapter",
                "mcp__oneiric__oneiric_validate_adapter",
                "mcp__oneiric__oneiric_get_adapter_health",
                "mcp__oneiric__oneiric_list_adapter_versions",
                "mcp__oneiric__oneiric_get_contract_info",
                "Read",
            ],
            "category": "foundation",
            "owner": "oneiric",
            "status": "active",
            "last_reviewed": "2026-10-16",
            "scope": "user-global",
        }
    ]
    for domain in sorted(_DOMAINS_WITH_SPECIALIST):
        catalog.append(
            {
                "name": f"{domain}-specialist",
                "version": "1.0.0",
                "title": f"{domain.replace('_', ' ').title()} Specialist",
                "description": (
                    f"Use proactively for {domain} adapter questions in the "
                    f"Oneiric substrate. Covers {len(_DOMAINS_WITH_SPECIALIST[domain])} "
                    f"registered providers. Routes through "
                    f"``mcp__oneiric__oneiric_list_adapters(domain='{domain}')`` "
                    f"and the related adapter tools. Sharper matcher than the "
                    f"cross-domain ``oneiric-specialist`` for {domain}-specific "
                    f"questions."
                ),
                "model": "sonnet",
                "tools": [
                    "mcp__oneiric__oneiric_list_adapters",
                    "mcp__oneiric__oneiric_get_adapter",
                    "mcp__oneiric__oneiric_validate_adapter",
                    "mcp__oneiric__oneiric_get_adapter_health",
                    "mcp__oneiric__oneiric_list_adapter_versions",
                    "Read",
                ],
                "category": domain,
                "owner": "oneiric",
                "status": "active",
                "last_reviewed": "2026-10-16",
                "scope": "user-global",
            }
        )
    return catalog


# Catalog built once at module load. The factory's catalog
# validation runs at this point (server_key check, name
# allowlist, duplicate detection) so config errors fail fast.
CATALOG: list[dict[str, Any]] = _build_catalog()


# --- Body source (server-specific) ----------------------------------


def _body_loader(name: str) -> str:
    """Factory's body source: synthesize a body per agent.

    For ``oneiric-specialist``: the cross-domain body listing
    every domain.

    For ``<domain>-specialist``: the per-domain body mentioning
    the registered providers.

    Unknown names raise KeyError — the factory catches it and
    returns a "not found" error envelope, not an exception.
    """
    if name == "oneiric-specialist":
        return _synthesize_oneiric_body()
    if name.endswith("-specialist"):
        domain = name[: -len("-specialist")]
        if domain in _DOMAINS_WITH_SPECIALIST:
            return _synthesize_domain_body(
                domain, _DOMAINS_WITH_SPECIALIST[domain]
            )
    raise KeyError(f"agent {name!r} not in oneiric's synthesized catalog")


# --- Signing policy (server-specific) -------------------------------


def _sign(metadata: AgentCanonicalSchema) -> AgentCanonicalSchema:
    """Apply an ed25519 signature using oneiric's signing surface.

    The factory hands the unsigned metadata to this callable and
    receives the signed copy. Acquires the signer via
    :func:`oneiric.mcp.signer_feed.get_signer_feed_state`
    (lifespan-owned singleton initialized in
    ``build_mcp_server``), canonicalizes via oneiric's local
    :func:`canonical_payload_for_signing` (which strips the
    ``signature`` + ``server_pubkey_id`` fields before signing so
    the signature doesn't cover itself), and attaches the result.

    Raises if the signer feed state isn't initialized (server still
    starting up, or pre-Phase-1.5 lite mode). The factory converts
    the exception into the standard error envelope.
    """
    from oneiric.mcp.signer_feed import get_signer_feed_state
    from oneiric.skills_signer import canonical_payload_for_signing

    state = get_signer_feed_state()
    if state is None:
        raise RuntimeError(
            "signer not initialized (server may still be starting up)"
        )

    canonical = canonical_payload_for_signing(metadata.to_dict())
    signed = state.signer.sign(canonical)
    return metadata.model_copy(
        update={
            "signature": signed.signature_b64,
            "server_pubkey_id": signed.key_id,
        }
    )


# --- B-7 cycle bump (server-specific) ------------------------------


def _on_call() -> None:
    """B-7: bump cycles_total on every tool call.

    The factory invokes this at the start of every list_agents and
    get_agent call so the four mandatory feed signals stay
    accurate. No-op if the signer feed state isn't initialized
    yet (matches the pre-refactor behavior).
    """
    from oneiric.mcp.signer_feed import get_signer_feed_state

    state = get_signer_feed_state()
    if state is not None:
        state.record_cycle()


# --- Tool registration ----------------------------------------------


def register_agents_tools(app: FastMCP) -> None:
    """Register ``oneiric_list_agents`` and ``oneiric_get_agent`` MCP tools.

    Idempotent at module level. Delegates to
    :func:`mcp_common.agents_tools.build_register_agents_tools`
    with oneiric's dynamic catalog (built at module load by
    :func:`_build_catalog`), the body synthesizer
    (:func:`_body_loader`), the signing policy (:func:`_sign`),
    and the cycle-bump hook (:func:`_on_call`).
    """
    build_register_agents_tools(
        server_key=_SERVER_KEY,
        catalog=CATALOG,
        body_loader=_body_loader,
        sign=_sign,
        on_call=_on_call,
        tool_name_prefix=_TOOL_NAME_PREFIX,
    )(app)


__all__ = ["register_agents_tools", "AgentCanonicalSchema"]
