"""Data types for the vernacular introspection query package."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Command(enum.StrEnum):
    """Valid Coq vernacular introspection commands."""

    Print = "Print"
    Check = "Check"
    About = "About"
    Locate = "Locate"
    Search = "Search"
    Compute = "Compute"
    Eval = "Eval"


@dataclass
class QueryResult:
    """Structured result of a vernacular introspection query.

    Fields:
        command:   One of the 7 valid commands.
        argument:  The argument as provided by the caller.
        output:    Parsed Coq output after normalization.
        warnings:  Coq warnings extracted during output parsing (may be empty).
    """

    command: str
    argument: str
    output: str
    warnings: list[str] = field(default_factory=list)
