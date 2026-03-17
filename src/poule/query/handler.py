"""Vernacular introspection query handler.

Entry point: coq_query(command, argument, session_id?, session_manager?, process_pool?)
"""

from __future__ import annotations

import re

from poule.query.dispatch import build_vernacular
from poule.query.errors import (
    INVALID_ARGUMENT,
    INVALID_COMMAND,
    classify_error,
)
from poule.query.parser import parse_output
from poule.query.types import Command, QueryResult
from poule.session.errors import SessionError

# Pre-compiled pattern to detect Coq error output.
_ERROR_RE = re.compile(r"^Error:", re.MULTILINE)

# Valid command names for error messages.
_VALID_COMMANDS = ", ".join(c.value for c in Command)


class QueryError(Exception):
    """Structured error raised by the query handler."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


async def coq_query(
    command: str,
    argument: str,
    session_id: str | None = None,
    session_manager=None,
    process_pool=None,
) -> QueryResult:
    """Execute a Coq vernacular introspection command.

    Args:
        command: One of Print, Check, About, Locate, Search, Compute, Eval.
        argument: The command argument (non-empty string).
        session_id: If provided, execute in this proof session's context.
        session_manager: The proof session manager (required when session_id is given).
        process_pool: Standalone Coq process pool (required when session_id is omitted).

    Returns:
        A QueryResult with the parsed output.

    Raises:
        QueryError: On input validation errors or Coq execution errors.
        SessionError: On session-related errors (propagated from session manager).
    """
    # --- Input validation (spec 7.1) ---
    valid_values = {c.value for c in Command}
    if command not in valid_values:
        raise QueryError(
            INVALID_COMMAND,
            f'Unknown command "{command}". Valid commands: {_VALID_COMMANDS}.',
        )

    if not argument:
        raise QueryError(INVALID_ARGUMENT, "Argument must not be empty.")

    # --- Build vernacular string (spec 4.2) ---
    vernacular = build_vernacular(command, argument)

    # --- Execute (spec 4.3) ---
    raw_output: str
    if session_id is not None:
        # Session-aware execution
        raw_output = await session_manager.submit_vernacular(session_id, vernacular)
    else:
        # Session-free execution
        raw_output = await process_pool.send_command(vernacular)

    # --- Check for Coq errors in output (spec 7.3) ---
    if _ERROR_RE.search(raw_output):
        code, message = classify_error(raw_output)
        raise QueryError(code, message)

    # --- Parse output (spec 4.4) ---
    output, warnings = parse_output(raw_output, command=command)

    return QueryResult(
        command=command,
        argument=argument,
        output=output,
        warnings=warnings,
    )
