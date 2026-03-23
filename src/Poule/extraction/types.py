"""Training data extraction types.

Canonical definitions from doc/architecture/data-models/extraction-types.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorKind(Enum):
    TIMEOUT = "timeout"
    BACKEND_CRASH = "backend_crash"
    TACTIC_FAILURE = "tactic_failure"
    LOAD_FAILURE = "load_failure"
    NO_PROOF_BODY = "no_proof_body"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Proof-level types (reuse Goal/Hypothesis from session.types at the
# boundary, but extraction has its own Premise and Diff types)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hypothesis:
    name: str
    type: str
    body: Optional[str] = None


@dataclass(frozen=True)
class Goal:
    index: int
    type: str
    hypotheses: list[Hypothesis] = field(default_factory=list)


@dataclass(frozen=True)
class Premise:
    name: str
    kind: str


@dataclass(frozen=True)
class GoalChange:
    index: int
    before: str
    after: str


@dataclass(frozen=True)
class HypothesisChange:
    name: str
    type_before: str
    type_after: str
    body_before: Optional[str] = None
    body_after: Optional[str] = None


@dataclass(frozen=True)
class ExtractionDiff:
    goals_added: list[Goal] = field(default_factory=list)
    goals_removed: list[Goal] = field(default_factory=list)
    goals_changed: list[GoalChange] = field(default_factory=list)
    hypotheses_added: list[Hypothesis] = field(default_factory=list)
    hypotheses_removed: list[Hypothesis] = field(default_factory=list)
    hypotheses_changed: list[HypothesisChange] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionStep:
    step_index: int
    tactic: Optional[str]
    goals: list[Goal] = field(default_factory=list)
    focused_goal_index: Optional[int] = None
    premises: list[Premise] = field(default_factory=list)
    diff: Optional[ExtractionDiff] = None


@dataclass(frozen=True)
class ExtractionRecord:
    schema_version: int
    record_type: str
    theorem_name: str
    source_file: str
    project_id: str
    total_steps: int
    steps: list[ExtractionStep] = field(default_factory=list)


@dataclass(frozen=True)
class PartialExtractionRecord:
    schema_version: int
    record_type: str
    theorem_name: str
    source_file: str
    project_id: str
    total_steps: int
    completed_steps: int
    failure_at_step: int
    failure_kind: str
    failure_message: str
    steps: list[ExtractionStep] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionError:
    schema_version: int
    record_type: str
    theorem_name: str
    source_file: str
    project_id: str
    error_kind: str
    error_message: str


# ---------------------------------------------------------------------------
# Campaign metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectMetadata:
    project_id: str
    project_path: str
    coq_version: str
    commit_hash: Optional[str] = None


@dataclass(frozen=True)
class CampaignMetadata:
    schema_version: int
    record_type: str
    extraction_tool_version: str
    extraction_timestamp: str
    projects: list[ProjectMetadata] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Summary types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileSummary:
    source_file: str
    theorems_found: int
    extracted: int
    failed: int
    no_proof_body: int = 0
    partial: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ProjectSummary:
    project_id: str
    theorems_found: int
    extracted: int
    failed: int
    no_proof_body: int = 0
    partial: int = 0
    skipped: int = 0
    per_file: list[FileSummary] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionSummary:
    schema_version: int
    record_type: str
    total_theorems_found: int
    total_extracted: int
    total_failed: int
    total_no_proof_body: int = 0
    total_partial: int = 0
    total_skipped: int = 0
    per_project: list[ProjectSummary] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Dependency graph types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DependencyRef:
    name: str
    kind: str


@dataclass(frozen=True)
class DependencyEntry:
    theorem_name: str
    source_file: str
    project_id: str
    depends_on: list[DependencyRef] = field(default_factory=list)

    def to_json(self) -> str:
        """Serialize to a compact JSON string (no trailing newline)."""
        import json
        obj = {
            "theorem_name": self.theorem_name,
            "source_file": self.source_file,
            "project_id": self.project_id,
            "depends_on": [
                {"name": ref.name, "kind": ref.kind}
                for ref in self.depends_on
            ],
        }
        return json.dumps(obj, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Quality report types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DistributionStats:
    min: int
    max: int
    mean: float
    median: float
    p25: float
    p75: float
    p95: float


@dataclass(frozen=True)
class TacticFrequency:
    tactic: str
    count: int


@dataclass(frozen=True)
class ProjectQualityReport:
    project_id: str
    premise_coverage: float
    proof_length_distribution: DistributionStats
    theorem_count: int


@dataclass(frozen=True)
class QualityReport:
    premise_coverage: float
    proof_length_distribution: DistributionStats
    tactic_vocabulary: list[TacticFrequency] = field(default_factory=list)
    per_project: list[ProjectQualityReport] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Error analysis report types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileErrorSummary:
    source_file: str
    error_count: int
    by_kind: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class NearTimeoutEntry:
    theorem_name: str
    source_file: str
    total_duration_s: float


@dataclass(frozen=True)
class TimingEntry:
    theorem_name: str
    source_file: str
    total_duration_s: float


@dataclass(frozen=True)
class ErrorAnalysisReport:
    files_analyzed: int
    total_theorems: int
    total_extracted: int
    total_failed: int
    by_error_kind: dict[str, int]
    by_file: list[FileErrorSummary]
    near_timeout: list[NearTimeoutEntry]
    slowest_successful: list[TimingEntry]
    timeout_threshold: int


# ---------------------------------------------------------------------------
# Scope filter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeFilter:
    name_pattern: Optional[str] = None
    module_prefixes: Optional[list[str]] = None

    def matches(self, name: str, module: str) -> bool:
        """Return True if the theorem matches this filter.

        When both fields are set, both must match (conjunction).
        When neither is set, all theorems are included.
        """
        name_ok = True
        if self.name_pattern is not None:
            name_ok = bool(re.search(self.name_pattern, name))

        module_ok = True
        if self.module_prefixes is not None:
            module_ok = any(module.startswith(p) for p in self.module_prefixes)

        return name_ok and module_ok
