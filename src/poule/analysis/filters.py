"""Scope filter predicates for BFS traversal."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import DependencyGraph


def module_prefix(prefix: str):
    """Include only nodes whose module starts with `prefix`."""
    def _filter(node: str, graph: DependencyGraph) -> bool:
        meta = graph.metadata.get(node)
        if meta is None:
            return False
        return meta.module.startswith(prefix)
    return _filter


def exclude_prefix(prefix: str):
    """Exclude nodes whose module starts with `prefix`."""
    def _filter(node: str, graph: DependencyGraph) -> bool:
        meta = graph.metadata.get(node)
        if meta is None:
            return True
        return not meta.module.startswith(prefix)
    return _filter


def same_project(node: str, graph: DependencyGraph) -> bool:
    """Include only nodes whose top-level module namespace matches the root's.

    This is a bare filter function (not a factory), used directly in scope_filter lists.
    It requires _root_namespace to be set on the graph during traversal. Since we cannot
    modify the graph, this function needs the root's namespace. We use a closure approach
    where the BFS caller sets a module attribute on the function.
    """
    meta = graph.metadata.get(node)
    if meta is None:
        return False
    node_ns = meta.module.split(".")[0] if meta.module else ""
    root_ns = getattr(same_project, "_root_namespace", "")
    return node_ns == root_ns
