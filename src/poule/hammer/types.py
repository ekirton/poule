"""Data types for Hammer Automation.

Spec: specification/hammer-automation.md section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from poule.session.types import ProofState


@dataclass
class StrategyDiagnostic:
    """Diagnostic information for a single strategy attempt."""

    strategy: str  # "hammer" | "sauto" | "qauto"
    failure_reason: str  # "timeout" | "no_proof_found" | "reconstruction_failed" | "tactic_error"
    detail: str
    partial_progress: Optional[str]
    wall_time_ms: int
    timeout_used: float


@dataclass
class HammerResult:
    """Output of a hammer automation invocation."""

    status: str  # "success" | "failure"
    proof_script: Optional[str]
    atp_proof: Optional[str]
    strategy_used: Optional[str]  # "hammer" | "sauto" | "qauto" | None
    state: ProofState
    diagnostics: list[StrategyDiagnostic] = field(default_factory=list)
    wall_time_ms: int = 0
