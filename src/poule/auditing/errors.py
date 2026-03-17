"""Error types for the assumption auditing engine."""

from __future__ import annotations


class AuditError(Exception):
    """Structured error raised by the auditing engine."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)
