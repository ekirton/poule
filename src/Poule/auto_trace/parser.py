from __future__ import annotations

import re
from typing import Optional

from Poule.auto_trace.types import AutoSearchNode, AutoSearchTree

_TRACE_LINE_RE = re.compile(
    r"^depth=(\d+)\s+(.+?)(\s+\(\*fail\*\))?\s*$"
)

_HINT_NAME_RE = re.compile(
    r"^(?:simple apply|exact|apply)\s+(\S+)"
)


def _extract_hint_name(action: str) -> Optional[str]:
    if action.strip() == "intro" or action.strip().startswith("intro "):
        return None
    m = _HINT_NAME_RE.match(action)
    if m:
        return m.group(1)
    return None


def parse_trace(messages: list[str]) -> AutoSearchTree:
    if not messages:
        return AutoSearchTree(
            root_nodes=[],
            max_depth=0,
            min_leaf_depth=0,
            depth_limit_reached=False,
            raw_messages=messages,
        )

    root_nodes: list[AutoSearchNode] = []
    # Stack of (node, remaining_depth)
    stack: list[tuple[AutoSearchNode, int]] = []
    max_depth = 0
    min_leaf_depth = float("inf")
    all_leaf_depths: list[tuple[int, str]] = []  # (depth, outcome)

    for line in messages:
        m = _TRACE_LINE_RE.match(line)
        if not m:
            # Unrecognized line — skip (preserved in raw_messages)
            continue

        depth = int(m.group(1))
        action = m.group(2).strip()
        failed = m.group(3) is not None
        outcome = "failure" if failed else "success"

        hint_name = _extract_hint_name(action)

        node = AutoSearchNode(
            action=action,
            hint_name=hint_name,
            remaining_depth=depth,
            outcome=outcome,
            children=[],
            raw_line=line,
        )

        if depth > max_depth:
            max_depth = depth

        # Pop stack until we find a parent with remaining_depth > depth
        while stack and stack[-1][1] <= depth:
            stack.pop()

        if stack:
            stack[-1][0].children.append(node)
        else:
            root_nodes.append(node)

        stack.append((node, depth))

    # Compute min_leaf_depth from leaf nodes
    def _collect_leaf_depths(node: AutoSearchNode) -> None:
        nonlocal min_leaf_depth
        if not node.children:
            all_leaf_depths.append((node.remaining_depth, node.outcome))
            if node.remaining_depth < min_leaf_depth:
                min_leaf_depth = node.remaining_depth
        for child in node.children:
            _collect_leaf_depths(child)

    for root in root_nodes:
        _collect_leaf_depths(root)

    if min_leaf_depth == float("inf"):
        min_leaf_depth = 0

    # depth_limit_reached: any leaf failure at depth=1
    depth_limit_reached = any(
        d == 1 and outcome == "failure" for d, outcome in all_leaf_depths
    )

    return AutoSearchTree(
        root_nodes=root_nodes,
        max_depth=max_depth,
        min_leaf_depth=int(min_leaf_depth),
        depth_limit_reached=depth_limit_reached,
        raw_messages=messages,
    )
