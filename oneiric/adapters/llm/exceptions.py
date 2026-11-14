"""LLM-specific exceptions."""


class LLMError(Exception):
    """Base exception for LLM operations."""


class ProviderUnavailableError(LLMError):
    """Provider is unavailable (circuit breaker open or health check failed)."""


class AllProvidersExhaustedError(LLMError):
    """All providers in the fallback chain failed."""


class UnsupportedModalityError(LLMError):
    """Raised when no tier in the chain supports the requested TaskType modality."""
