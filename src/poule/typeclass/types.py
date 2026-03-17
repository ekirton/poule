"""Data types for the typeclass debugging component.

Spec: specification/typeclass-debugging.md, section 5 (Data Model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TypeclassInfo:
    """A registered instance of a typeclass."""

    instance_name: str
    typeclass_name: str
    type_signature: str
    defining_module: str


@dataclass
class TypeclassSummary:
    """Summary record for a typeclass with optional instance count."""

    typeclass_name: str
    instance_count: Optional[int] = None


@dataclass
class ResolutionNode:
    """A single node in the resolution search tree."""

    instance_name: str
    goal: str
    outcome: str  # "success", "unification_failure", "subgoal_failure", "depth_exceeded"
    failure_detail: Optional[str] = None
    children: List[ResolutionNode] = field(default_factory=list)
    depth: int = 0


@dataclass
class ResolutionTrace:
    """The complete resolution trace for a goal."""

    goal: str
    root_nodes: List[ResolutionNode] = field(default_factory=list)
    succeeded: bool = False
    failure_mode: Optional[str] = None  # "no_instance", "unification", "depth_exceeded", or None
    raw_output: str = ""


@dataclass
class FailureExplanation:
    """Classified failure explanation from a resolution trace."""

    failure_mode: str  # "no_instance", "unification", "depth_exceeded", "unclassified"
    typeclass: Optional[str] = None
    type_arguments: Optional[List[str]] = None
    goal_context: Optional[List[str]] = None
    closest_instance: Optional[str] = None
    successful_unifications: Optional[int] = None
    mismatch_expected: Optional[str] = None
    mismatch_actual: Optional[str] = None
    resolution_path: Optional[List[str]] = None
    cycle_detected: Optional[bool] = None
    cycle_typeclasses: Optional[List[str]] = None
    max_depth_reached: Optional[int] = None
    raw_output: Optional[str] = None


@dataclass
class InstanceConflict:
    """Ambiguity where multiple instances match a goal."""

    goal: str
    matching_instances: List[str] = field(default_factory=list)
    selected_instance: str = ""
    selection_basis: str = "declaration_order"  # "declaration_order", "priority_hint", "specificity"


@dataclass
class InstanceExplanation:
    """Explanation of a specific instance's role in resolution."""

    instance_name: str
    status: str  # "selected", "succeeded_overridden", "failed", "not_considered"
    overridden_by: Optional[str] = None
    failure_reason: Optional[str] = None
    not_considered_reason: Optional[str] = None
