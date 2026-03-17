"""Polymorphic definition inspection operations.

Spec: specification/universe-inspection.md sections 4.10, 4.11.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from poule.universe.graph import build_graph, detect_cycles_with_strict_edge
from poule.universe.parser import parse_constraints, parse_instantiations
from poule.universe.types import ComparisonResult, UniverseConstraint


async def retrieve_instantiations(
    session_manager,
    session_id: str,
    use_site_name: str,
) -> List[Tuple[str, Dict[str, str]]]:
    """Retrieve polymorphic instantiation mappings for a definition.

    Submits Set Printing Universes / Print / Unset Printing Universes
    atomically. Returns a list of (definition_name, {param: level}) tuples.

    Raises INVALID_INPUT for empty use_site_name.
    """
    if not use_site_name:
        raise ValueError(
            "INVALID_INPUT: Required parameter 'use_site_name' must be non-empty."
        )

    await session_manager.coq_query(session_id, "Set Printing Universes.")
    try:
        raw_text = await session_manager.coq_query(
            session_id, f"Print {use_site_name}."
        )
    finally:
        await session_manager.coq_query(session_id, "Unset Printing Universes.")

    return parse_instantiations(raw_text)


async def compare_definitions(
    session_manager,
    session_id: str,
    name_a: str,
    name_b: str,
) -> ComparisonResult:
    """Compare two definitions for universe compatibility.

    Retrieves constraints for both definitions, combines them, and checks
    for cycles with strict edges (indicating incompatibility).

    Raises INVALID_INPUT for empty name_a or name_b.
    """
    if not name_a:
        raise ValueError(
            "INVALID_INPUT: Required parameter 'name_a' must be non-empty."
        )
    if not name_b:
        raise ValueError(
            "INVALID_INPUT: Required parameter 'name_b' must be non-empty."
        )

    # Retrieve constraints for both definitions
    await session_manager.coq_query(session_id, "Set Printing Universes.")
    try:
        raw_a = await session_manager.coq_query(session_id, f"Print {name_a}.")
        raw_b = await session_manager.coq_query(session_id, f"Print {name_b}.")
    finally:
        await session_manager.coq_query(session_id, "Unset Printing Universes.")

    constraints_a = parse_constraints(raw_a, "print_definition")
    constraints_b = parse_constraints(raw_b, "print_definition")

    # Combine constraints and check for cycles
    all_constraints = constraints_a + constraints_b
    if not all_constraints:
        return ComparisonResult(compatible=True, explanation="No universe constraints to compare.")

    combined_graph = build_graph(all_constraints)
    cycle = detect_cycles_with_strict_edge(combined_graph)

    if cycle:
        return ComparisonResult(
            compatible=False,
            conflicting_constraints=cycle,
            explanation=(
                f"Incompatible: combining constraints from {name_a} and {name_b} "
                f"creates a cycle with at least one strict inequality."
            ),
        )

    return ComparisonResult(
        compatible=True,
        explanation=(
            f"Compatible: constraints from {name_a} and {name_b} can be "
            f"satisfied simultaneously."
        ),
    )
