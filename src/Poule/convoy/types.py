"""Data types for the convoy pattern assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class IndexInfo:
    """An index argument of an inductive type."""

    name: str
    type: str
    has_decidable_eq: bool


@dataclass(frozen=True)
class DependentHypothesis:
    """A hypothesis whose type mentions an index variable."""

    name: str
    type: str
    indices_mentioned: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DependencyReport:
    """Result of scanning a proof state for index dependencies."""

    target: str
    target_type: str
    inductive_name: str
    parameters: list[str] = field(default_factory=list)
    indices: list[IndexInfo] = field(default_factory=list)
    dependent_hypotheses: list[DependentHypothesis] = field(default_factory=list)
    goal_depends_on_index: bool = False
    error_message: Optional[str] = None


@dataclass(frozen=True)
class Technique:
    """A repair technique for dependent-destruction failures."""

    name: str
    description: str
    axioms_introduced: list[str] = field(default_factory=list)
    requires_plugin: Optional[str] = None


@dataclass(frozen=True)
class TechniqueRecommendation:
    """Ranked technique recommendation with axiom warning."""

    primary: Technique
    alternatives: list[Technique] = field(default_factory=list)
    axiom_warning: Optional[str] = None


@dataclass(frozen=True)
class GeneratedCode:
    """Generated boilerplate code for a repair technique."""

    technique: str
    imports: list[str] = field(default_factory=list)
    setup: list[str] = field(default_factory=list)
    code: str = ""
    validation_result: Optional[str] = None


@dataclass(frozen=True)
class DestructDiagnosis:
    """Complete diagnosis of a dependent-destruction failure."""

    dependency_report: DependencyReport
    recommendation: TechniqueRecommendation
    generated_code: Optional[GeneratedCode] = None
