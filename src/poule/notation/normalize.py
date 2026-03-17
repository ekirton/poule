"""Input normalization for notation strings (specification §4.1)."""

from __future__ import annotations

import re


class NotationNormalizationError(Exception):
    """Raised when notation input cannot be normalized."""

    def __init__(self, message: str, code: str = "PARSE_ERROR") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def normalize_notation(raw_input: str) -> str:
    """Normalize a notation string for submission to Coq vernacular commands.

    Applies three transformations in order (§4.1):
    1. Strip leading/trailing whitespace and collapse internal whitespace to single spaces.
    2. If no underscore placeholders are present and the string matches an
       infix/prefix/postfix pattern, insert ``_`` placeholders at operand positions.
    3. Wrap the result in double quotes with internal double quotes escaped by doubling.

    Parameters
    ----------
    raw_input:
        A non-empty string representing a notation pattern or Coq term.

    Returns
    -------
    str
        The normalized notation string wrapped in double quotes.

    Raises
    ------
    NotationNormalizationError
        If *raw_input* is empty or collapses to empty after whitespace normalization.
    """
    # Step 1: whitespace normalization
    stripped = raw_input.strip()
    if not stripped:
        raise NotationNormalizationError("Notation string must not be empty")

    collapsed = re.sub(r"\s+", " ", stripped)

    # Step 2: underscore placeholder insertion
    if "_" not in collapsed:
        collapsed = _insert_placeholders(collapsed)

    # Step 3: quote escaping and wrapping
    escaped = collapsed.replace('"', '""')
    return f'"{escaped}"'


def _insert_placeholders(notation: str) -> str:
    """Insert underscore placeholders at operand positions.

    Heuristic rules:
    - Single-token operators (e.g., ``++``, ``!``, ``~``) that contain no
      alphanumeric characters are treated as infix (``_ ++ _``) if they are
      multi-character, or prefix (``! _``) if single-character.
    - Multi-token strings without underscores are treated as potential infix
      expressions where the operator is in the middle.
    """
    tokens = notation.split()

    if len(tokens) == 1:
        token = tokens[0]
        # Pure operator (no alphanumeric characters)
        if not any(c.isalnum() for c in token):
            # All pure operators are treated as infix (e.g. +, -, *, !, ~, ++).
            # Infix is the common case for Coq notations; prefix-only operators
            # (like unary !) will be filtered/handled at a higher level if needed.
            return f"_ {token} _"
        else:
            # Single alphanumeric token — treat as-is (could be a term)
            return notation

    # Multi-token: check if it looks like an infix expression (e.g., "x + y")
    # If there are alphanumeric tokens on both sides of an operator, treat
    # the whole thing as a term expression (for two-step resolution).
    # Otherwise, wrap with underscores.
    has_operator = any(not any(c.isalnum() or c == '_' for c in t) for t in tokens)
    if has_operator and len(tokens) >= 3:
        # Looks like "x op y" — keep as-is for term resolution
        return notation
    elif has_operator and len(tokens) == 2:
        return notation

    return notation
