"""Debug output parser for Coq typeclass resolution traces.

Spec: specification/typeclass-debugging.md, section 4.3 (Debug Output Parsing).
"""

from __future__ import annotations

import re
from typing import List, Optional

from poule.typeclass.types import ResolutionNode


# Patterns for classifying debug output lines.
_GOAL_PATTERN = re.compile(
    r"^[\d.]+:\s*looking for\s+(.+)$"
)
_ATTEMPT_PATTERN = re.compile(
    r"^[\d.]+:\s*trying\s+(\S+)(.*)$"
)
_SUCCESS_PATTERN = re.compile(
    r"^[\d.]+:\s*(\S+)\s*--\s*success$"
)
_DEPTH_LIMIT_PATTERN = re.compile(
    r"^depth\s+limit\s+exceeded",
    re.IGNORECASE,
)


class TraceParser:
    """Stateful line-by-line parser that converts Coq typeclass debug output
    into a tree of ResolutionNode records.

    Uses an explicit stack for tree construction as required by the spec.
    """

    def parse(self, debug_output: str) -> List[ResolutionNode]:
        """Parse raw debug output into a list of root ResolutionNode records."""
        if not debug_output or not debug_output.strip():
            return []

        lines = debug_output.split("\n")
        indent_unit: Optional[int] = None
        # Stack entries: (depth, ResolutionNode)
        stack: List[tuple[int, ResolutionNode]] = []
        roots: List[ResolutionNode] = []

        for raw_line in lines:
            if not raw_line.strip():
                continue

            # Compute leading spaces
            stripped = raw_line.lstrip(" ")
            leading_spaces = len(raw_line) - len(stripped)
            content = stripped

            # Detect indentation unit from first indented line
            if leading_spaces > 0 and indent_unit is None:
                indent_unit = leading_spaces

            if indent_unit and indent_unit > 0:
                depth = leading_spaces // indent_unit
            else:
                depth = 0

            # Classify the line
            node = self._classify_line(content, depth)

            if node is not None:
                # Pop stack entries at same or deeper depth
                while stack and stack[-1][0] >= depth:
                    stack.pop()

                if stack:
                    # Attach as child of the top-of-stack node
                    parent_node = stack[-1][1]
                    parent_node.children.append(node)
                else:
                    roots.append(node)

                stack.append((depth, node))
            else:
                # Unrecognized line: check for depth-limit pattern
                if _DEPTH_LIMIT_PATTERN.match(content):
                    # Find enclosing node and set outcome
                    if stack:
                        enclosing = stack[-1][1]
                        enclosing.outcome = "depth_exceeded"
                        if enclosing.failure_detail:
                            enclosing.failure_detail += "\n" + content
                        else:
                            enclosing.failure_detail = content
                    else:
                        # No enclosing node; create a synthetic one
                        synth = ResolutionNode(
                            instance_name="",
                            goal="",
                            outcome="depth_exceeded",
                            failure_detail=content,
                            depth=depth,
                        )
                        roots.append(synth)
                else:
                    # Preserve as raw text in the enclosing node's failure_detail
                    if stack:
                        enclosing = stack[-1][1]
                        if enclosing.failure_detail:
                            enclosing.failure_detail += "\n" + content
                        else:
                            enclosing.failure_detail = content

        # Propagate success: if a node's children all succeeded, mark it success
        for root in roots:
            self._propagate_outcomes(root)

        return roots

    def _classify_line(self, content: str, depth: int) -> Optional[ResolutionNode]:
        """Classify a single line and return a ResolutionNode or None."""

        # Check for "trying X -- success" pattern (attempt + immediate success)
        m = _ATTEMPT_PATTERN.match(content)
        if m:
            instance_name = m.group(1)
            rest = m.group(2).strip()
            if "success" in rest:
                return ResolutionNode(
                    instance_name=instance_name,
                    goal="",
                    outcome="success",
                    depth=depth,
                )
            elif "failed" in rest:
                outcome = "unification_failure"
                if "subgoal" in rest.lower():
                    outcome = "subgoal_failure"
                return ResolutionNode(
                    instance_name=instance_name,
                    goal="",
                    outcome=outcome,
                    failure_detail=rest,
                    depth=depth,
                )
            else:
                # Attempt without immediate result; children will determine outcome
                return ResolutionNode(
                    instance_name=instance_name,
                    goal="",
                    outcome="success",  # tentative; may be updated
                    depth=depth,
                )

        # Check for "X -- success" (completion line for a previously started attempt)
        m = _SUCCESS_PATTERN.match(content)
        if m:
            # This is a completion marker; update the matching node on the stack
            # We return None and handle it specially
            return None

        # Check for goal pattern
        m = _GOAL_PATTERN.match(content)
        if m:
            goal_text = m.group(1).strip()
            return ResolutionNode(
                instance_name="",
                goal=goal_text,
                outcome="success",  # tentative
                depth=depth,
            )

        return None

    def _propagate_outcomes(self, node: ResolutionNode) -> None:
        """Recursively propagate outcomes up the tree."""
        for child in node.children:
            self._propagate_outcomes(child)

        # If any child has a non-success outcome and this node has no explicit failure,
        # propagate the failure up
        if node.children:
            has_success = any(c.outcome == "success" for c in node.children)
            has_depth_exceeded = any(c.outcome == "depth_exceeded" for c in node.children)
            has_failure = any(
                c.outcome in ("unification_failure", "subgoal_failure")
                for c in node.children
            )

            if has_depth_exceeded and node.outcome == "success":
                node.outcome = "depth_exceeded"
            elif has_failure and not has_success and node.outcome == "success":
                node.outcome = "subgoal_failure"
