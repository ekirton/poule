"""Top-level analyzer for the convoy pattern assistant."""

from __future__ import annotations

import re
from typing import Any

from .errors import ConvoyError
from .generator import BoilerplateGenerator
from .scanner import DependencyScanner
from .selector import TechniqueSelector
from .types import DestructDiagnosis


async def diagnose_destruct(
    session_id: str,
    target: str | None,
    axiom_tolerance: str = "strict",
    generate_code: bool = True,
    session_manager: Any = None,
) -> DestructDiagnosis:
    """Diagnose a dependent-destruction failure.

    See specification/convoy-pattern-assistant.md §4.1.
    """
    if session_manager is None:
        raise ConvoyError("SESSION_NOT_FOUND", "Destruct diagnosis requires an active proof session.")

    # Get proof state
    try:
        proof_state = await session_manager.observe_proof_state(session_id)
    except Exception as exc:
        code = getattr(exc, "code", None)
        msg = str(exc)
        if code:
            raise ConvoyError(code, getattr(exc, "message", msg)) from exc
        if "SESSION_NOT_FOUND" in msg:
            raise ConvoyError("SESSION_NOT_FOUND", msg) from exc
        if "BACKEND_CRASHED" in msg:
            raise ConvoyError("BACKEND_CRASHED", msg) from exc
        raise ConvoyError("SESSION_NOT_FOUND", msg) from exc

    # Target inference (§4.1.1)
    if target is None:
        target = _infer_target(proof_state)
        if target is None:
            raise ConvoyError(
                "TARGET_NOT_FOUND",
                "No target specified and no recent destruct error found.",
            )

    # Dependency scanning (§4.1.2–4.1.5)
    scanner = DependencyScanner()
    report = await scanner.scan(session_id, target, session_manager, proof_state)

    # Technique selection (§4.2)
    selector = TechniqueSelector()
    recommendation = await selector.select(
        report, axiom_tolerance, session_id, session_manager
    )

    # Boilerplate generation (§4.3)
    generated_code = None
    if generate_code:
        generator = BoilerplateGenerator()
        generated_code = await generator.generate(
            report, recommendation, session_id, session_manager
        )

    return DestructDiagnosis(
        dependency_report=report,
        recommendation=recommendation,
        generated_code=generated_code,
    )


def _infer_target(proof_state: dict) -> str | None:
    """Infer the destruct target from error messages in the proof state."""
    messages = proof_state.get("messages", [])
    for msg in messages:
        # "Abstracting over the terms `n` and `v` leads to ..."
        match = re.search(
            r"Abstracting over the terms?\s+`([^`]+)`\s+and\s+`([^`]+)`",
            msg,
        )
        if match:
            # The second term is typically the one being destructed
            return match.group(2)
        # Simpler pattern
        match = re.search(r"Abstracting over.*`([^`]+)`.*ill-typed", msg)
        if match:
            return match.group(1)
    return None
