"""Result Interpreter for Hammer Automation.

Classifies Coq output into structured failure reasons.

Spec: specification/hammer-automation.md section 4.7.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from poule.session.types import ProofState


@dataclass
class InterpretedResult:
    """Classification of Coq output from a hammer tactic attempt."""

    status: str  # "success" or a failure reason
    failure_reason: Optional[str] = None
    detail: Optional[str] = None
    partial_progress: Optional[str] = None


def interpret_result(coq_output: str, proof_state: ProofState) -> InterpretedResult | str:
    """Classify Coq output into a structured result.

    REQUIRES: coq_output is raw text from the Proof Session Manager.
              proof_state is the ProofState observed after submission.
    ENSURES: Returns classification per spec section 4.7 mapping table.

    Returns an InterpretedResult for structured access, but the tests also
    accept plain string returns for simple classifications.
    """
    # Success: goal closed in proof_state_after
    if proof_state.is_complete:
        return InterpretedResult(status="success")

    output_lower = coq_output.lower()

    # Timeout
    if "timeout" in output_lower:
        return InterpretedResult(
            status="failure",
            failure_reason="timeout",
            detail=coq_output,
        )

    # No proof found / hammer failed
    if "no proof found" in output_lower or "hammer failed" in output_lower:
        return InterpretedResult(
            status="failure",
            failure_reason="no_proof_found",
            detail=coq_output,
        )

    # Reconstruction failed with ATP proof
    if "reconstruction failed" in output_lower:
        # Extract ATP proof text: everything after the "Reconstruction failed" line
        lines = coq_output.split("\n")
        atp_lines = []
        found_reconstruction = False
        for line in lines:
            if found_reconstruction:
                atp_lines.append(line)
            elif "reconstruction failed" in line.lower():
                found_reconstruction = True
        partial = "\n".join(atp_lines).strip() if atp_lines else None
        return InterpretedResult(
            status="failure",
            failure_reason="reconstruction_failed",
            detail=coq_output,
            partial_progress=partial or None,
        )

    # Fallback: tactic_error
    return InterpretedResult(
        status="failure",
        failure_reason="tactic_error",
        detail=coq_output,
    )
