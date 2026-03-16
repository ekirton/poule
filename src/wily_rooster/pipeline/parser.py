"""CoqParser protocol and ParseError."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class ParseError(Exception):
    """Error raised when parsing a Coq expression fails."""
    pass


@runtime_checkable
class CoqParser(Protocol):
    """Protocol for parsing Coq expressions into ConstrNode."""

    def parse(self, expression: str) -> Any:
        """Parse a Coq expression string into a ConstrNode.

        Raises ParseError on failure.
        """
        ...
