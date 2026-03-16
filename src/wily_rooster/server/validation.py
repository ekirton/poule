"""Input validation functions for the MCP server layer."""

from __future__ import annotations

_VALID_RELATIONS = frozenset({"uses", "used_by", "same_module", "same_typeclass"})


def validate_string(value: str) -> str:
    """Validate and strip a string parameter.

    Raises ValueError if the string is empty or whitespace-only after stripping.
    Returns the stripped string.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("String parameter must be non-empty after stripping whitespace.")
    return stripped


def validate_limit(value: int) -> int:
    """Clamp a limit parameter to [1, 200]."""
    if value < 1:
        return 1
    if value > 200:
        return 200
    return value


def validate_symbols(symbols: list[str]) -> list[str]:
    """Validate a symbols list: non-empty list of non-empty stripped strings.

    Raises ValueError if the list is empty or any element is empty after stripping.
    Returns a list of stripped strings.
    """
    if not symbols:
        raise ValueError("Symbols list must be non-empty.")
    result = []
    for s in symbols:
        stripped = s.strip()
        if not stripped:
            raise ValueError("Each symbol must be non-empty after stripping whitespace.")
        result.append(stripped)
    return result


def validate_relation(relation: str) -> str:
    """Validate a relation parameter against the four recognized values.

    Raises ValueError if the relation is not one of: uses, used_by, same_module, same_typeclass.
    Returns the relation unchanged.
    """
    if relation not in _VALID_RELATIONS:
        raise ValueError(
            f"Invalid relation '{relation}'. Must be one of: {', '.join(sorted(_VALID_RELATIONS))}."
        )
    return relation
