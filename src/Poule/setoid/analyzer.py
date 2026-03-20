"""Top-level analyzer for the setoid rewriting assistant."""

from __future__ import annotations

from typing import Any

from .advisor import ProofAdvisor
from .checker import InstanceChecker
from .errors import SetoidError
from .generator import SignatureGenerator
from .parser import ErrorParser
from .types import (
    InstanceCheckResult,
    ParsedError,
    RewriteDiagnosis,
)


async def diagnose_rewrite(
    session_id: str,
    error_message: str | None = None,
    mode: str = "diagnose",
    target_function: str | None = None,
    target_relation: str | None = None,
    session_manager: Any = None,
) -> RewriteDiagnosis:
    """Diagnose a setoid rewriting failure.

    See specification/setoid-rewriting-assistant.md §4.1.
    """
    if session_manager is None:
        raise SetoidError("SESSION_NOT_FOUND", "Rewrite diagnosis requires an active proof session.")

    # Get proof state
    try:
        proof_state = await session_manager.observe_proof_state(session_id)
    except Exception as exc:
        msg = str(exc)
        code = getattr(exc, "code", None)
        if code:
            raise SetoidError(code, getattr(exc, "message", msg)) from exc
        if "SESSION_NOT_FOUND" in msg:
            raise SetoidError("SESSION_NOT_FOUND", msg) from exc
        if "BACKEND_CRASHED" in msg:
            raise SetoidError("BACKEND_CRASHED", msg) from exc
        raise SetoidError("SESSION_NOT_FOUND", msg) from exc

    # Get error message
    if error_message is None:
        messages = proof_state.get("messages", []) if isinstance(proof_state, dict) else []
        if not messages:
            raise SetoidError(
                "NO_ERROR_CONTEXT",
                "No error messages found in the session. Provide the error message explicitly.",
            )
        error_message = messages[-1]

    # Parse error
    goal = ""
    if isinstance(proof_state, dict):
        goal = proof_state.get("goal", "")

    parser = ErrorParser()
    parsed_error = parser.parse(error_message, goal)

    if parsed_error.error_class == "_unrecognized":
        raise SetoidError(
            "UNRECOGNIZED_ERROR",
            f"Could not parse the error message as a rewriting failure. Raw: {error_message}",
        )

    # Override function name if provided
    function_name = target_function or parsed_error.function_name

    # Extract relations from parsed error
    relation_names = _extract_relations(parsed_error, target_relation)

    # Check for binder_rewrite stdlib suggestion
    checker = InstanceChecker()

    if parsed_error.error_class == "binder_rewrite":
        # For binder rewrites, check if stdlib covers the binder
        instance_check = InstanceCheckResult(
            existing_instances=[],
            base_relation_registered=True,
            base_relation_class="Equivalence",
            stdlib_suggestion="Require Import Coq.Classes.Morphisms_Prop.",
        )
    else:
        # Normal instance checking
        instance_check = await checker.check(
            function_name, relation_names, session_id, session_manager
        )

    # Check base relation — if not registered, flag as root cause
    if (parsed_error.error_class == "missing_proper"
            and not instance_check.base_relation_registered
            and relation_names
            and any(r and r != "eq" for r in relation_names)):
        parsed_error = ParsedError(
            error_class="missing_equivalence",
            function_name=parsed_error.function_name,
            partial_signature=parsed_error.partial_signature,
            binder_type=parsed_error.binder_type,
            rewrite_target=parsed_error.rewrite_target,
            raw_error=parsed_error.raw_error,
        )

    # Generate signature if requested
    generated_signature = None
    proof_strategy = None

    if mode == "generate" and function_name:
        # Don't generate if base relation is missing
        if instance_check.base_relation_registered or parsed_error.error_class != "missing_equivalence":
            # Check if function type is retrievable
            try:
                func_type_output = await session_manager.execute_vernacular(
                    session_id, f"Check {function_name}"
                )
                if func_type_output and "Error" in func_type_output and "not found" in func_type_output:
                    raise SetoidError(
                        "TYPE_ERROR",
                        f"Could not retrieve the type of `{function_name}`. Ensure it is in scope.",
                    )
            except SetoidError:
                raise
            except Exception:
                raise SetoidError(
                    "TYPE_ERROR",
                    f"Could not retrieve the type of `{function_name}`. Ensure it is in scope.",
                )

            sig_gen = SignatureGenerator()
            generated_signature = await sig_gen.generate(
                function_name,
                parsed_error.partial_signature,
                target_relation,
                session_id,
                session_manager,
            )

            advisor = ProofAdvisor()
            proof_strategy = await advisor.advise(
                generated_signature, session_id, session_manager
            )

    # Build suggestion
    suggestion = _build_suggestion(parsed_error, instance_check, function_name)

    return RewriteDiagnosis(
        parsed_error=parsed_error,
        instance_check=instance_check,
        generated_signature=generated_signature,
        proof_strategy=proof_strategy,
        suggestion=suggestion,
    )


def _extract_relations(parsed_error: ParsedError, target_relation: str | None) -> list[str]:
    """Extract relation names from parsed error and target_relation."""
    relations: list[str] = []

    for slot in parsed_error.partial_signature:
        if slot.relation:
            relations.append(slot.relation)

    if target_relation and target_relation not in relations:
        relations.append(target_relation)

    return relations


def _build_suggestion(
    parsed_error: ParsedError,
    instance_check: InstanceCheckResult,
    function_name: str | None,
) -> str:
    """Build a plain-language suggestion string."""
    parts: list[str] = []

    if parsed_error.error_class == "binder_rewrite":
        parts.append(
            f"Use `setoid_rewrite` instead of `rewrite`. "
            f"The target is under a `{parsed_error.binder_type}`, which `rewrite` cannot enter."
        )
        if instance_check.stdlib_suggestion:
            parts.append(f" Import `Morphisms_Prop` for the required `Proper` instances.")

    elif parsed_error.error_class == "missing_proper":
        if function_name:
            parts.append(f"Function `{function_name}` needs a `Proper` instance.")
        if instance_check.existing_instances:
            parts.append(" An existing instance was found; ensure it is in scope.")
        else:
            parts.append(" No existing instance found.")
        if instance_check.stdlib_suggestion:
            parts.append(f" Try: {instance_check.stdlib_suggestion}")

    elif parsed_error.error_class == "missing_equivalence":
        relations = [s.relation for s in parsed_error.partial_signature if s.relation]
        rel_name = relations[0] if relations else "the relation"
        parts.append(
            f"Declare `Instance : Equivalence {rel_name}` before declaring Proper instances."
        )

    elif parsed_error.error_class == "pattern_not_found":
        parts.append("The rewrite target pattern was not found in the goal.")

    return "".join(parts)
