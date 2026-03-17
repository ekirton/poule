"""Constraint graph construction and filtering.

Spec: specification/universe-inspection.md sections 4.4, 4.5.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import List, Set

from poule.universe.types import ConstraintGraph, UniverseConstraint


def _extract_variable_name(expr) -> str | None:
    """Extract variable name from a UniverseExpression, if it is a variable."""
    if expr.kind == "variable" and expr.name is not None:
        return expr.name
    return None


def build_graph(constraints: List[UniverseConstraint]) -> ConstraintGraph:
    """Build a ConstraintGraph from a list of constraints.

    Constructs a graph with variables containing all unique universe variable
    names from both sides of all constraints.
    """
    variables_set: set[str] = set()
    for c in constraints:
        left_name = _extract_variable_name(c.left)
        right_name = _extract_variable_name(c.right)
        if left_name:
            variables_set.add(left_name)
        if right_name:
            variables_set.add(right_name)

    variables = sorted(variables_set)
    return ConstraintGraph(
        variables=variables,
        constraints=list(constraints),
        node_count=len(variables),
        edge_count=len(constraints),
        filtered_from=None,
    )


def filter_by_reachability(
    graph: ConstraintGraph,
    seed_variables: List[str],
) -> ConstraintGraph:
    """Filter a constraint graph to the subgraph reachable from seed variables.

    Computes reachability by following constraint edges in both directions
    (forward and backward). Returns a ConstraintGraph containing only the
    reachable variables and constraints where both endpoints are reachable.
    """
    # Build undirected adjacency list
    adjacency: dict[str, set[str]] = defaultdict(set)
    for c in graph.constraints:
        left_name = _extract_variable_name(c.left)
        right_name = _extract_variable_name(c.right)
        if left_name and right_name:
            adjacency[left_name].add(right_name)
            adjacency[right_name].add(left_name)

    # BFS from seed variables
    reachable: Set[str] = set()
    queue: deque[str] = deque()
    for seed in seed_variables:
        if seed in graph.variables or seed in adjacency:
            reachable.add(seed)
            queue.append(seed)

    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)

    # Filter constraints to those with both endpoints in reachable set
    filtered_constraints = []
    for c in graph.constraints:
        left_name = _extract_variable_name(c.left)
        right_name = _extract_variable_name(c.right)
        if left_name in reachable and right_name in reachable:
            filtered_constraints.append(c)

    filtered_variables = sorted(reachable)
    return ConstraintGraph(
        variables=filtered_variables,
        constraints=filtered_constraints,
        node_count=len(filtered_variables),
        edge_count=len(filtered_constraints),
        filtered_from=graph.filtered_from,
    )


def detect_cycles_with_strict_edge(
    graph: ConstraintGraph,
) -> List[UniverseConstraint]:
    """Detect the shortest directed cycle containing at least one strict (<) edge.

    Uses iterative DFS for cycle detection to avoid stack overflow on large graphs.
    Returns the cycle as a list of constraints, or an empty list if no such cycle exists.
    """
    if not graph.constraints:
        return []

    # Build directed adjacency list: node -> list of (neighbor, constraint)
    adj: dict[str, list[tuple[str, UniverseConstraint]]] = defaultdict(list)
    for c in graph.constraints:
        left_name = _extract_variable_name(c.left)
        right_name = _extract_variable_name(c.right)
        if left_name and right_name:
            adj[left_name].append((right_name, c))
            # For equality constraints, add both directions
            if c.relation == "eq":
                adj[right_name].append((left_name, c))

    # Find all cycles using DFS from each node, then filter for strict edges
    best_cycle: List[UniverseConstraint] = []

    for start_node in graph.variables:
        # BFS-based cycle detection for shortest cycle from start_node
        # Track: (current_node, path_of_constraints)
        visited_paths: dict[str, int] = {}
        queue: deque[tuple[str, list[UniverseConstraint]]] = deque()
        queue.append((start_node, []))
        visited_paths[start_node] = 0

        while queue:
            current, path = queue.popleft()

            for neighbor, constraint in adj.get(current, []):
                new_path = path + [constraint]

                if neighbor == start_node and len(new_path) > 0:
                    # Found a cycle back to start
                    has_strict = any(c.relation == "lt" for c in new_path)
                    if has_strict:
                        if not best_cycle or len(new_path) < len(best_cycle):
                            best_cycle = new_path
                    continue

                if neighbor not in visited_paths or len(new_path) < visited_paths[neighbor]:
                    visited_paths[neighbor] = len(new_path)
                    if len(new_path) < len(graph.constraints):  # bound search
                        queue.append((neighbor, new_path))

    return best_cycle
