"""Inconsistency diagnosis for universe constraint errors.

Spec: specification/universe-inspection.md sections 4.6-4.9.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from poule.universe.graph import (
    build_graph,
    detect_cycles_with_strict_edge,
    filter_by_reachability,
)
from poule.universe.parser import parse_constraints
from poule.universe.types import (
    ConstraintAttribution,
    ConstraintGraph,
    InconsistencyDiagnosis,
    UniverseConstraint,
)

# Pattern to extract universe variables from error messages
_UNIVERSE_VAR_RE = re.compile(r"\bu\.\d+\b")

# Pattern to detect universe inconsistency errors
_INCONSISTENCY_RE = re.compile(
    r"[Uu]niverse\s+inconsistency", re.IGNORECASE
)


def _extract_error_variables(error_message: str) -> List[str]:
    """Extract universe variable names from an error message."""
    return list(dict.fromkeys(_UNIVERSE_VAR_RE.findall(error_message)))


def _build_attributions(
    cycle: List[UniverseConstraint],
    about_output: Optional[str] = None,
) -> List[ConstraintAttribution]:
    """Build source attributions for constraints in a cycle.

    Best-effort attribution: when About output mentions a variable,
    map it to the definition. Otherwise, confidence is "unknown".
    """
    attributions = []
    for constraint in cycle:
        definition = None
        location = None
        confidence = "unknown"

        # Try to find definition from about output
        if about_output:
            left_name = constraint.left.name if constraint.left.name else ""
            right_name = constraint.right.name if constraint.right.name else ""
            # Check if the about output mentions one of our variables
            if left_name in about_output or right_name in about_output:
                # Try to extract definition name from About output
                # Format: "def_name : Type@{u.N}"
                m = re.match(r"(\S+)\s*:", about_output)
                if m:
                    definition = m.group(1)
                    confidence = "certain"

        attributions.append(
            ConstraintAttribution(
                constraint=constraint,
                definition=definition,
                location=location,
                confidence=confidence,
            )
        )
    return attributions


def _generate_suggestions(
    cycle: List[UniverseConstraint],
    attributions: List[ConstraintAttribution],
) -> List[str]:
    """Generate resolution suggestions based on cycle structure and attributions.

    At least one suggestion is always returned.
    """
    suggestions = []

    # Check if we have attributed definitions
    attributed_defs = [
        a.definition for a in attributions if a.definition is not None
    ]

    if attributed_defs:
        for def_name in set(attributed_defs):
            suggestions.append(
                f"Consider making {def_name} universe-polymorphic to avoid "
                f"rigid universe constraints."
            )
        if len(set(attributed_defs)) >= 2:
            suggestions.append(
                "Restructure the definitions to decouple their mutual "
                "universe dependencies."
            )
    else:
        suggestions.append(
            "Add universe polymorphism to the definitions involved in this "
            "constraint cycle."
        )

    if not suggestions:
        suggestions.append(
            "Review the universe constraints and consider restructuring "
            "to break the cycle."
        )

    return suggestions


def _build_explanation(
    cycle: List[UniverseConstraint],
    attributions: List[ConstraintAttribution],
    error_text: str,
) -> str:
    """Build a plain-language explanation of the inconsistency."""
    if not cycle:
        return (
            "The universe inconsistency could not be reproduced in the "
            "current environment. The constraint graph may have changed "
            "since the error occurred."
        )

    parts = []
    for c in cycle:
        left = c.left.name or "?"
        right = c.right.name or "?"
        rel_str = {"lt": "<", "le": "<=", "eq": "="}.get(c.relation, c.relation)
        parts.append(f"{left} {rel_str} {right}")

    cycle_desc = ", ".join(parts)
    return (
        f"A cycle with at least one strict inequality was found: {cycle_desc}. "
        f"This violates the well-foundedness requirement for Coq universes."
    )


async def diagnose_universe_error(
    session_manager,
    session_id: str,
    error_message: str,
    environment_context: Dict,
) -> InconsistencyDiagnosis:
    """Diagnose a universe inconsistency error.

    Parses the error message to extract universe variables, retrieves the
    full constraint graph, filters to the relevant subgraph, detects cycles,
    attributes constraints to source definitions, and returns a structured
    diagnosis.

    Raises INVALID_INPUT for empty error_message or non-universe errors.
    """
    if not error_message:
        raise ValueError(
            "INVALID_INPUT: Required parameter 'error_message' must be non-empty."
        )

    if not _INCONSISTENCY_RE.search(error_message):
        raise ValueError(
            "INVALID_INPUT: The provided error is not a universe inconsistency error."
        )

    # Extract universe variables from the error
    error_vars = _extract_error_variables(error_message)

    # Retrieve the full constraint graph
    raw_text = await session_manager.coq_query(session_id, "Print Universes.")
    constraints = parse_constraints(raw_text, "print_universes")
    full_graph = build_graph(constraints)

    # Filter to relevant subgraph
    if error_vars:
        relevant_subgraph = filter_by_reachability(full_graph, error_vars)
    else:
        relevant_subgraph = full_graph

    # Detect cycles with strict edges
    cycle = detect_cycles_with_strict_edge(relevant_subgraph)

    # Attempt source attribution
    about_output = None
    try:
        about_output = await session_manager.coq_query(session_id, "About")
    except Exception:
        pass

    attributions = _build_attributions(cycle, about_output)

    # Generate suggestions
    suggestions = _generate_suggestions(cycle, attributions)

    # Build explanation
    explanation = _build_explanation(cycle, attributions, error_message)

    return InconsistencyDiagnosis(
        error_text=error_message,
        cycle=cycle,
        attributions=attributions,
        explanation=explanation,
        suggestions=suggestions,
        relevant_subgraph=relevant_subgraph,
    )
