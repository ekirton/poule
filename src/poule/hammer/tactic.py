"""Tactic Builder for Hammer Automation.

Assembles syntactically valid CoqHammer tactic strings from structured parameters.

Spec: specification/hammer-automation.md section 4.5.
"""

from __future__ import annotations

import re

from poule.hammer.errors import ParseError

# Valid Coq identifier pattern per spec: [a-zA-Z_][a-zA-Z0-9_'.]*
_COQ_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_'.]*$")

_VALID_STRATEGIES = {"hammer", "sauto", "qauto"}


def _validate_identifier(name: str, label: str = "hint") -> None:
    """Validate that a name is a syntactically valid Coq identifier."""
    if not name or not _COQ_IDENT_RE.match(name):
        raise ParseError(f"Invalid {label}: {name!r} is not a valid Coq identifier")


def build_tactic(strategy: str, hints: list[str], options: dict) -> str:
    """Build a syntactically valid Coq tactic string.

    REQUIRES: strategy is one of hammer, sauto, qauto.
    ENSURES: Returns a syntactically valid tactic string.
    RAISES: ParseError on invalid hint, invalid depth, or invalid unfold entry.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"Invalid strategy: {strategy!r}; must be one of {_VALID_STRATEGIES}")

    # Validate hints
    for hint in hints:
        _validate_identifier(hint, "hint")

    # Validate options
    depth = options.get("depth")
    if depth is not None:
        if not isinstance(depth, int) or depth <= 0:
            raise ParseError(f"Invalid depth: {depth!r}; must be a positive integer")

    unfold = options.get("unfold", [])
    for entry in unfold:
        _validate_identifier(entry, "unfold entry")

    # Build the tactic string
    if strategy == "hammer":
        parts = ["hammer"]
        if hints:
            parts.append("using: " + ", ".join(hints))
        return " ".join(parts)

    # sauto and qauto share similar syntax
    parts = [strategy]

    if depth is not None:
        parts.append(f"depth: {depth}")

    if hints:
        parts.append("use: " + ", ".join(hints))

    if unfold:
        parts.append("unfold: " + ", ".join(unfold))

    return " ".join(parts)
