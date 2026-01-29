"""Error types for OTel observability adapter."""

from __future__ import annotations


class QueryError(Exception):
    """Base class for all query-related errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        """Initialize query error.

        Args:
            message: Error message
            details: Additional error context
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """Convert error to dictionary for API responses.

        Returns:
            Dictionary with error details
        """
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class InvalidEmbeddingError(QueryError):
    """Embedding dimension mismatch."""

    pass


class TraceNotFoundError(QueryError):
    """Trace ID not found."""

    pass


class InvalidSQLError(QueryError):
    """SQL validation failed."""

    pass
