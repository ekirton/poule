"""Error classification for Coq vernacular output.

Classifies raw Coq error output into structured error codes and messages.
"""

from __future__ import annotations

import re

# Compiled regex patterns for error classification (compiled once at module load).
_NOT_FOUND_RE = re.compile(
    r"(?:The reference|The variable|Toplevel input).*not found", re.IGNORECASE
)
_TYPE_ERROR_RE = re.compile(
    r"has type.*while it is expected to have type|ill-typed|type mismatch",
    re.IGNORECASE,
)
_SYNTAX_RE = re.compile(r"Syntax error", re.IGNORECASE)
_STRATEGY_RE = re.compile(r"Unknown reduction strategy", re.IGNORECASE)
_TIMEOUT_RE = re.compile(r"Timeout", re.IGNORECASE)


# Error codes
INVALID_COMMAND = "INVALID_COMMAND"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
NOT_FOUND = "NOT_FOUND"
TYPE_ERROR = "TYPE_ERROR"
PARSE_ERROR = "PARSE_ERROR"
INVALID_STRATEGY = "INVALID_STRATEGY"
TIMEOUT = "TIMEOUT"


def classify_error(raw: str) -> tuple[str, str]:
    """Classify a raw Coq error string into an (error_code, message) tuple.

    When the error does not match a known pattern, it falls back to PARSE_ERROR
    with the raw Coq error message preserved.
    """
    # Strip the leading "Error: " prefix if present for the message body.
    body = re.sub(r"^Error:\s*", "", raw).strip()

    if _NOT_FOUND_RE.search(raw):
        # Extract the name if possible
        m = re.search(r"reference\s+(\S+)", raw)
        name = m.group(1) if m else "unknown"
        return NOT_FOUND, f'"{name}" not found in the current environment.'

    if _TYPE_ERROR_RE.search(raw):
        return TYPE_ERROR, f"Type error: {body}"

    if _SYNTAX_RE.search(raw):
        return PARSE_ERROR, f"Failed to parse: {body}"

    if _STRATEGY_RE.search(raw):
        return (
            INVALID_STRATEGY,
            "Unknown reduction strategy. Valid strategies: cbv, lazy, cbn, simpl, hnf, unfold.",
        )

    if _TIMEOUT_RE.search(raw):
        return TIMEOUT, "Computation exceeded time limit."

    # Unclassified -> PARSE_ERROR with raw message preserved
    return PARSE_ERROR, f"Failed to parse: {body}"
