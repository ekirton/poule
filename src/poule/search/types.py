"""Data types for the proof search engine and fill-admits orchestrator.

Canonical definitions from specification/proof-search-engine.md §5
and specification/fill-admits-orchestrator.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from poule.session.types import ProofState


# ---------------------------------------------------------------------------
# Proof Search Engine types (spec §5)
# ---------------------------------------------------------------------------

@dataclass
class SearchNode:
    """A node in the search tree (spec §5 SearchNode)."""

    proof_state: ProofState
    state_hash: bytes
    tactic_path: list[str] = field(default_factory=list)
    depth: int = 0
    score: float = 1.0
    parent: Optional[SearchNode] = None


@dataclass
class ProofStep:
    """A single verified tactic step (spec §5 ProofStep)."""

    tactic: str
    state_before: ProofState
    state_after: ProofState


@dataclass
class SearchResult:
    """Result of a proof search invocation (spec §5 SearchResult)."""

    status: str  # "success" or "failure"
    proof_script: Optional[list[ProofStep]]
    best_partial: Optional[list[ProofStep]]
    states_explored: int
    unique_states: int
    wall_time_ms: int
    llm_unavailable: bool = False


# ---------------------------------------------------------------------------
# Fill Admits Orchestrator types (spec §5)
# ---------------------------------------------------------------------------

@dataclass
class AdmitLocation:
    """Syntactic position of an admit call (spec §5 AdmitLocation)."""

    proof_name: str
    admit_index: int
    line_number: int
    column_range: tuple[int, int]


@dataclass
class AdmitResult:
    """Per-admit outcome (spec §5 AdmitResult)."""

    proof_name: str
    admit_index: int
    line_number: int
    status: str  # "filled" or "unfilled"
    replacement: Optional[list[str]]
    search_stats: Optional[dict[str, Any]]
    error: Optional[str]


@dataclass
class FillAdmitsResult:
    """Aggregate result of fill-admits invocation (spec §5 FillAdmitsResult)."""

    total_admits: int
    filled: int
    unfilled: int
    results: list[AdmitResult] = field(default_factory=list)
    modified_script: str = ""
