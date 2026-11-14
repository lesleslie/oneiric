"""YAML-driven LLM provider configuration."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from ._security import validate_base_url

logger = logging.getLogger(__name__)

#: The thinking-depth vocabulary a provider may be configured with.
#:
#: ``adaptive`` is the sentinel meaning "send no effort field; the model
#: chooses its own depth". The remaining members are the effort levels
#: MiniMax's OpenAI-compatible endpoint accepts.
#:
#: There is deliberately no "off" member. Thinking is never disabled:
#: ``MiniMax-M3.1-Flash`` answers 400 for a disable request, and
#: ``MiniMax-M3`` answering without thinking is a decision no operator
#: configuration should be able to make.
REASONING_EFFORT_LEVELS = frozenset(
    {"adaptive", "low", "medium", "high", "xhigh", "max"}
)


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    name: str = ""
    enabled: bool = True
    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    api_key_env: str | None = None
    require_auth: bool = True
    models: dict[str, str] = {}
    priority: int = 1
    timeout: int = 30
    timeout_seconds: int = 30
    max_retries: int = 2
    task_routing: dict[str, str] = {}
    fallback: dict[str, str] = {}
    #: Extra HTTP headers sent with every request to this provider.
    #:
    #: Used by the Bifrost gateway path, which authenticates with a
    #: gateway virtual key (``x-bf-vk``) and selects a cache path
    #: (``x-bf-cache-type`` / ``x-bf-cache-key`` / ``x-bf-cache-no-store``)
    #: in headers rather than in the URL or the bearer token.
    #:
    #: These are merged with the SDK's own headers -- they do not replace
    #: them, so ``Authorization`` is still set from ``api_key``.
    #:
    #: The field is excluded from the model's ``repr``: the Bifrost path
    #: puts the gateway virtual key in ``x-bf-vk``, and a printed config
    #: is a printed credential.
    default_headers: dict[str, str] = Field(default_factory=dict, repr=False)
    #: Per-model thinking-depth policy, keyed by the *resolved* model id.
    #:
    #: Values are the effort levels MiniMax's OpenAI-compatible endpoint
    #: accepts -- ``low``, ``medium``, ``high``, ``xhigh``, ``max`` -- plus
    #: the sentinel ``adaptive``, which means "send no effort field; the
    #: model chooses its own depth".
    #:
    #: The sentinel is a first-class member rather than an absent key so
    #: that every model the provider can serve is accounted for. A model
    #: missing from the map is a configuration miss and is logged as such:
    #: on ``MiniMax-M3.1-Flash`` a miss silently means the provider
    #: default, which is ``max``.
    #:
    #: There is deliberately no "off" member. Thinking is never disabled:
    #: ``MiniMax-M3.1-Flash`` answers 400 for a disable request, and
    #: ``MiniMax-M3`` answering without thinking is a decision no operator
    #: configuration should be able to make.
    reasoning_effort: dict[str, str] = {}

    # ``validate_assignment`` closes the gap between "the base_url was
    # checked" and "the base_url is still the one that was checked": a
    # validated model that can be mutated afterwards is a model whose
    # validation can be undone.
    model_config = {"extra": "forbid", "validate_assignment": True}

    @field_validator("reasoning_effort")
    @classmethod
    def _validate_reasoning_effort(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject effort values outside the permitted vocabulary.

        The failure message names the offending value and the allowed set,
        and calls out ``none``/``disabled`` by name: on
        ``MiniMax-M3.1-Flash`` both are 400s rather than inert values.
        """
        invalid = {
            model: effort
            for model, effort in value.items()
            if effort not in REASONING_EFFORT_LEVELS
        }
        if invalid:
            offending = ", ".join(
                f"{model}={effort!r}" for model, effort in sorted(invalid.items())
            )
            allowed = ", ".join(sorted(REASONING_EFFORT_LEVELS))
            msg = (
                f"Invalid reasoning_effort value(s): {offending}. "
                f"Allowed values are: {allowed}. "
                "'none' and 'disabled' are not allowed — thinking is never "
                "disabled: MiniMax-M3.1-Flash answers 400 for a disable request."
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def resolve_env_vars(self) -> ProviderConfig:
        """Resolve ${ENV_VAR} patterns in api_key and base_url."""
        if self.base_url.startswith("${") and self.base_url.endswith("}"):
            env_var = self.base_url[2:-1]
            resolved = os.getenv(env_var, "")
            if resolved:
                self.base_url = resolved

        raw_key = self.api_key.get_secret_value()
        if raw_key.startswith("${") and raw_key.endswith("}"):
            env_var = raw_key[2:-1]
            resolved = os.getenv(env_var, "")
            if resolved:
                self.api_key = SecretStr(resolved)

        # Sync timeout_seconds from legacy timeout if not explicitly set
        if self.timeout_seconds == 30 and self.timeout != 30:
            self.timeout_seconds = self.timeout

        return self

    @model_validator(mode="after")
    def reject_dangerous_base_url(self) -> ProviderConfig:
        """Refuse a ``base_url`` that would aim the provider credential at
        a metadata endpoint or a private network.

        Runs after :meth:`resolve_env_vars` so the ``${ENV_VAR}`` form is
        judged once it has been substituted; an unresolved placeholder is
        skipped, because the environment is not read at model-construction
        time for every provider.
        """
        url = self.base_url
        if not url or (url.startswith("${") and url.endswith("}")):
            return self
        validate_base_url(url)
        return self

    def get_model_for_task(self, task_type: str) -> str | None:
        """Get the model ID for a given task type."""
        return self.task_routing.get(task_type)


class LLMSettings(BaseModel):
    """Loaded from settings/models.yaml or equivalent."""

    providers: dict[str, dict[str, Any]] = {}
    default_provider: str = "minimax"
    fallback_chain: list[str] = ["minimax", "llama_server"]

    model_config = {"extra": "forbid"}

    @classmethod
    def from_yaml(cls, path: str | Path) -> LLMSettings:
        """Load settings from a YAML file.

        Accepts both the legacy flat schema (top-level provider keys) and
        the new schema (providers: + fallback_chain:). Both shapes coexist
        during the transition period.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            LLMSettings instance with parsed provider configs.
        """
        path = Path(path)
        if not path.exists():
            logger.warning("LLM config file not found: %s", path)
            return cls()

        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        reserved = {
            "default_provider",
            "fallback_chain",
            "free_tier_provider",
            "bifrost",
            "providers",
        }
        providers: dict[str, Any] = data.get("providers", {})
        if not providers:
            # Legacy flat schema: extract provider configs from top-level keys
            for key, val in data.items():
                if key in reserved or key.startswith("#") or not isinstance(val, dict):
                    continue
                val_copy = dict(val)
                val_copy["name"] = key
                providers[key] = val_copy
            if providers:
                logger.debug(
                    "Loaded LLM settings using legacy flat schema — "
                    "migrate to 'providers:' top-level key."
                )

        return cls(
            providers=providers,
            default_provider=data.get("default_provider", "minimax"),
            fallback_chain=data.get("fallback_chain", ["minimax", "llama_server"]),
        )

    def get_provider(self, name: str) -> ProviderConfig | None:
        """Get a resolved provider configuration by name.

        Args:
            name: Provider name (e.g., "minimax", "llama_server").

        Returns:
            ProviderConfig if found and enabled, None otherwise.
        """
        raw = self.providers.get(name)
        if not raw:
            return None
        config = ProviderConfig(**raw)
        if not config.enabled:
            return None
        return config

    def get_enabled_providers(self) -> list[ProviderConfig]:
        """Return providers in fallback_chain order, excluding disabled or key-missing ones."""
        result = []
        for name in self.fallback_chain:
            raw = self.providers.get(name)
            if raw is None:
                logger.warning(
                    "Provider %s in fallback_chain not found in config", name
                )
                continue
            cfg = ProviderConfig(**raw)
            if not cfg.enabled:
                continue
            # Fail-closed: skip cloud providers that require auth but have no token configured
            if cfg.require_auth:
                key = cfg.api_key.get_secret_value()
                env_name = cfg.api_key_env or ""
                if not key or not key.strip() or key.startswith("${"):
                    logger.warning(
                        "Provider %s skipped: env var %s is not set.",
                        name,
                        env_name or "unknown",
                    )
                    continue
            result.append(cfg)
        return result
