from __future__ import annotations

from typing import Optional

from Poule.auto_trace.types import (
    AutoSearchNode,
    AutoSearchTree,
    HintClassification,
    RejectionReason,
)


def _collect_trace_hints(
    node: AutoSearchNode,
    result: dict[str, tuple[str, AutoSearchNode]],
) -> None:
    """Collect all hint names from the trace tree with their outcome and node."""
    if node.hint_name is not None:
        # If same hint appears multiple times, keep the "success" one if any
        existing = result.get(node.hint_name)
        if existing is None or (existing[0] == "failure" and node.outcome == "success"):
            result[node.hint_name] = (node.outcome, node)
    for child in node.children:
        _collect_trace_hints(child, result)


def classify_hints(
    tree: AutoSearchTree,
    databases: list,  # list[HintDatabase]
    state,  # ProofState
) -> list[HintClassification]:
    # Build map of hint_name -> (outcome, node) from trace
    trace_hints: dict[str, tuple[str, AutoSearchNode]] = {}
    for root in tree.root_nodes:
        _collect_trace_hints(root, trace_hints)

    classifications: list[HintClassification] = []

    # Classify hints from databases
    for db in databases:
        for entry in db.entries:
            name = entry.name
            if name is None:
                continue

            if name in trace_hints:
                outcome, node = trace_hints[name]
                if outcome == "success":
                    classification = "matched"
                    rejection_reason = None
                else:
                    classification = "attempted_but_rejected"
                    rejection_reason = _detect_rejection_reason(node, entry)

                classifications.append(HintClassification(
                    hint_name=name,
                    hint_type=entry.hint_type,
                    database=db.name,
                    classification=classification,
                    rejection_reason=rejection_reason,
                    trace_node=node,
                ))
            else:
                classifications.append(HintClassification(
                    hint_name=name,
                    hint_type=entry.hint_type,
                    database=db.name,
                    classification="not_considered",
                    rejection_reason=None,
                    trace_node=None,
                ))

    # Classify hypotheses from proof state
    if state and hasattr(state, "goals") and state.goals:
        goal = state.goals[0] if state.focused_goal_index is not None else None
        if goal is None and state.goals:
            goal = state.goals[0]
        if goal and hasattr(goal, "hypotheses"):
            for hyp in goal.hypotheses:
                hyp_name = hyp.name
                if hyp_name in trace_hints:
                    outcome, node = trace_hints[hyp_name]
                    classifications.append(HintClassification(
                        hint_name=hyp_name,
                        hint_type="hypothesis",
                        database=None,
                        classification="matched" if outcome == "success" else "attempted_but_rejected",
                        rejection_reason=None,
                        trace_node=node,
                    ))
                else:
                    classifications.append(HintClassification(
                        hint_name=hyp_name,
                        hint_type="hypothesis",
                        database=None,
                        classification="not_considered",
                        rejection_reason=None,
                        trace_node=None,
                    ))

    return classifications


def _detect_rejection_reason(
    node: AutoSearchNode,
    entry,  # HintEntry
) -> Optional[RejectionReason]:
    """Detect evar_rejected for leaf failures of constructor/resolve hints."""
    # Leaf failure with no children — potential evar rejection
    if not node.children and node.outcome == "failure":
        # Heuristic: constructors hints (like ex_intro) commonly have
        # universally quantified variables not in the conclusion
        if entry.hint_type in ("constructors", "resolve"):
            return RejectionReason(
                reason="evar_rejected",
                detail=f"{node.hint_name} has uninstantiated universals",
                fix_suggestion="Switch to 'eauto' or 'eauto with core'",
            )
    return None
