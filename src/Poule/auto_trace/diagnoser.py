from __future__ import annotations

from typing import Optional

from Poule.auto_trace.types import (
    AutoDiagnosis,
    AutoSearchNode,
    AutoSearchTree,
    HintClassification,
    RejectionReason,
)


def diagnose_failures(
    classifications: list[HintClassification],
    tree: AutoSearchTree,
    databases_consulted: list[str],
    goal: str,
) -> AutoDiagnosis:
    diagnosed: list[HintClassification] = []
    min_depth_required: Optional[int] = None

    for c in classifications:
        if c.classification == "matched":
            diagnosed.append(c)
            continue

        if c.classification == "not_considered":
            reason = _diagnose_not_considered(c, databases_consulted)
            diagnosed.append(HintClassification(
                hint_name=c.hint_name,
                hint_type=c.hint_type,
                database=c.database,
                classification=c.classification,
                rejection_reason=reason,
                trace_node=c.trace_node,
            ))
            continue

        # attempted_but_rejected
        reason = _diagnose_attempted(c, tree)
        if reason and reason.reason == "depth_exhausted" and tree.depth_limit_reached:
            depth = tree.max_depth - tree.min_leaf_depth + 1
            if min_depth_required is None or depth > min_depth_required:
                min_depth_required = depth

        diagnosed.append(HintClassification(
            hint_name=c.hint_name,
            hint_type=c.hint_type,
            database=c.database,
            classification=c.classification,
            rejection_reason=reason,
            trace_node=c.trace_node,
        ))

    # Extract winning path
    winning_path = _extract_winning_path(tree)

    return AutoDiagnosis(
        tactic="",
        outcome="succeeded" if winning_path else "failed",
        goal=goal,
        classifications=diagnosed,
        winning_path=winning_path,
        min_depth_required=min_depth_required,
    )


def _diagnose_not_considered(
    c: HintClassification,
    databases_consulted: list[str],
) -> RejectionReason:
    if c.database and c.database not in databases_consulted:
        return RejectionReason(
            reason="wrong_database",
            detail=f"{c.hint_name} is registered in database '{c.database}', "
                   f"but only {databases_consulted} were consulted",
            fix_suggestion=f"Add 'with {c.database}' to the tactic invocation",
        )
    return RejectionReason(
        reason="head_symbol_mismatch",
        detail=f"{c.hint_name} was not considered — head symbol may not match the goal",
        fix_suggestion=f"Unfold the goal head or use 'apply {c.hint_name}' directly",
    )


def _diagnose_attempted(
    c: HintClassification,
    tree: AutoSearchTree,
) -> RejectionReason:
    # If classifier already assigned evar_rejected, refine the fix suggestion
    if c.rejection_reason and c.rejection_reason.reason == "evar_rejected":
        return RejectionReason(
            reason="evar_rejected",
            detail=c.rejection_reason.detail,
            fix_suggestion="Switch to 'eauto' or 'eauto with core'",
        )

    # Check depth exhaustion
    if (
        tree.depth_limit_reached
        and c.trace_node
        and c.trace_node.remaining_depth == 1
    ):
        min_depth = tree.max_depth - tree.min_leaf_depth + 1
        return RejectionReason(
            reason="depth_exhausted",
            detail=f"Search reached maximum depth at {c.hint_name}",
            fix_suggestion=f"Use 'auto {min_depth}' or 'eauto {min_depth}'",
        )

    # Default: unification failure
    return RejectionReason(
        reason="unification_failure",
        detail=f"Unification failed when applying {c.hint_name}",
        fix_suggestion=f"Use explicit 'apply {c.hint_name}' with instantiation, "
                       "or check argument types",
    )


def _extract_winning_path(tree: AutoSearchTree) -> Optional[list[AutoSearchNode]]:
    """Extract root-to-leaf path where every node succeeded."""
    for root in tree.root_nodes:
        path = _find_success_path(root)
        if path:
            return path
    return None


def _find_success_path(node: AutoSearchNode) -> Optional[list[AutoSearchNode]]:
    if node.outcome != "success":
        return None
    if not node.children:
        return [node]
    for child in node.children:
        child_path = _find_success_path(child)
        if child_path:
            return [node] + child_path
    # Node succeeded but no child path succeeded — still report this node
    return [node]
