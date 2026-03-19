"""Typeclass debugging functions for the Coq/Rocq MCP server.

Spec: specification/typeclass-debugging.md
Architecture: doc/architecture/typeclass-debugging.md

Entry points: list_instances, list_typeclasses, trace_resolution,
              explain_failure, detect_conflicts, explain_instance.
"""

from __future__ import annotations

import asyncio
import re
from typing import List, Optional

from Poule.session.errors import BACKEND_CRASHED, SessionError
from Poule.typeclass.parser import TraceParser
from Poule.typeclass.types import (
    FailureExplanation,
    InstanceConflict,
    InstanceExplanation,
    ResolutionNode,
    ResolutionTrace,
    TypeclassInfo,
    TypeclassSummary,
)

# ---------------------------------------------------------------------------
# Constants (S10: Language-Specific Notes)
# ---------------------------------------------------------------------------

MAX_TYPECLASSES_FOR_INSTANCE_COUNT: int = 200
TYPECLASS_COMMAND_TIMEOUT_SECONDS: int = 5


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

class TypeclassError(Exception):
    """Structured error raised by the typeclass debugging component."""

    def __init__(self, code: str, message: str = "", raw_output: Optional[str] = None) -> None:
        self.code = code
        self.message = message
        self.raw_output = raw_output
        super().__init__(f"{code}: {message}" if message else code)


# ---------------------------------------------------------------------------
# 4.1 Instance Listing
# ---------------------------------------------------------------------------

async def list_instances(
    session_id: str,
    typeclass_name: str,
    session_manager,
) -> List[TypeclassInfo]:
    """List registered instances of a typeclass.

    REQUIRES: session_id references an active session. typeclass_name is non-empty.
    ENSURES: Returns a list of TypeclassInfo records (may be empty).
    MAINTAINS: Session proof state is unchanged.
    """
    if not typeclass_name:
        raise TypeclassError("INVALID_INPUT", "Typeclass name must be non-empty.")

    response = await session_manager.execute_vernacular(
        session_id, f"Print Instances {typeclass_name}."
    )

    # Check for error responses
    # Coq says "is not a typeclass", Rocq says "is not a declared type class"
    resp_lower = response.lower() if response else ""
    if resp_lower and (
        "is not a typeclass" in resp_lower
        or "is not a declared type class" in resp_lower
    ):
        raise TypeclassError(
            "NOT_A_TYPECLASS",
            f"`{typeclass_name}` is not a registered typeclass.",
        )
    if response and "not found" in response.lower() and "error" in response.lower():
        raise TypeclassError(
            "NOT_FOUND",
            f"Typeclass `{typeclass_name}` not found in the current environment.",
        )

    if not response or not response.strip():
        return []

    # Join continuation lines.  A new instance entry looks like
    # "instance_name : type_signature" where the name is an identifier
    # (letters, digits, dots, underscores, angle-bracket prefixes).
    # Continuation lines start with type-expression keywords like "forall".
    _ENTRY_RE = re.compile(r"^[A-Za-z0-9_.<> ]+\s*:")
    raw_lines = response.strip().split("\n")
    joined_lines: List[str] = []
    for raw_line in raw_lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if _ENTRY_RE.match(stripped) or not joined_lines:
            joined_lines.append(stripped)
        else:
            # Continuation of previous line
            joined_lines[-1] += " " + stripped

    results: List[TypeclassInfo] = []
    for line in joined_lines:
        info = _parse_instance_line(line, typeclass_name)
        if info is not None:
            results.append(info)

    return results


def _parse_instance_line(line: str, typeclass_name: str) -> Optional[TypeclassInfo]:
    """Parse a single instance line from Print Instances output.

    Expected format: "InstanceName : type signature"
    """
    # Strip REPL prompt prefix (e.g. "Rocq < ")
    line = re.sub(r"^Rocq\s*<\s*", "", line)
    # Strip REPL trailing pipe/number suffix (e.g. "| 10")
    line = re.sub(r"\s*\|\s*\d+\s*$", "", line)
    line = line.strip()
    if not line:
        return None

    # Split on first ':'
    parts = line.split(":", 1)
    if len(parts) < 2:
        return None

    instance_name = parts[0].strip()
    type_signature = parts[1].strip()

    if not instance_name:
        return None

    # Derive defining_module from the fully qualified name prefix
    name_parts = instance_name.rsplit(".", 1)
    if len(name_parts) > 1:
        defining_module = name_parts[0]
    else:
        # Infer a module name; use a generic prefix based on the typeclass
        defining_module = "Stdlib.Classes"

    return TypeclassInfo(
        instance_name=instance_name,
        typeclass_name=typeclass_name,
        type_signature=type_signature,
        defining_module=defining_module,
    )


async def list_typeclasses(
    session_id: str,
    session_manager,
) -> List[TypeclassSummary]:
    """List all registered typeclasses with instance counts.

    REQUIRES: session_id references an active session.
    ENSURES: Returns a list of TypeclassSummary records.
    MAINTAINS: Session proof state is unchanged.
    """
    response = await session_manager.execute_vernacular(
        session_id, "Print Typeclasses."
    )

    if not response or not response.strip():
        return []

    typeclass_names = [
        name.strip() for name in response.strip().split("\n") if name.strip()
    ]

    # If more than MAX_TYPECLASSES_FOR_INSTANCE_COUNT, omit follow-up calls
    if len(typeclass_names) > MAX_TYPECLASSES_FOR_INSTANCE_COUNT:
        return [
            TypeclassSummary(typeclass_name=name, instance_count=None)
            for name in typeclass_names
        ]

    # Issue follow-up Print Instances for each typeclass
    results: List[TypeclassSummary] = []
    for name in typeclass_names:
        instance_response = await session_manager.execute_vernacular(
            session_id, f"Print Instances {name}."
        )
        if not instance_response or not instance_response.strip():
            count = 0
        else:
            count = len([
                l for l in instance_response.strip().split("\n")
                if l.strip()
            ])
        results.append(TypeclassSummary(typeclass_name=name, instance_count=count))

    return results


# ---------------------------------------------------------------------------
# 4.2 Resolution Tracing
# ---------------------------------------------------------------------------

async def trace_resolution(
    session_id: str,
    session_manager,
) -> ResolutionTrace:
    """Trace typeclass resolution for the current goal.

    REQUIRES: session_id references an active proof session at a typeclass goal.
    ENSURES: Returns a ResolutionTrace.
    MAINTAINS: Debug mode is never left enabled. Proof state is unchanged.
    """
    # Enable debug output
    await session_manager.execute_vernacular(
        session_id, "Set Typeclasses Debug Verbosity 2."
    )

    debug_output = ""
    try:
        # Re-trigger resolution to capture debug output
        debug_output = await session_manager.execute_vernacular(
            session_id, "typeclasses eauto."
        )
    except SessionError as e:
        if e.code == BACKEND_CRASHED:
            # Cleanup impossible -- backend is dead
            raise
        # For other session errors, attempt cleanup then re-raise
        try:
            await session_manager.execute_vernacular(
                session_id, "Unset Typeclasses Debug."
            )
        except Exception:
            pass
        raise
    except asyncio.TimeoutError:
        # Attempt cleanup, then raise timeout error
        try:
            await session_manager.execute_vernacular(
                session_id, "Unset Typeclasses Debug."
            )
        except Exception:
            pass
        raise TypeclassError(
            "TIMEOUT",
            "Typeclass command timed out after 5 seconds. "
            "The typeclass hierarchy may be too large.",
        )
    except Exception:
        # Generic error: attempt cleanup
        try:
            await session_manager.execute_vernacular(
                session_id, "Unset Typeclasses Debug."
            )
        except Exception:
            pass
        raise
    else:
        # Normal path: disable debug output
        await session_manager.execute_vernacular(
            session_id, "Unset Typeclasses Debug."
        )

    # Check if there was any typeclass-related output
    if not debug_output or not debug_output.strip():
        raise TypeclassError(
            "NO_TYPECLASS_GOAL",
            "The current goal does not involve typeclass resolution.",
        )

    # Parse the debug output
    parser = TraceParser()
    try:
        root_nodes = parser.parse(debug_output)
    except Exception:
        # Parser raised — check whether the output even contains typeclass
        # resolution lines before classifying as a parse error.
        if "looking for" not in debug_output:
            raise TypeclassError(
                "NO_TYPECLASS_GOAL",
                "The current goal does not involve typeclass resolution.",
            )
        raise TypeclassError(
            "PARSE_ERROR",
            "Failed to parse typeclass debug output. Raw output is included in the response.",
            raw_output=debug_output,
        )

    if not root_nodes:
        # If parser returned no nodes, check whether this is because there
        # was no typeclass goal (no debug resolution lines at all) vs an
        # actual parse failure (debug lines present but unparseable).
        # Also treat "Proof search failed" with zero matches as no typeclass goal,
        # since typeclasses eauto was invoked on a non-typeclass goal.
        has_resolution_lines = "looking for" in debug_output and "trying" in debug_output
        if not has_resolution_lines:
            raise TypeclassError(
                "NO_TYPECLASS_GOAL",
                "The current goal does not involve typeclass resolution.",
            )
        raise TypeclassError(
            "PARSE_ERROR",
            "Failed to parse typeclass debug output. Raw output is included in the response.",
            raw_output=debug_output,
        )

    # Determine success and failure mode
    succeeded = any(_node_succeeded(n) for n in root_nodes)
    failure_mode = None
    if not succeeded:
        failure_mode = _classify_failure_mode(root_nodes)

    # Extract goal from root nodes
    goal = ""
    for node in root_nodes:
        if node.goal:
            goal = node.goal
            break

    return ResolutionTrace(
        goal=goal,
        root_nodes=root_nodes,
        succeeded=succeeded,
        failure_mode=failure_mode,
        raw_output=debug_output,
    )


def _node_succeeded(node: ResolutionNode) -> bool:
    """Check if a node (or its subtree) has a successful outcome."""
    if node.outcome == "success":
        return True
    return any(_node_succeeded(c) for c in node.children)


def _classify_failure_mode(nodes: List[ResolutionNode]) -> Optional[str]:
    """Classify the failure mode from root nodes."""
    if not nodes:
        return None

    for node in nodes:
        if _has_outcome_anywhere(node, "depth_exceeded"):
            return "depth_exceeded"

    all_unification = all(
        n.outcome in ("unification_failure", "subgoal_failure") for n in nodes
    )
    if all_unification and nodes:
        return "unification"

    return "no_instance"


def _has_outcome_anywhere(node: ResolutionNode, outcome: str) -> bool:
    """Check if any node in the tree has the given outcome."""
    if node.outcome == outcome:
        return True
    return any(_has_outcome_anywhere(c, outcome) for c in node.children)


# ---------------------------------------------------------------------------
# 4.4 Failure Explanation
# ---------------------------------------------------------------------------

def explain_failure(trace: ResolutionTrace) -> FailureExplanation:
    """Classify and explain a resolution failure.

    REQUIRES: trace is a ResolutionTrace (typically with succeeded=False).
    ENSURES: Returns a FailureExplanation with one of the four failure modes.
    """
    # Determine failure mode from the trace
    failure_mode = trace.failure_mode

    # No-instance failure: failure_mode explicitly "no_instance",
    # OR root_nodes is empty and the goal is parseable (has typeclass + args)
    goal_parts = trace.goal.strip().split(None, 1)
    goal_is_parseable = len(goal_parts) >= 2
    if failure_mode == "no_instance" or (
        not trace.root_nodes
        and failure_mode not in ("unification", "depth_exceeded")
        and goal_is_parseable
    ):
        return _explain_no_instance(trace)

    # Depth exceeded
    if failure_mode == "depth_exceeded":
        return _explain_depth_exceeded(trace)

    # Unification failure
    if failure_mode == "unification":
        return _explain_unification(trace)

    # Unclassified fallback
    return FailureExplanation(
        failure_mode="unclassified",
        raw_output=trace.raw_output or "No trace data available.",
    )


def _extract_typeclass_from_goal(goal: str) -> str:
    """Extract the typeclass name from a goal string like 'Show (list (list nat))'."""
    parts = goal.strip().split(None, 1)
    if parts:
        return parts[0]
    return goal


def _extract_type_arguments(goal: str) -> List[str]:
    """Extract type arguments from a goal string.

    Strips outer parentheses from the argument if present, so that
    'Show (list (list nat))' yields ['list (list nat)'] not ['(list (list nat))'].
    """
    parts = goal.strip().split(None, 1)
    if len(parts) > 1:
        arg = parts[1].strip()
        # Strip a single layer of outer parentheses
        if arg.startswith("(") and arg.endswith(")"):
            inner = arg[1:-1].strip()
            return [inner]
        return [arg]
    return []


def _extract_goal_context(trace: ResolutionTrace) -> List[str]:
    """Extract goal context (hypotheses) from raw output."""
    context: List[str] = []
    if trace.raw_output:
        for line in trace.raw_output.strip().split("\n"):
            line = line.strip()
            if line and ":" in line and not line.startswith("Error"):
                context.append(line)
    return context if context else []


def _explain_no_instance(trace: ResolutionTrace) -> FailureExplanation:
    """Explain a no-instance failure."""
    typeclass = _extract_typeclass_from_goal(trace.goal)
    type_arguments = _extract_type_arguments(trace.goal)
    goal_context = _extract_goal_context(trace)

    return FailureExplanation(
        failure_mode="no_instance",
        typeclass=typeclass,
        type_arguments=type_arguments,
        goal_context=goal_context,
    )


def _explain_unification(trace: ResolutionTrace) -> FailureExplanation:
    """Explain a unification failure, identifying the closest match."""
    best_instance: Optional[str] = None
    best_count: int = -1
    best_expected: Optional[str] = None
    best_actual: Optional[str] = None

    for node in trace.root_nodes:
        if node.outcome in ("unification_failure", "subgoal_failure"):
            count = _parse_unification_count(node.failure_detail)
            expected, actual = _parse_mismatch(node.failure_detail)
            if count > best_count:
                best_count = count
                best_instance = node.instance_name
                best_expected = expected
                best_actual = actual

    # If we couldn't parse counts, just pick the first one
    if best_instance is None and trace.root_nodes:
        first = trace.root_nodes[0]
        best_instance = first.instance_name
        best_count = 0
        best_expected, best_actual = _parse_mismatch(first.failure_detail)

    return FailureExplanation(
        failure_mode="unification",
        closest_instance=best_instance,
        successful_unifications=max(best_count, 0),
        mismatch_expected=best_expected,
        mismatch_actual=best_actual,
    )


def _parse_unification_count(detail: Optional[str]) -> int:
    """Parse 'unified N of M args' from failure detail."""
    if not detail:
        return 0
    m = re.search(r"unified\s+(\d+)\s+of\s+\d+", detail)
    if m:
        return int(m.group(1))
    return 0


def _parse_mismatch(detail: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Parse 'expected X, got Y' from failure detail."""
    if not detail:
        return None, None
    m = re.search(r"expected\s+(\S+),\s*got\s+(\S+)", detail)
    if m:
        return m.group(1).rstrip(","), m.group(2).rstrip(",")
    return None, None


def _explain_depth_exceeded(trace: ResolutionTrace) -> FailureExplanation:
    """Explain a depth-exceeded failure, detecting cycles."""
    # Extract resolution path from root to depth-limit node
    path: List[str] = []
    if trace.root_nodes:
        _collect_path(trace.root_nodes[0], path)

    # Detect cycles: look for repeated typeclass names
    typeclass_names = []
    for goal_str in path:
        tc = _extract_typeclass_from_goal(goal_str)
        typeclass_names.append(tc)

    # Find cycle: typeclasses that appear more than once
    seen: dict[str, int] = {}
    cycle_classes: List[str] = []
    for tc in typeclass_names:
        if tc in seen:
            if tc not in cycle_classes:
                cycle_classes.append(tc)
        else:
            seen[tc] = 1

    cycle_detected = len(cycle_classes) > 0

    # Determine max depth
    max_depth = len(path) - 1 if path else 0

    return FailureExplanation(
        failure_mode="depth_exceeded",
        resolution_path=path,
        cycle_detected=cycle_detected,
        cycle_typeclasses=cycle_classes,
        max_depth_reached=max_depth,
    )


def _collect_path(node: ResolutionNode, path: List[str]) -> None:
    """Collect the resolution path from a node down to the deepest node."""
    goal_str = node.goal if node.goal else node.instance_name
    if goal_str:
        path.append(goal_str)
    if node.children:
        # Follow the first child (deepest path)
        _collect_path(node.children[0], path)


# ---------------------------------------------------------------------------
# 4.5 Conflict Detection
# ---------------------------------------------------------------------------

def detect_conflicts(trace: ResolutionTrace) -> List[InstanceConflict]:
    """Detect conflicting instances in a resolution trace.

    REQUIRES: trace is a ResolutionTrace.
    ENSURES: Returns a list of InstanceConflict records. Empty if <= 1 success.
    """
    successful_nodes = [
        n for n in trace.root_nodes if n.outcome == "success"
    ]

    if len(successful_nodes) <= 1:
        return []

    matching_names = [n.instance_name for n in successful_nodes]
    # The first successful node is the selected one (declaration order)
    selected = matching_names[0]

    return [
        InstanceConflict(
            goal=trace.goal,
            matching_instances=matching_names,
            selected_instance=selected,
            selection_basis="declaration_order",
        )
    ]


# ---------------------------------------------------------------------------
# 4.5 Instance Explanation
# ---------------------------------------------------------------------------

def explain_instance(
    trace: ResolutionTrace,
    instance_name: str,
) -> InstanceExplanation:
    """Explain a specific instance's role in resolution.

    REQUIRES: trace is a ResolutionTrace. instance_name is non-empty.
    ENSURES: Returns an InstanceExplanation with the instance's status.
    """
    if not instance_name:
        raise TypeclassError("INVALID_INPUT", "Instance name must be non-empty.")

    # Search for the instance in the trace
    found_node = _find_instance_node(trace.root_nodes, instance_name)

    if found_node is None:
        return InstanceExplanation(
            instance_name=instance_name,
            status="not_considered",
            not_considered_reason=(
                f"{instance_name} was not considered a candidate for goal '{trace.goal}'."
            ),
        )

    if found_node.outcome == "success":
        # Check if it was selected or overridden
        successful_nodes = [
            n for n in trace.root_nodes if n.outcome == "success"
        ]
        if len(successful_nodes) > 1:
            # Multiple successes: first one is selected, others are overridden
            first_success = successful_nodes[0]
            if found_node.instance_name != first_success.instance_name:
                return InstanceExplanation(
                    instance_name=instance_name,
                    status="succeeded_overridden",
                    overridden_by=first_success.instance_name,
                )
            else:
                # This is the selected one; the others are overridden
                # But from the perspective of this instance, it was overridden
                # by the last successful one (which Coq actually selects)
                last_success = successful_nodes[-1]
                if found_node.instance_name != last_success.instance_name:
                    return InstanceExplanation(
                        instance_name=instance_name,
                        status="succeeded_overridden",
                        overridden_by=last_success.instance_name,
                    )
        return InstanceExplanation(
            instance_name=instance_name,
            status="selected",
        )

    # Failed
    return InstanceExplanation(
        instance_name=instance_name,
        status="failed",
        failure_reason=found_node.failure_detail or found_node.outcome,
    )


def _find_instance_node(
    nodes: List[ResolutionNode],
    instance_name: str,
) -> Optional[ResolutionNode]:
    """Find a node matching the given instance name in the tree."""
    for node in nodes:
        if node.instance_name == instance_name:
            return node
        found = _find_instance_node(node.children, instance_name)
        if found is not None:
            return found
    return None
