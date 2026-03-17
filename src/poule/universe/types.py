"""Data model types for universe constraint inspection.

Spec: specification/universe-inspection.md section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class UniverseExpression:
    """A universe level expression.

    kind: "variable", "algebraic", "set", or "prop".
    name: Universe variable name (e.g. "u.42") when kind="variable"; None otherwise.
    base: Base expression for algebraic kind (base+offset form).
    offset: Non-negative integer increment for algebraic kind.
    operands: List of operands for max(...) expressions within algebraic kind.
    """

    kind: str
    name: Optional[str]
    base: Optional[UniverseExpression]
    offset: Optional[int]
    operands: Optional[List[UniverseExpression]]


@dataclass
class UniverseConstraint:
    """A single constraint between two universe expressions.

    relation: "lt", "le", or "eq".
    source: Qualified name of the introducing definition; None when unknown.
    """

    left: UniverseExpression
    relation: str
    right: UniverseExpression
    source: Optional[str] = None


@dataclass
class ConstraintGraph:
    """The full or filtered universe constraint graph."""

    variables: List[str]
    constraints: List[UniverseConstraint]
    node_count: int
    edge_count: int
    filtered_from: Optional[str] = None


@dataclass
class ConstraintAttribution:
    """Maps a constraint to the source definition that introduced it."""

    constraint: UniverseConstraint
    definition: Optional[str]
    location: Optional[str]
    confidence: str  # "certain", "inferred", or "unknown"


@dataclass
class InconsistencyDiagnosis:
    """The result of diagnosing a universe inconsistency error."""

    error_text: str
    cycle: List[UniverseConstraint]
    attributions: List[ConstraintAttribution]
    explanation: str
    suggestions: List[str]
    relevant_subgraph: ConstraintGraph


@dataclass
class ComparisonResult:
    """Result of comparing two definitions for universe compatibility."""

    compatible: bool
    conflicting_constraints: List[UniverseConstraint] = field(default_factory=list)
    explanation: str = ""
