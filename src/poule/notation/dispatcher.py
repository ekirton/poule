"""Notation query dispatcher (specification §4.2-4.7, §6)."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple, Union

from poule.notation.normalize import NotationNormalizationError, normalize_notation
from poule.notation.parsers import (
    ParseError,
    parse_locate_notation,
    parse_print_notation,
    parse_print_scope,
    parse_print_visibility,
)
from poule.notation.types import (
    NotationAmbiguity,
    NotationInfo,
    NotationInterpretation,
    ScopeInfo,
)


class NotationError(Exception):
    """Structured error for notation-specific failures."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


async def dispatch_notation_query(
    *,
    command: str,
    session_id: str,
    session_manager: Any,
    notation: str = "",
    scope_name: str = "",
    coq_version: Optional[str] = None,
    expected_type: Optional[str] = None,
) -> Any:
    """Dispatch a notation query to the appropriate handler.

    Parameters
    ----------
    command:
        One of ``print_notation``, ``locate_notation``, ``print_scope``,
        ``print_visibility``.
    session_id:
        Active Coq session identifier.
    session_manager:
        Session manager instance with ``submit_command(session_id, cmd)`` method.
    notation:
        Notation string (for print_notation, locate_notation).
    scope_name:
        Scope name (for print_scope).
    coq_version:
        Optional Coq version string for compatibility checks.
    expected_type:
        Optional expected type for type-directed resolution.
    """
    if command == "print_notation":
        return await _handle_print_notation(
            notation=notation,
            session_id=session_id,
            session_manager=session_manager,
            coq_version=coq_version,
        )
    elif command == "locate_notation":
        return await _handle_locate_notation(
            notation=notation,
            session_id=session_id,
            session_manager=session_manager,
        )
    elif command == "print_scope":
        return await _handle_print_scope(
            scope_name=scope_name,
            session_id=session_id,
            session_manager=session_manager,
        )
    elif command == "print_visibility":
        return await _handle_print_visibility(
            session_id=session_id,
            session_manager=session_manager,
        )
    else:
        raise NotationError("PARSE_ERROR", f"Unknown notation command: {command}")


async def _handle_print_notation(
    *,
    notation: str,
    session_id: str,
    session_manager: Any,
    coq_version: Optional[str] = None,
) -> Union[NotationInfo, NotationAmbiguity]:
    """Handle print_notation command (§4.2)."""
    if not notation or not notation.strip():
        raise NotationError("PARSE_ERROR", "Notation string must not be empty")

    # §7.4: Version compatibility check
    if coq_version is not None:
        try:
            major_minor = coq_version.split(".")
            major = int(major_minor[0])
            minor = int(major_minor[1]) if len(major_minor) > 1 else 0
            if major < 8 or (major == 8 and minor < 19):
                raise NotationError(
                    "UNSUPPORTED_COMMAND",
                    "`Print Notation` requires Coq 8.19 or later. Use `Locate` as a fallback.",
                )
        except (ValueError, IndexError):
            pass  # Can't parse version, proceed

    normalized = normalize_notation(notation)

    # Build and submit the command
    cmd = f"Print Notation {normalized}."
    raw_output = await session_manager.submit_command(session_id, cmd)

    # Check for error responses
    if _is_error_output(raw_output):
        # Try two-step resolution: maybe the input is a term, not a notation
        try:
            return await two_step_resolve(
                term=notation,
                session_id=session_id,
                session_manager=session_manager,
            )
        except (NotationError, ParseError):
            # Two-step also failed — report as not found
            raise NotationError(
                "NOTATION_NOT_FOUND",
                f'Notation {normalized} not found in the current environment.',
            )

    # Parse the output
    try:
        return parse_print_notation(raw_output)
    except ParseError:
        # If parsing fails, also try two-step resolution
        try:
            return await two_step_resolve(
                term=notation,
                session_id=session_id,
                session_manager=session_manager,
            )
        except (NotationError, ParseError):
            raise NotationError(
                "NOTATION_NOT_FOUND",
                f'Notation {normalized} not found in the current environment.',
            )


async def _handle_locate_notation(
    *,
    notation: str,
    session_id: str,
    session_manager: Any,
) -> List[NotationInterpretation]:
    """Handle locate_notation command (§4.3)."""
    if not notation or not notation.strip():
        raise NotationError("PARSE_ERROR", "Notation string must not be empty")

    normalized = normalize_notation(notation)
    cmd = f"Locate {normalized}."
    raw_output = await session_manager.submit_command(session_id, cmd)

    if _is_error_output(raw_output):
        raise NotationError(
            "NOTATION_NOT_FOUND",
            f'Notation {normalized} not found in the current environment.',
        )

    return parse_locate_notation(raw_output)


async def _handle_print_scope(
    *,
    scope_name: str,
    session_id: str,
    session_manager: Any,
) -> ScopeInfo:
    """Handle print_scope command (§4.4)."""
    if not scope_name or not scope_name.strip():
        raise NotationError("PARSE_ERROR", "Scope name must not be empty")

    cmd = f"Print Scope {scope_name}."
    raw_output = await session_manager.submit_command(session_id, cmd)

    if _is_error_output(raw_output):
        raise NotationError(
            "SCOPE_NOT_FOUND",
            f"Scope {scope_name} is not registered in the current environment.",
        )

    return parse_print_scope(raw_output)


async def _handle_print_visibility(
    *,
    session_id: str,
    session_manager: Any,
) -> List[Tuple[str, Optional[str]]]:
    """Handle print_visibility command (§4.5)."""
    cmd = "Print Visibility."
    raw_output = await session_manager.submit_command(session_id, cmd)
    return parse_print_visibility(raw_output)


async def resolve_ambiguity(
    *,
    notation_string: str,
    session_id: str,
    session_manager: Any,
    expected_type: Optional[str] = None,
) -> NotationAmbiguity:
    """Resolve ambiguity for a notation with multiple scope interpretations (§4.6).

    Steps:
    1. Issue ``Locate "<notation>"`` to retrieve all interpretations.
    2. Issue ``Print Visibility.`` to retrieve scope stacking order.
    3. Match each interpretation's scope against visibility order.
    4. Identify the active interpretation.
    5. Return a NotationAmbiguity structure.
    """
    normalized = normalize_notation(notation_string)

    # Step 1: Locate
    locate_cmd = f"Locate {normalized}."
    locate_output = await session_manager.submit_command(session_id, locate_cmd)
    interpretations = parse_locate_notation(locate_output)

    # Step 2: Print Visibility
    vis_output = await session_manager.submit_command(session_id, "Print Visibility.")
    visibility = parse_print_visibility(vis_output)

    # Step 3: Build scope priority map
    scope_priority = {scope: rank for rank, (scope, _) in enumerate(visibility)}
    scope_bound_types = {scope: btype for scope, btype in visibility}

    # Step 4: Sort interpretations by priority rank and assign ranks
    sorted_interps: List[NotationInterpretation] = []
    for interp in interpretations:
        rank = scope_priority.get(interp.scope, 999)
        sorted_interps.append(NotationInterpretation(
            expansion=interp.expansion,
            scope=interp.scope,
            defining_module=interp.defining_module,
            priority_rank=rank,
            is_default=interp.is_default,
        ))

    sorted_interps.sort(key=lambda x: x.priority_rank)

    # Re-number ranks to be contiguous 0, 1, 2, ...
    for i, interp in enumerate(sorted_interps):
        interp.priority_rank = i

    # Step 5: Determine active interpretation and reason
    active_index = 0
    resolution_reason = "highest-priority open scope"

    if expected_type is not None:
        # Check for type-directed binding
        for i, interp in enumerate(sorted_interps):
            bound_type = scope_bound_types.get(interp.scope)
            if bound_type == expected_type:
                active_index = i
                resolution_reason = f"type-directed binding on {expected_type}"
                break

    return NotationAmbiguity(
        notation_string=notation_string,
        interpretations=sorted_interps,
        active_index=active_index,
        resolution_reason=resolution_reason,
    )


async def two_step_resolve(
    *,
    term: str,
    session_id: str,
    session_manager: Any,
) -> NotationInfo:
    """Two-step resolution for term-based queries (§4.7).

    Steps:
    1. Issue ``Locate "<term>"`` to identify which notation was used.
    2. Issue ``Print Notation "<notation>"`` using the identified notation string.
    3. Return the full NotationInfo.
    """
    # Step 1: Locate the term to find the notation
    locate_cmd = f'Locate "{term}".'
    locate_output = await session_manager.submit_command(session_id, locate_cmd)

    if _is_error_output(locate_output):
        raise NotationError(
            "NOTATION_NOT_FOUND",
            f'Notation for term "{term}" not found in the current environment.',
        )

    interpretations = parse_locate_notation(locate_output)
    if not interpretations:
        raise NotationError(
            "NOTATION_NOT_FOUND",
            f'Notation for term "{term}" not found in the current environment.',
        )

    # Use the first (default or only) interpretation to identify the notation
    # Extract the notation string from the Locate output
    # The notation string is embedded in the Locate output format
    import re
    notation_match = re.search(r'Notation\s+"([^"]+)"', locate_output)
    if not notation_match:
        raise NotationError(
            "PARSE_ERROR",
            f"Failed to identify notation from Locate output for term: {term}",
        )
    notation_string = notation_match.group(1)

    # Step 2: Print Notation for the identified notation
    print_cmd = f'Print Notation "{notation_string}".'
    print_output = await session_manager.submit_command(session_id, print_cmd)

    if _is_error_output(print_output):
        raise NotationError(
            "NOTATION_NOT_FOUND",
            f'Notation "{notation_string}" not found in the current environment.',
        )

    return parse_print_notation(print_output)


def _is_error_output(raw: str) -> bool:
    """Check if Coq output indicates an error."""
    if not raw or not raw.strip():
        return True
    error_indicators = ["Error:", "Unknown", "No notation"]
    return any(indicator in raw for indicator in error_indicators)
