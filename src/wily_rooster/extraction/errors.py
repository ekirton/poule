"""Extraction pipeline error types."""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for extraction pipeline errors.

    Carries a ``message: str`` with context about the failure.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
