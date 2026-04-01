"""Data types for tactic documentation.

Spec: specification/tactic-documentation.md section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class StrategyEntry:
    """Unfolding strategy for a constant."""
    constant: str
    level: Union[str, int]  # "transparent", "opaque", or integer


@dataclass
class TacticInfo:
    """Structured information about a tactic."""
    name: str
    qualified_name: Optional[str]
    kind: str  # "ltac", "ltac2", "primitive"
    category: Optional[str]  # "automation", "rewriting", "case_analysis", "introduction", "arithmetic", or None
    body: Optional[str]
    is_recursive: bool
    referenced_tactics: list[str] = field(default_factory=list)
    referenced_constants: list[str] = field(default_factory=list)
    strategy_entries: list[StrategyEntry] = field(default_factory=list)


@dataclass
class PairwiseDiff:
    """Pairwise difference between two tactics."""
    tactic_a: str
    tactic_b: str
    differences: list[str] = field(default_factory=list)


@dataclass
class SelectionHint:
    """Guidance on when to prefer a tactic."""
    tactic: str
    prefer_when: list[str] = field(default_factory=list)


@dataclass
class TacticComparison:
    """Structured comparison of two or more tactics."""
    tactics: list[TacticInfo] = field(default_factory=list)
    shared_capabilities: list[str] = field(default_factory=list)
    pairwise_differences: list[PairwiseDiff] = field(default_factory=list)
    selection_guidance: list[SelectionHint] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)


@dataclass
class TacticSuggestion:
    """A ranked tactic suggestion for a proof state."""
    tactic: str
    rank: int
    rationale: str
    confidence: str  # "high", "medium", "low"
    category: str
    source: str = "rule"  # "neural" or "rule"


@dataclass
class HintSummary:
    """Summary counts for a hint database."""
    resolve_count: int = 0
    unfold_count: int = 0
    constructors_count: int = 0
    extern_count: int = 0


@dataclass
class HintEntry:
    """A single hint entry from a hint database."""
    hint_type: str  # "resolve", "unfold", "constructors", "extern"
    name: Optional[str] = None
    pattern: Optional[str] = None
    tactic: Optional[str] = None
    cost: int = 0


@dataclass
class HintDatabase:
    """Parsed hint database with summary and entries."""
    name: str
    summary: HintSummary = field(default_factory=HintSummary)
    entries: list[HintEntry] = field(default_factory=list)
    truncated: bool = False
    total_entries: int = 0
