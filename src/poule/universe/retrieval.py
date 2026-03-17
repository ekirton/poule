"""Constraint retrieval operations for universe inspection.

Spec: specification/universe-inspection.md sections 4.1, 4.2.
"""

from __future__ import annotations

from poule.session.errors import SessionError
from poule.universe.graph import build_graph
from poule.universe.parser import parse_constraints
from poule.universe.types import ConstraintGraph


async def retrieve_full_graph(
    session_manager,
    session_id: str,
) -> ConstraintGraph:
    """Retrieve the full universe constraint graph from the current environment.

    Submits 'Print Universes.' via coq_query and parses the output into
    a ConstraintGraph. Session errors are propagated unchanged.
    """
    raw_text = await session_manager.coq_query(session_id, "Print Universes.")
    constraints = parse_constraints(raw_text, "print_universes")
    return build_graph(constraints)


async def retrieve_definition_constraints(
    session_manager,
    session_id: str,
    qualified_name: str,
) -> ConstraintGraph:
    """Retrieve universe constraints for a specific definition.

    Submits Set Printing Universes / Print / Unset Printing Universes
    as an atomic command sequence. Returns a ConstraintGraph with
    filtered_from set to qualified_name.

    Raises INVALID_INPUT for empty qualified_name.
    """
    if not qualified_name:
        raise ValueError("INVALID_INPUT: Required parameter 'qualified_name' must be non-empty.")

    await session_manager.coq_query(session_id, "Set Printing Universes.")
    try:
        raw_text = await session_manager.coq_query(
            session_id, f"Print {qualified_name}."
        )
    finally:
        await session_manager.coq_query(session_id, "Unset Printing Universes.")

    constraints = parse_constraints(raw_text, "print_definition")
    graph = build_graph(constraints)
    graph.filtered_from = qualified_name
    return graph
