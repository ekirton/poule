"""Cycle detection via iterative Tarjan's SCC algorithm."""

from __future__ import annotations

from dataclasses import dataclass

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .graph import DependencyGraph


@dataclass
class CycleReport:
    """Result of cycle detection over a dependency graph."""
    cycles: list[list[str]]
    total_cycle_count: int
    total_nodes_in_cycles: int
    is_acyclic: bool


def detect_cycles(graph: DependencyGraph) -> CycleReport:
    """Detect all strongly connected components with size >= 2 using iterative Tarjan's algorithm.

    Each SCC is rotated to start with the lexicographically smallest member.

    Returns:
        CycleReport with all non-trivial SCCs.
    """
    index_counter = [0]
    node_index: dict[str, int] = {}
    node_lowlink: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    sccs: list[list[str]] = []

    # Iterative Tarjan's to avoid stack overflow on large graphs
    all_nodes = set(graph.forward_adj.keys()) | set(graph.reverse_adj.keys()) | set(graph.metadata.keys())

    for start in sorted(all_nodes):
        if start in node_index:
            continue

        # Iterative DFS using an explicit call stack
        # Each frame: (node, neighbor_iterator, is_initial_visit)
        call_stack: list[tuple[str, list[str], int]] = []
        _push_node(start, index_counter, node_index, node_lowlink, on_stack, stack)
        neighbors = sorted(graph.forward_adj.get(start, set()))
        call_stack.append((start, neighbors, 0))

        while call_stack:
            v, nbrs, idx = call_stack[-1]

            if idx < len(nbrs):
                w = nbrs[idx]
                call_stack[-1] = (v, nbrs, idx + 1)

                if w not in node_index:
                    _push_node(w, index_counter, node_index, node_lowlink, on_stack, stack)
                    w_neighbors = sorted(graph.forward_adj.get(w, set()))
                    call_stack.append((w, w_neighbors, 0))
                elif on_stack.get(w, False):
                    node_lowlink[v] = min(node_lowlink[v], node_index[w])
            else:
                # All neighbors processed; check if v is a root of an SCC
                if node_lowlink[v] == node_index[v]:
                    scc: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        scc.append(w)
                        if w == v:
                            break
                    if len(scc) > 1:
                        # Rotate to start with lexicographically smallest
                        min_idx = scc.index(min(scc))
                        scc = scc[min_idx:] + scc[:min_idx]
                        sccs.append(scc)

                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    node_lowlink[parent] = min(node_lowlink[parent], node_lowlink[v])

    total_nodes = sum(len(scc) for scc in sccs)

    return CycleReport(
        cycles=sccs,
        total_cycle_count=len(sccs),
        total_nodes_in_cycles=total_nodes,
        is_acyclic=len(sccs) == 0,
    )


def _push_node(
    v: str,
    index_counter: list[int],
    node_index: dict[str, int],
    node_lowlink: dict[str, int],
    on_stack: dict[str, bool],
    stack: list[str],
) -> None:
    """Initialize a node for Tarjan's algorithm."""
    node_index[v] = index_counter[0]
    node_lowlink[v] = index_counter[0]
    index_counter[0] += 1
    stack.append(v)
    on_stack[v] = True
