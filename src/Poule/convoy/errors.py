"""Error types for the convoy pattern assistant."""

from __future__ import annotations


class ConvoyError(Exception):
    """Structured error for convoy pattern diagnosis."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)
