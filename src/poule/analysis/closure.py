"""Transitive closure computation via forward BFS."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .errors import AnalysisError
from .filters import same_project

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .graph import DependencyGraph


RESULT_SIZE_LIMIT = 10_000


@dataclass
class TransitiveClosure:
    """Result of a forward transitive closure computation."""
    root: str
    nodes: set[str]
    edges: set[tuple[str, str]]
    depth_map: dict[int, set[str]]
    total_depth: int


def transitive_closure(
    graph: DependencyGraph,
    root: str,
    max_depth: int | None = None,
    scope_filter: list | None = None,
) -> TransitiveClosure:
    """Compute forward transitive closure from root via BFS.

    Args:
        graph: The dependency graph.
        root: Fully qualified declaration name.
        max_depth: Maximum BFS depth (None = unlimited, <=0 clamped to 1).
        scope_filter: List of filter predicates; all must pass for a node to be visited.

    Returns:
        TransitiveClosure with all reachable nodes, edges, and depth map.

    Raises:
        AnalysisError: INVALID_INPUT if root is empty, NOT_FOUND if root not in graph,
                       RESULT_TOO_LARGE if result exceeds 10,000 nodes.
    """
    if not root:
        raise AnalysisError("INVALID_INPUT", "Root declaration name must be non-empty")

    if root not in graph.forward_adj and root not in graph.metadata:
        raise AnalysisError(
            "NOT_FOUND",
            f"Declaration {root} not found in the dependency graph",
        )

    if scope_filter is None:
        scope_filter = []

    # Clamp max_depth <= 0 to 1
    if max_depth is not None and max_depth <= 0:
        max_depth = 1

    # Set root namespace for same_project filter
    root_meta = graph.metadata.get(root)
    if root_meta:
        root_ns = root_meta.module.split(".")[0] if root_meta.module else ""
        same_project._root_namespace = root_ns

    visited: set[str] = {root}
    depth_map: dict[int, set[str]] = {0: {root}}
    frontier = deque([root])
    depth = 0

    while frontier and (max_depth is None or depth < max_depth):
        next_frontier: set[str] = set()
        for _ in range(len(frontier)):
            node = frontier.popleft()
            for neighbor in graph.forward_adj.get(node, set()):
                if neighbor in visited:
                    continue
                # Apply scope filters (root is already included)
                if not _passes_filters(neighbor, graph, scope_filter):
                    continue
                visited.add(neighbor)
                next_frontier.add(neighbor)

        if not next_frontier:
            break

        depth += 1
        depth_map[depth] = next_frontier
        frontier.extend(next_frontier)

        # Check size limit
        if len(visited) > RESULT_SIZE_LIMIT:
            raise AnalysisError(
                "RESULT_TOO_LARGE",
                f"Result contains {len(visited)} nodes, exceeding the limit of {RESULT_SIZE_LIMIT}. "
                "Use max_depth or scope filters to narrow the query",
            )

    # Collect edges within the closure
    edges: set[tuple[str, str]] = set()
    for u in visited:
        for v in graph.forward_adj.get(u, set()):
            if v in visited:
                edges.add((u, v))

    total_depth = max(depth_map.keys()) if depth_map else 0

    return TransitiveClosure(
        root=root,
        nodes=visited,
        edges=edges,
        depth_map=depth_map,
        total_depth=total_depth,
    )


def _passes_filters(node: str, graph, scope_filter: list) -> bool:
    """Return True if node passes all filter predicates."""
    for f in scope_filter:
        if not f(node, graph):
            return False
    return True
