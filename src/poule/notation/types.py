"""Data types for notation inspection (specification §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class NotationInfo:
    """Structured representation of a Coq notation (§5 NotationInfo)."""

    notation_string: str
    expansion: str
    level: int
    associativity: str  # "left", "right", or "none"
    arg_levels: List[Tuple[str, int]]
    format: Optional[str]
    scope: str
    defining_module: Optional[str]
    only_parsing: bool
    only_printing: bool


@dataclass
class ScopeInfo:
    """Structured representation of a Coq scope (§5 ScopeInfo)."""

    scope_name: str
    bound_type: Optional[str]
    notations: List[NotationInfo] = field(default_factory=list)


@dataclass
class NotationInterpretation:
    """A single interpretation of a notation in a specific scope (§5)."""

    expansion: str
    scope: str
    defining_module: Optional[str]
    priority_rank: int
    is_default: bool


@dataclass
class NotationAmbiguity:
    """Ambiguous notation with multiple interpretations (§5)."""

    notation_string: str
    interpretations: List[NotationInterpretation]
    active_index: int
    resolution_reason: str
