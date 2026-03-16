"""Normalization error types."""

from __future__ import annotations


class NormalizationError(Exception):
    """Error during expression normalization.

    Carries the declaration name being normalized and a human-readable message.
    """

    def __init__(self, *, declaration_name: str, message: str) -> None:
        self.declaration_name = declaration_name
        self.message = message
        super().__init__(f"{declaration_name}: {message}")
