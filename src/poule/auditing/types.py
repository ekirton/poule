"""Data types for the assumption auditing engine."""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# AxiomCategory: StrEnum on Python 3.11+, str + Enum otherwise.
if sys.version_info >= (3, 11):
    class AxiomCategory(enum.StrEnum):
        CLASSICAL = "classical"
        EXTENSIONALITY = "extensionality"
        CHOICE = "choice"
        PROOF_IRRELEVANCE = "proof_irrelevance"
        CUSTOM = "custom"
else:
    class AxiomCategory(str, enum.Enum):  # type: ignore[no-redef]
        CLASSICAL = "classical"
        EXTENSIONALITY = "extensionality"
        CHOICE = "choice"
        PROOF_IRRELEVANCE = "proof_irrelevance"
        CUSTOM = "custom"


@dataclass(frozen=True)
class ClassifiedAxiom:
    """An axiom dependency with classification."""

    name: str
    type: str
    category: AxiomCategory
    explanation: str


@dataclass(frozen=True)
class OpaqueDependency:
    """An opaque dependency (Qed/Admitted)."""

    name: str
    type: str


@dataclass(frozen=True)
class AssumptionResult:
    """Result of auditing a single theorem's assumptions."""

    name: str
    is_closed: bool
    axioms: List[ClassifiedAxiom]
    opaque_dependencies: List[OpaqueDependency]
    error: Optional[str] = None


@dataclass(frozen=True)
class AxiomUsageSummary:
    """Per-axiom usage summary across a module."""

    axiom_name: str
    category: AxiomCategory
    dependent_count: int


@dataclass(frozen=True)
class FlaggedTheorem:
    """A theorem flagged for using axioms in specified categories."""

    name: str
    flagged_axioms: List[ClassifiedAxiom]


@dataclass(frozen=True)
class ModuleAuditResult:
    """Result of batch auditing a module."""

    module: str
    theorem_count: int
    axiom_free_count: int
    axiom_summary: List[AxiomUsageSummary]
    flagged_theorems: List[FlaggedTheorem]
    per_theorem: List[AssumptionResult]


@dataclass(frozen=True)
class MatrixRow:
    """A row in the axiom-by-theorem presence matrix."""

    axiom: ClassifiedAxiom
    present_in: List[str]


@dataclass(frozen=True)
class ComparisonResult:
    """Result of comparing assumption profiles across theorems."""

    theorems: List[str]
    shared_axioms: List[ClassifiedAxiom]
    unique_axioms: Dict[str, List[ClassifiedAxiom]]
    matrix: Optional[List[MatrixRow]]
    weakest: List[str]


@dataclass(frozen=True)
class ParsedDependency:
    """A single parsed dependency from Print Assumptions output."""

    name: str
    type: str


@dataclass(frozen=True)
class ParsedOutput:
    """Parsed output from Print Assumptions."""

    is_closed: bool
    dependencies: List[ParsedDependency]
    axioms: List[ClassifiedAxiom] = field(default_factory=list)
    opaque_dependencies: List[OpaqueDependency] = field(default_factory=list)
