from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AutoSearchNode:
    action: str
    hint_name: Optional[str]
    remaining_depth: int
    outcome: str  # "success" or "failure"
    children: list[AutoSearchNode] = field(default_factory=list)
    raw_line: str = ""


@dataclass
class AutoSearchTree:
    root_nodes: list[AutoSearchNode] = field(default_factory=list)
    max_depth: int = 0
    min_leaf_depth: int = 0
    depth_limit_reached: bool = False
    raw_messages: list[str] = field(default_factory=list)


@dataclass
class RawTraceCapture:
    messages: list[str]
    outcome: str  # "succeeded" or "failed"
    goal: str
    tactic: str
    semantic_divergence_caveat: Optional[str] = None


@dataclass
class RejectionReason:
    reason: str
    detail: str = ""
    fix_suggestion: str = ""


@dataclass
class HintClassification:
    hint_name: str
    hint_type: str  # "resolve", "unfold", "constructors", "extern", "hypothesis"
    database: Optional[str] = None
    classification: str = "not_considered"
    rejection_reason: Optional[RejectionReason] = None
    trace_node: Optional[AutoSearchNode] = None


@dataclass
class DatabaseConfig:
    name: str
    transparency: str  # "transparent" or "opaque"
    hint_count: int


@dataclass
class VariantResult:
    tactic: str
    outcome: str
    databases_consulted: list[str] = field(default_factory=list)
    winning_path: Optional[list[AutoSearchNode]] = None


@dataclass
class DivergencePoint:
    hint_name: str
    per_variant: dict[str, HintClassification] = field(default_factory=dict)
    explanation: str = ""


@dataclass
class VariantComparison:
    variants: list[VariantResult] = field(default_factory=list)
    divergence_points: list[DivergencePoint] = field(default_factory=list)


@dataclass
class AutoDiagnosis:
    tactic: str
    outcome: str
    goal: str
    classifications: list[HintClassification] = field(default_factory=list)
    winning_path: Optional[list[AutoSearchNode]] = None
    min_depth_required: Optional[int] = None
    databases_consulted: list[DatabaseConfig] = field(default_factory=list)
    variant_comparison: Optional[VariantComparison] = None
    semantic_divergence_caveat: Optional[str] = None
