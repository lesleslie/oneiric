"""Auth configuration for the oneiric FastMCP server.

Loads the ``auth:`` section from oneiric's settings.yaml + ONEIRIC_AUTH_*
env vars and converts it into mcp-common's ``AuthConfig`` + a map of
``IdentityProvider`` instances.

REQ-006: settings file with env-var override, per oneiric's existing
layered-config convention.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from mcp_common.auth.config import AuthConfig
from mcp_common.auth.identity import IdentityProviderSpec, validate_auth_config
from mcp_common.auth.provider import IdentityProvider


def load_yaml_auth_section(yaml_path: Path) -> dict[str, Any]:
    """Read oneiric settings YAML and return the ``auth:`` section dict.

    REQ-006: YAML is the source of truth when env vars don't override.
    Returns an empty dict when the file is missing (trusted-network
    default — operators haven't opted into auth).
    Raises a clear error when the file exists but is malformed or the
    ``auth:`` section has wrong shape.
    """
    if not yaml_path.exists():
        return {}
    try:
        data = yaml.safe_load(yaml_path.read_text())
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"Failed to parse {yaml_path}: {exc}. "
            "Fix the YAML or unset the env var."
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(
            f"{yaml_path} must contain a YAML mapping at the top level "
            f"(got {type(data).__name__})."
        )
    auth = data.get("auth", {})
    if auth is None:
        return {}
    if not isinstance(auth, dict):
        raise RuntimeError(
            f"{yaml_path}'s 'auth:' section must be a mapping "
            f"(got {type(auth).__name__})."
        )
    return dict(auth)


@dataclass
class OneiricMCPAuthConfig:
    """Resolved auth settings for the oneiric FastMCP server."""

    enabled: bool = False
    default_provider: str | None = None
    trusted_issuers: list[str] = field(default_factory=list)
    # Provider-specific config; each provider maps to a name and a callable
    # that returns an IdentityProvider instance (constructed lazily so
    # secrets aren't loaded until the server starts).
    provider_configs: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_env(cls, raw: dict[str, Any]) -> OneiricMCPAuthConfig:
        """Construct from YAML-merged dict + env vars.

        Precedence: env var > YAML value > default. The ``raw`` dict is
        the YAML-loaded ``auth:`` section (already merged with any
        upstream defaults); env vars are applied LAST so they win.
        """
        enabled_str = os.getenv("ONEIRIC_AUTH_ENABLED")
        if enabled_str is not None:
            enabled = enabled_str.lower() in ("true", "1", "yes")
        else:
            enabled = bool(raw.get("enabled", False))
        default_provider = os.getenv(
            "ONEIRIC_AUTH_DEFAULT_PROVIDER", raw.get("default_provider")
        )
        issuers_str = os.getenv("ONEIRIC_AUTH_TRUSTED_ISSUERS")
        if issuers_str is not None:
            trusted_issuers = [s.strip() for s in issuers_str.split(",") if s.strip()]
        else:
            trusted_issuers = list(raw.get("trusted_issuers", []))
        return cls(
            enabled=enabled,
            default_provider=default_provider,
            trusted_issuers=trusted_issuers,
            provider_configs=dict(raw.get("providers", {})),
        )


def load_auth_config(
    cfg: OneiricMCPAuthConfig,
    *,
    provider_factories: dict[str, Callable[[dict[str, Any]], IdentityProvider]] | None = None,
) -> tuple[AuthConfig, dict[str, IdentityProvider]]:
    """Build mcp-common's AuthConfig + provider map from the resolved config.

    ``provider_factories`` maps provider name to a callable that turns the
    raw provider config dict into an ``IdentityProvider`` instance. When
    the operator configures auth, they wire ``provider_factories`` (in
    the production settings loader) to the actual provider constructors
    (e.g. ``{"mahavishnu-jwt": lambda c: JWTProvider(c["secret"])}``).
    """
    auth_config = AuthConfig(
        service_name="oneiric",
        enabled=cfg.enabled,
        default_provider=cfg.default_provider or "",
        trusted_issuers=frozenset(cfg.trusted_issuers),
        identity_providers=(
            {name: IdentityProviderSpec(type="jwt") for name in provider_factories}
            if cfg.enabled and provider_factories
            else None
        ),
    )
    providers: dict[str, IdentityProvider] = {}
    if cfg.enabled:
        if not provider_factories:
            raise RuntimeError(
                "auth.enabled=True but no provider_factories supplied. "
                "Configure provider_factories in the production settings loader, "
                "or disable auth via auth.enabled=false. "
                "See docs/operations/oneiric-auth.md for setup details."
            )
        for name, factory in provider_factories.items():
            providers[name] = factory(cfg.provider_configs.get(name, {}))
        # Fail-loud at startup if config is invalid (mcp-common's helper).
        validate_auth_config(auth_config)
    return auth_config, providers


__all__ = ["OneiricMCPAuthConfig", "load_auth_config", "load_yaml_auth_section"]
