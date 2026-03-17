"""Module-level aggregation and metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from .cycles import detect_cycles, CycleReport
from .graph import DependencyGraph, NodeMetadata


class ModuleMetrics(NamedTuple):
    """Per-module metrics."""
    fan_in: int
    fan_out: int
    internal_nodes: int


@dataclass
class ModuleSummary:
    """Module-level dependency summary."""
    modules: dict[str, ModuleMetrics]
    module_edges: dict[str, set[str]]
    module_cycles: list[list[str]]
    total_modules: int


def module_summary(graph: DependencyGraph) -> ModuleSummary:
    """Compute module-level forward adjacency, metrics, and cycle detection.

    Self-edges (intra-module dependencies) are excluded from the module graph.
    Module-level SCCs are detected via Tarjan's on the projected module graph.
    """
    # Count declarations per module
    module_nodes: dict[str, int] = {}
    for name, meta in graph.metadata.items():
        mod = meta.module
        module_nodes[mod] = module_nodes.get(mod, 0) + 1

    # Build module-level adjacency
    module_forward: dict[str, set[str]] = {mod: set() for mod in module_nodes}
    module_reverse: dict[str, set[str]] = {mod: set() for mod in module_nodes}

    for src, dsts in graph.forward_adj.items():
        src_meta = graph.metadata.get(src)
        if src_meta is None:
            continue
        src_mod = src_meta.module
        for dst in dsts:
            dst_meta = graph.metadata.get(dst)
            if dst_meta is None:
                continue
            dst_mod = dst_meta.module
            if src_mod != dst_mod:
                module_forward[src_mod].add(dst_mod)
                module_reverse.setdefault(dst_mod, set()).add(src_mod)

    # Compute per-module metrics
    modules: dict[str, ModuleMetrics] = {}
    for mod in module_nodes:
        fan_out = len(module_forward.get(mod, set()))
        fan_in = len(module_reverse.get(mod, set()))
        internal = module_nodes[mod]
        modules[mod] = ModuleMetrics(fan_in=fan_in, fan_out=fan_out, internal_nodes=internal)

    # Detect module-level cycles using Tarjan's on the module graph
    # Build a pseudo DependencyGraph for modules
    mod_forward_adj: dict[str, set[str]] = {mod: set(deps) for mod, deps in module_forward.items()}
    mod_reverse_adj: dict[str, set[str]] = {mod: set(deps) for mod, deps in module_reverse.items()}
    mod_metadata = {mod: NodeMetadata(module=mod, kind="module") for mod in module_nodes}

    mod_graph = DependencyGraph(
        forward_adj=mod_forward_adj,
        reverse_adj=mod_reverse_adj,
        metadata=mod_metadata,
        node_count=len(module_nodes),
        edge_count=sum(len(v) for v in mod_forward_adj.values()),
    )

    cycle_report = detect_cycles(mod_graph)

    return ModuleSummary(
        modules=modules,
        module_edges=module_forward,
        module_cycles=cycle_report.cycles,
        total_modules=len(module_nodes),
    )
