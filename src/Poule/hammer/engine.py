"""Hammer Automation Engine.

Executes CoqHammer tactics via the Proof Session Manager.

Spec: specification/hammer-automation.md sections 4.2, 4.3, 4.6.
"""

from __future__ import annotations

import time
from typing import Optional

from Poule.hammer.interpret import interpret_result
from Poule.hammer.tactic import build_tactic
from Poule.hammer.types import HammerResult, StrategyDiagnostic
from Poule.session.errors import SessionError, BACKEND_CRASHED, SESSION_NOT_FOUND, TACTIC_ERROR

# Default per-strategy timeouts (spec section 4.4)
_DEFAULT_TIMEOUTS = {
    "hammer": 30,
    "sauto": 10,
    "qauto": 5,
}

_VALID_STRATEGIES = {"hammer", "sauto", "qauto"}

# Fixed strategy order for multi-strategy fallback (spec section 4.3)
_STRATEGY_ORDER = ["hammer", "sauto", "qauto"]



def _wrap_timeout(strategy: str, tactic: str, timeout: float) -> tuple[Optional[str], str]:
    """Wrap a tactic with appropriate Coq-level timeout directive.

    Returns (pre_command, wrapped_tactic) where pre_command is a separate
    command to issue before the tactic (for hammer), or None (for sauto/qauto
    where the timeout is inline).

    Spec section 4.6.
    """
    t = int(timeout)
    if strategy == "hammer":
        return (f"Set Hammer Timeout {t}.", tactic)
    else:
        # sauto/qauto: "Timeout {t} {tactic}"
        return (None, f"Timeout {t} {tactic}")


async def execute_hammer(
    session_manager,
    session_id: str,
    strategy: str,
    timeout: float,
    hints: list[str],
    options: dict,
) -> HammerResult:
    """Execute a single hammer strategy.

    REQUIRES: session_id references an active proof session with at least one
              open goal. strategy is one of hammer, sauto, qauto. timeout is
              a positive number (seconds).
    ENSURES: Returns a HammerResult reflecting the outcome.
    MAINTAINS: On success, exactly one tactic step added. On failure, session
               state unchanged.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"Invalid strategy: {strategy!r}; must be one of {_VALID_STRATEGIES}")

    if timeout <= 0:
        raise ValueError(f"Timeout must be positive, got {timeout}")

    # Observe initial proof state -- propagates SESSION_NOT_FOUND, SESSION_EXPIRED
    initial_state = await session_manager.observe_proof_state(session_id)

    # Check for no active goal
    if initial_state.is_complete:
        raise SessionError(TACTIC_ERROR, "No open goals; proof is already complete")

    # Build tactic string (may raise ParseError)
    tactic = build_tactic(strategy, hints, options)

    # Wrap with timeout directive
    pre_command, wrapped_tactic = _wrap_timeout(strategy, tactic, timeout)

    start = time.monotonic()

    coq_output = ""
    result_state = initial_state

    try:
        # Issue pre-command if needed (e.g., "Set Hammer Timeout 30.")
        if pre_command is not None:
            try:
                raw_pre = await session_manager.submit_tactic(
                    session_id, pre_command,
                )
            except SessionError as exc:
                if exc.code in (SESSION_NOT_FOUND, BACKEND_CRASHED):
                    raise
                # Pre-command may fail (e.g., petanque doesn't support Set
                # commands in proof mode); continue with the main tactic.

        # Submit the actual tactic
        raw = await session_manager.submit_tactic(
            session_id, wrapped_tactic,
        )

        # Handle both (str, ProofState) tuple (mocks) and bare ProofState
        # (real SessionManager).
        if isinstance(raw, tuple):
            coq_output, result_state = raw
        else:
            result_state = raw
            coq_output = "No more subgoals." if result_state.is_complete else ""

    except SessionError as exc:
        # Propagate SESSION_NOT_FOUND and BACKEND_CRASHED immediately
        if exc.code in (SESSION_NOT_FOUND, BACKEND_CRASHED):
            raise
        # TACTIC_ERROR or other: use the error message as coq_output
        # so the Result Interpreter can classify it properly.
        coq_output = exc.message
        result_state = initial_state

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Interpret the result
    interpreted = interpret_result(coq_output, result_state)

    if interpreted.classification == "success":
        return HammerResult(
            status="success",
            proof_script=f"{tactic}.",
            atp_proof=_extract_atp_proof(coq_output) if strategy == "hammer" else None,
            strategy_used=strategy,
            state=result_state,
            diagnostics=[],
            wall_time_ms=elapsed_ms,
        )
    else:
        return HammerResult(
            status="failure",
            proof_script=None,
            atp_proof=None,
            strategy_used=None,
            state=result_state,
            diagnostics=[
                StrategyDiagnostic(
                    strategy=strategy,
                    failure_reason=interpreted.classification,
                    detail=interpreted.detail or coq_output,
                    partial_progress=interpreted.partial_progress,
                    wall_time_ms=elapsed_ms,
                    timeout_used=timeout,
                )
            ],
            wall_time_ms=elapsed_ms,
        )


def _extract_atp_proof(coq_output: str) -> Optional[str]:
    """Extract ATP proof text from Coq output, if present."""
    for line in coq_output.split("\n"):
        stripped = line.strip()
        if stripped and stripped != "No more subgoals.":
            return stripped
    return None


async def execute_auto_hammer(
    session_manager,
    session_id: str,
    timeout: float = 60,
    hints: list[str] | None = None,
    options: dict | None = None,
) -> HammerResult:
    """Execute multi-strategy fallback (auto_hammer).

    Executes strategies in fixed order [hammer, sauto, qauto], stopping on
    first success or budget exhaustion.

    REQUIRES: session_id references an active proof session with at least one
              open goal. timeout is total budget in seconds (default 60).
    ENSURES: On first success, returns immediately with diagnostics from prior
             failed attempts. When all fail or budget exhausted, returns failure
             with all diagnostics.
    MAINTAINS: At most one successful tactic step added to the session.
    """
    if hints is None:
        hints = []
    if options is None:
        options = {}

    deadline = time.monotonic() + timeout
    diagnostics: list[StrategyDiagnostic] = []
    last_state = None

    for strategy in _STRATEGY_ORDER:
        now = time.monotonic()
        budget_remaining = deadline - now

        if budget_remaining <= 0:
            break

        default_timeout = _DEFAULT_TIMEOUTS[strategy]
        per_strategy_timeout = min(budget_remaining, default_timeout)

        result = await execute_hammer(
            session_manager=session_manager,
            session_id=session_id,
            strategy=strategy,
            timeout=per_strategy_timeout,
            hints=hints,
            options=options,
        )

        last_state = result.state

        if result.status == "success":
            # Prepend diagnostics from prior failed attempts
            result.diagnostics = diagnostics + result.diagnostics
            # Recompute total wall_time_ms
            total_wall = sum(d.wall_time_ms for d in diagnostics) + result.wall_time_ms
            result.wall_time_ms = total_wall
            return result

        # Failure: collect diagnostics and continue
        diagnostics.extend(result.diagnostics)

    # All strategies failed or budget exhausted
    total_wall = sum(d.wall_time_ms for d in diagnostics)
    return HammerResult(
        status="failure",
        proof_script=None,
        atp_proof=None,
        strategy_used=None,
        state=last_state if last_state is not None else (await session_manager.observe_proof_state(session_id)),
        diagnostics=diagnostics,
        wall_time_ms=total_wall,
    )
