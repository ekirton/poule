"""Error types for the setoid rewriting assistant."""

from __future__ import annotations


class SetoidError(Exception):
    """Structured error for setoid rewriting diagnosis."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)
