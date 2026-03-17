"""Error types for Hammer Automation.

Spec: specification/hammer-automation.md section 7.
"""

from __future__ import annotations


class ParseError(Exception):
    """Raised when tactic builder input is invalid (bad hint name, bad option)."""

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)
