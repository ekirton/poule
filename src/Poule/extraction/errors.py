"""Extraction pipeline error types."""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for extraction pipeline errors.

    Carries a ``message: str`` with context about the failure.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class CoqNotInstalledError(ExtractionError):
    """Raised when coq-lsp is not found on the system.

    Includes installation instructions in the error message.
    """

    def __init__(self, message: str | None = None) -> None:
        if message is None:
            message = (
                "coq-lsp not found. "
                "Install it via opam: opam install coq-lsp"
            )
        super().__init__(message)


class BackendCrashError(ExtractionError):
    """Raised when the backend subprocess exits unexpectedly."""

    def __init__(self, message: str | None = None) -> None:
        if message is None:
            message = "Backend process exited unexpectedly"
        super().__init__(message)
