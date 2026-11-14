"""OpenAI-compatible LLM provider for MiniMax and llama-server."""

from __future__ import annotations

import inspect
import logging
from typing import Any, ClassVar

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.resolution import CandidateSource

from ._security import sanitize_error as _sanitize_error
from .config import ProviderConfig
from .exceptions import LLMError

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """Single provider using the OpenAI-compatible API.

    The `openai` package is an optional dependency. It is lazy-imported
    and a clear ImportError is raised if not installed.
    """

    metadata: ClassVar[AdapterMetadata] = AdapterMetadata(
        category="llm",
        provider="openai-compatible",
        factory="oneiric.adapters.llm.provider: OpenAICompatibleProvider",
        description=(
            "OpenAI-compatible chat-completions transport used by the "
            "fallback chain for MiniMax and llama-server providers"
        ),
        capabilities=["chat_completion"],
        stack_level=10,
        priority=100,
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=False,
        settings_model=ProviderConfig,
    )

    def __init__(self, config: ProviderConfig | None = None) -> None:
        """Bind a provider configuration.

        ``config`` is optional so the class satisfies the zero-argument
        factory contract the adapter registry uses
        (``LifecycleManager._instantiate_candidate`` calls ``factory()``).
        Without a configuration there is no client until ``init()`` is
        called; with one, the client is created eagerly so a missing
        ``openai`` install fails at construction rather than at first use.
        """
        self.name = config.name if config is not None else ""
        self.timeout_seconds = config.timeout_seconds if config is not None else 30
        self._config = config
        self._client: Any | None = None

        if config is not None:
            self._client = self._build_client(config)
            logger.info(
                "Initialized provider %s: base_url=%s", config.name, config.base_url
            )

    def _build_client(self, config: ProviderConfig) -> Any:
        """Create the OpenAI SDK client for a provider configuration."""
        try:
            # ``openai`` is an optional dependency from the ``llm`` PEP 735 group;
            # the runtime ``ImportError`` below gives a clear install hint.
            # The ``ty: import-not-found`` suppression is needed in clean venvs
            # where the optional dep is not installed; locally ty resolves it
            # via venv bleed and reports the directive as unused (warning only,
            # does not fail the gate).
            import openai  # type: ignore[import-not-found]  # ty: ignore[import-not-found, unused-ignore-comment]
        except ImportError as e:
            msg = (
                "openai package required for OpenAICompatibleProvider. "
                "Install it in the consuming project -- oneiric exposes it "
                "as the 'llm' dependency-group (uv sync --group llm)."
            )
            raise ImportError(msg) from e

        # Caller-supplied headers are merged with the SDK's own, never
        # substituted for them: ``Authorization`` still comes from
        # ``api_key``. The Bifrost gateway path uses this to carry the
        # gateway virtual key (``x-bf-vk``) and the cache headers.
        extra_headers = config.default_headers.copy()

        if config.require_auth:
            return openai.AsyncOpenAI(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                max_retries=0,  # retries handled by FallbackChain
                timeout=config.timeout_seconds,
                default_headers=extra_headers,
            )
        # Local no-auth provider (llama-server) —
        # send empty Authorization header so the SDK doesn't inject "Bearer no-auth"
        return openai.AsyncOpenAI(
            api_key="no-auth",
            base_url=config.base_url,
            default_headers={"Authorization": ""} | extra_headers,
            max_retries=0,
            timeout=config.timeout_seconds,
        )

    def _ensure_client(self) -> Any:
        """Return the SDK client, building it on demand after cleanup."""
        if self._client is not None:
            return self._client
        if self._config is None:
            raise LLMError(
                f"Provider {self.name or '<unconfigured>'} has no configuration; "
                "cannot build a client"
            )
        self._client = self._build_client(self._config)
        return self._client

    def _resolve_model(self, task: dict[str, Any]) -> str:
        """Pick model: task_routing[task_type] if configured, else task['model']."""
        task_type = task.get("task_type")
        config = self._config
        if task_type and config is not None and config.task_routing:
            routed = config.task_routing.get(task_type)
            if routed:
                return routed
        return task.get("model") or ""

    def _resolve_reasoning_effort(self, model: str) -> str | None:
        """Resolve the thinking-depth policy for a resolved model id.

        Returns the configured effort level, ``"adaptive"`` (send no field
        -- the model picks its own depth), or ``None`` when the model has
        no entry at all, in which case the provider default applies.

        A missing entry is only a *miss* when a policy map is configured;
        an empty map means "no policy for this provider", which is not a
        misconfiguration and must not be logged as one.
        """
        config = self._config
        if config is None:
            return None
        effort = config.reasoning_effort.get(model)
        if effort is None:
            if config.reasoning_effort:
                logger.warning(
                    "Provider %s: model %s has no reasoning_effort entry; "
                    "the provider default applies",
                    self.name,
                    model,
                )
            return None
        return effort

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a chat completion request.

        Args:
            task: Dict with 'model', 'messages', and optional
                  'task_type', 'max_tokens', 'temperature'.
                  When 'task_type' is present and this provider has a
                  matching task_routing entry, that model is used instead
                  of task['model'], enabling per-provider model selection
                  from a single FallbackChain call.

        Returns:
            Dict with 'content', 'provider', 'model', 'usage', and -- when
            a thinking-depth policy applies to the resolved model --
            'reasoning_effort'.

        Raises:
            LLMError: If the API call fails.
        """
        model = self._resolve_model(task)
        try:
            create_kwargs: dict[str, Any] = {
                "model": model,
                "messages": task["messages"],
                "max_tokens": task.get("max_tokens", 4096),
                "temperature": task.get("temperature", 0.7),
            }
            # Per-model thinking depth. ``reasoning_effort`` is the native
            # OpenAI Chat Completions field name, so the direct path needs
            # no translation. ``adaptive`` sends no field at all.
            effort = self._resolve_reasoning_effort(model)
            if effort is not None and effort != "adaptive":
                create_kwargs["reasoning_effort"] = effort
            # Per-call headers, for callers that need to vary them per
            # request (e.g. a per-tenant cache bucket). Omitted entirely
            # when absent so the SDK call shape is unchanged.
            call_headers = task.get("extra_headers")
            if call_headers:
                create_kwargs["extra_headers"] = dict(call_headers)
            response = await self._ensure_client().chat.completions.create(
                **create_kwargs
            )
            result: dict[str, Any] = {
                "content": response.choices[0].message.content or "",
                "provider": self.name,
                "model": model,
                "usage": response.usage.model_dump() if response.usage else {},
            }
            if effort is not None:
                result["reasoning_effort"] = effort
            return result
        except Exception as e:
            logger.warning("Provider %s failed: %s", self.name, _sanitize_error(str(e)))
            raise LLMError(
                f"Provider {self.name} failed: {_sanitize_error(str(e))}"
            ) from e

    async def health_check(self) -> bool:
        """Lightweight health check by listing models.

        Returns:
            True if provider is reachable, False otherwise.
        """
        try:
            await self._ensure_client().models.list()
            return True
        except (
            OSError,
            TimeoutError,
            ValueError,
            TypeError,
            AttributeError,
            KeyError,
            IndexError,
            RuntimeError,
        ) as e:
            logger.warning(
                "Health check failed for %s: %s", self.name, _sanitize_error(str(e))
            )
            return False

    async def init(self) -> None:
        """Warm up the provider client.

        Idempotent: a client that already exists is left alone, and a
        client released by :meth:`cleanup` is rebuilt from the
        configuration.
        """
        if self._client is not None:
            return
        if self._config is None:
            logger.warning(
                "Provider %s has no configuration; init() has nothing to warm up",
                self.name,
            )
            return
        self._client = self._build_client(self._config)
        logger.info("Provider %s initialized", self.name)

    async def health(self) -> bool:
        """Return whether the provider is reachable.

        Never raises -- the monitoring layer relies on a ``bool``. The
        public :meth:`health_check` keeps its own (narrower) error
        handling; this wrapper is the protocol-facing surface.
        """
        try:
            return await self.health_check()
        except Exception as e:
            logger.warning(
                "Health check raised for %s: %s", self.name, _sanitize_error(str(e))
            )
            return False

    async def cleanup(self) -> None:
        """Release the provider client.

        Idempotent, and never raises -- a failed close must not mask the
        shutdown it belongs to.
        """
        client = self._client
        self._client = None
        if client is None:
            return
        close = getattr(client, "close", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.warning(
                "Cleanup failed for %s: %s", self.name, _sanitize_error(str(e))
            )
