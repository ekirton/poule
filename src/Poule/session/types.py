"""Proof interaction data types.

Canonical definitions from doc/architecture/data-models/proof-types.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Hypothesis:
    name: str
    type: str
    body: Optional[str] = None


@dataclass
class Goal:
    index: int
    type: str
    hypotheses: list[Hypothesis] = field(default_factory=list)


@dataclass
class ProofState:
    schema_version: int
    session_id: str
    step_index: int
    is_complete: bool
    focused_goal_index: Optional[int]
    goals: list[Goal] = field(default_factory=list)


@dataclass
class TraceStep:
    step_index: int
    tactic: Optional[str]
    state: ProofState
    duration_ms: Optional[float] = None


@dataclass
class ProofTrace:
    schema_version: int
    session_id: str
    proof_name: str
    file_path: str
    total_steps: int
    steps: list[TraceStep] = field(default_factory=list)
    partial: bool = False
    failure_step: Optional[int] = None
    failure_message: str = ""


@dataclass
class Premise:
    name: str
    kind: str


@dataclass
class PremiseAnnotation:
    step_index: int
    tactic: str
    premises: list[Premise] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    file_path: str
    proof_name: str
    current_step: int
    total_steps: Optional[int]
    created_at: str
    last_active_at: str


@dataclass
class GoalChange:
    index: int
    before: str
    after: str


@dataclass
class HypothesisChange:
    name: str
    type_before: str
    type_after: str
    body_before: Optional[str] = None
    body_after: Optional[str] = None


@dataclass
class ProofStateDiff:
    from_step: int
    to_step: int
    goals_added: list[Goal] = field(default_factory=list)
    goals_removed: list[Goal] = field(default_factory=list)
    goals_changed: list[GoalChange] = field(default_factory=list)
    hypotheses_added: list[Hypothesis] = field(default_factory=list)
    hypotheses_removed: list[Hypothesis] = field(default_factory=list)
    hypotheses_changed: list[HypothesisChange] = field(default_factory=list)
