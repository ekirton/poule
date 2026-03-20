"""Data types for the setoid rewriting assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class RelationSlot:
    """A single argument position in a Proper signature."""

    position: int
    relation: Optional[str] = None
    argument_type: str = ""
    variance: str = "covariant"


@dataclass(frozen=True)
class ParsedError:
    """Parsed and classified rewriting error."""

    error_class: str  # "missing_proper", "binder_rewrite", "missing_equivalence", "pattern_not_found"
    function_name: Optional[str] = None
    partial_signature: list[RelationSlot] = field(default_factory=list)
    binder_type: Optional[str] = None  # "forall", "exists", "fun"
    rewrite_target: Optional[str] = None
    raw_error: str = ""


@dataclass(frozen=True)
class ExistingInstance:
    """An existing Proper instance found in the environment."""

    instance_name: str
    signature: str
    compatibility: str  # "exact_match", "compatible", "incompatible"
    incompatibility_detail: Optional[str] = None


@dataclass(frozen=True)
class InstanceCheckResult:
    """Results of checking for existing Proper instances."""

    existing_instances: list[ExistingInstance] = field(default_factory=list)
    base_relation_registered: bool = False
    base_relation_class: Optional[str] = None  # "Equivalence", "PreOrder", "PER"
    stdlib_suggestion: Optional[str] = None


@dataclass(frozen=True)
class ProperSignature:
    """Generated Proper instance signature."""

    function_name: str
    slots: list[RelationSlot] = field(default_factory=list)
    return_relation: str = "eq"
    declaration: str = ""


@dataclass(frozen=True)
class ProofStrategy:
    """Suggested proof strategy for a Proper obligation."""

    strategy: str  # "solve_proper", "f_equiv", "manual"
    confidence: str  # "high", "medium", "low"
    proof_skeleton: str = ""


@dataclass(frozen=True)
class RewriteDiagnosis:
    """Complete diagnosis of a setoid rewriting failure."""

    parsed_error: ParsedError
    instance_check: InstanceCheckResult
    generated_signature: Optional[ProperSignature] = None
    proof_strategy: Optional[ProofStrategy] = None
    suggestion: str = ""
