from __future__ import annotations


class QueryError(Exception):
    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class InvalidEmbeddingError(QueryError):
    pass


class TraceNotFoundError(QueryError):
    pass


class InvalidSQLError(QueryError):
    pass
