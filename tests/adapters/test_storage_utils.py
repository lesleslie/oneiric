from __future__ import annotations

from oneiric.adapters.storage.utils import is_not_found_error


class CodeError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("code error")


class ResponseError(Exception):
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        super().__init__("response error")


def test_is_not_found_error_matches_code() -> None:
    exc = CodeError("NoSuchKey")

    assert is_not_found_error(exc, codes=("NoSuchKey",))


def test_is_not_found_error_matches_response_code() -> None:
    exc = ResponseError({"Error": {"Code": "NotFound"}})

    assert is_not_found_error(exc, codes=("NotFound",))


def test_is_not_found_error_matches_message_token() -> None:
    exc = RuntimeError("missing resource at path")

    assert is_not_found_error(exc, messages=("missing",))


def test_is_not_found_error_returns_false_for_unmatched() -> None:
    exc = RuntimeError("boom")

    assert is_not_found_error(exc, codes=("Nope",), messages=("missing",)) is False
