from __future__ import annotations

import re
from typing import Optional

from Poule.auto_trace.classifier import classify_hints
from Poule.auto_trace.diagnoser import diagnose_failures
from Poule.auto_trace.errors import AutoTraceError
from Poule.auto_trace.parser import parse_trace
from Poule.auto_trace.types import (
    AutoDiagnosis,
    DatabaseConfig,
    DivergencePoint,
    RawTraceCapture,
    VariantComparison,
    VariantResult,
)

_AUTO_FAMILY_RE = re.compile(
    r"^(auto|eauto)(\s+\d+)?(\s+with\s+\w+(\s+\w+)*)?$|^typeclasses\s+eauto$"
)

# Well-known Coq hint databases to probe when searching for a specific hint
_WELL_KNOWN_DATABASES = [
    "core", "arith", "bool", "datatypes", "zarith", "real",
    "typeclass_instances", "rewrite", "nocore",
]


def _validate_tactic(tactic: str) -> None:
    if not tactic:
        raise AutoTraceError("INVALID_ARGUMENT", "Tactic must not be empty.")
    if not _AUTO_FAMILY_RE.match(tactic):
        raise AutoTraceError(
            "INVALID_ARGUMENT",
            f'"{tactic}" is not an auto-family tactic. '
            "Supported: auto, eauto, auto with <db>, eauto with <db>, "
            "auto <N>, eauto <N>, typeclasses eauto.",
        )


def _parse_consulted_databases(tactic: str) -> list[str]:
    """Extract database names from a tactic string."""
    dbs = ["core"]
    m = re.search(r"with\s+(.+)$", tactic)
    if m:
        extra = m.group(1).strip().split()
        for db_name in extra:
            if db_name not in dbs:
                dbs.append(db_name)
    return dbs


async def capture_trace(
    session_id: str,
    tactic: str,
    session_manager,
) -> RawTraceCapture:
    # Get current proof state to extract goal
    state = await session_manager.observe_state(session_id)
    goal_text = ""
    if state.goals:
        goal_text = state.goals[0].type

    # Set debug flag
    await session_manager.execute_vernacular(session_id, 'Set Debug "auto".')

    try:
        # Submit tactic wrapped in try(...)
        result = await session_manager.submit_tactic(
            session_id, f"try ({tactic})"
        )

        messages = result.messages if hasattr(result, "messages") else []
        new_state = result.proof_state if hasattr(result, "proof_state") else None

        # Determine outcome by checking if goal changed
        new_goal = ""
        if new_state and hasattr(new_state, "goals") and new_state.goals:
            new_goal = new_state.goals[0].type

        if new_goal != goal_text:
            outcome = "succeeded"
        else:
            outcome = "failed"

        semantic_divergence_caveat = None

        # Fallback: if no messages captured, retry with debug auto
        if not messages:
            fallback_result = await session_manager.submit_tactic(
                session_id, "try (debug auto)"
            )
            messages = (
                fallback_result.messages
                if hasattr(fallback_result, "messages")
                else []
            )

            # Check for Hint Extern in fallback messages
            if messages and any("Extern" in msg for msg in messages):
                semantic_divergence_caveat = (
                    "Fallback to 'debug auto' was used. Hint Extern entries "
                    "were detected in the trace; debug auto wraps Hint Extern "
                    "with 'once', which may produce different behavior than auto."
                )

            fallback_state = (
                fallback_result.proof_state
                if hasattr(fallback_result, "proof_state")
                else None
            )
            fallback_goal = ""
            if (
                fallback_state
                and hasattr(fallback_state, "goals")
                and fallback_state.goals
            ):
                fallback_goal = fallback_state.goals[0].type
            if fallback_goal != goal_text:
                await session_manager.step_backward(session_id)

        # Step backward if the original tactic succeeded
        if outcome == "succeeded":
            await session_manager.step_backward(session_id)

        return RawTraceCapture(
            messages=messages,
            outcome=outcome,
            goal=goal_text,
            tactic=tactic,
            semantic_divergence_caveat=semantic_divergence_caveat,
        )
    finally:
        # Always unset debug flag
        await session_manager.execute_vernacular(
            session_id, 'Unset Debug "auto".'
        )


async def compare_variants(
    session_id: str,
    session_manager,
    hint_inspect=None,
) -> VariantComparison:
    variant_tactics = ["auto", "eauto", "typeclasses eauto"]
    variants: list[VariantResult] = []

    for tactic in variant_tactics:
        trace_capture = await capture_trace(session_id, tactic, session_manager)
        tree = parse_trace(trace_capture.messages)

        if tactic == "typeclasses eauto":
            dbs_consulted = ["typeclass_instances"]
        else:
            dbs_consulted = ["core"]

        winning_path = None
        if trace_capture.outcome == "succeeded":
            from Poule.auto_trace.diagnoser import _extract_winning_path

            winning_path = _extract_winning_path(tree)

        variants.append(
            VariantResult(
                tactic=tactic,
                outcome=trace_capture.outcome,
                databases_consulted=dbs_consulted,
                winning_path=winning_path,
            )
        )

    divergence_points: list[DivergencePoint] = []
    return VariantComparison(
        variants=variants,
        divergence_points=divergence_points,
    )


async def _retrieve_databases(
    db_names: list[str],
    hint_inspect,
    session_id: str,
) -> tuple[list, list[DatabaseConfig]]:
    """Retrieve hint databases, returning (databases, configs)."""
    all_databases = []
    db_configs: list[DatabaseConfig] = []
    for db_name in db_names:
        try:
            db = await hint_inspect(db_name, session_id=session_id)
            all_databases.append(db)
            db_configs.append(
                DatabaseConfig(
                    name=db.name,
                    transparency="transparent",
                    hint_count=db.total_entries,
                )
            )
        except Exception:
            db_configs.append(
                DatabaseConfig(
                    name=db_name,
                    transparency="transparent",
                    hint_count=0,
                )
            )
    return all_databases, db_configs


def _hint_found_in(name: str, databases: list) -> bool:
    for db in databases:
        for entry in db.entries:
            if entry.name == name:
                return True
    return False


async def diagnose_auto(
    session_id: str,
    tactic: str = "auto",
    session_manager=None,
    hint_inspect=None,
    hint_name: Optional[str] = None,
    compare_variants_flag: bool = False,
    **kwargs,
) -> AutoDiagnosis:
    if "compare_variants" in kwargs:
        compare_variants_flag = kwargs["compare_variants"]

    _validate_tactic(tactic)

    if hint_name is not None and hint_name == "":
        raise AutoTraceError("INVALID_ARGUMENT", "Hint name must not be empty.")

    # Capture trace
    trace_capture = await capture_trace(session_id, tactic, session_manager)

    # Parse trace
    tree = parse_trace(trace_capture.messages)

    # Determine consulted databases
    db_names = _parse_consulted_databases(tactic)

    # Retrieve consulted databases
    all_databases, db_configs = await _retrieve_databases(
        db_names, hint_inspect, session_id
    )

    # For focused hint queries: if the hint is not in consulted databases,
    # probe additional well-known databases to enable wrong_database diagnosis
    if hint_name is not None and not _hint_found_in(hint_name, all_databases):
        extra_db_names = [
            n for n in _WELL_KNOWN_DATABASES if n not in db_names
        ]
        extra_dbs, _ = await _retrieve_databases(
            extra_db_names, hint_inspect, session_id
        )
        # Check if hint found in any extra database
        if _hint_found_in(hint_name, extra_dbs):
            all_databases.extend(extra_dbs)
        else:
            raise AutoTraceError(
                "NOT_FOUND",
                f'Hint "{hint_name}" not found in any consulted database.',
            )

    # Get proof state for classification
    state = await session_manager.observe_state(session_id)

    # Classify hints
    classifications = classify_hints(tree, all_databases, state)

    # Diagnose failures
    diagnosis = diagnose_failures(
        classifications, tree, db_names, trace_capture.goal
    )

    # Override tactic and outcome from the capture
    diagnosis.tactic = tactic
    diagnosis.outcome = trace_capture.outcome
    diagnosis.databases_consulted = db_configs
    diagnosis.semantic_divergence_caveat = trace_capture.semantic_divergence_caveat

    # Filter to specific hint if requested
    if hint_name is not None:
        diagnosis.classifications = [
            c for c in diagnosis.classifications if c.hint_name == hint_name
        ]

    # Variant comparison
    if compare_variants_flag:
        diagnosis.variant_comparison = await compare_variants(
            session_id, session_manager, hint_inspect
        )

    return diagnosis
