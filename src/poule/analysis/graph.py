"""Graph construction from Storage (IndexReader) and coq-dpdgraph DOT files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .errors import AnalysisError


class NodeMetadata(NamedTuple):
    """Per-declaration metadata: module and kind."""
    module: str
    kind: str


@dataclass
class DependencyGraph:
    """In-memory dependency graph with forward and reverse adjacency lists."""
    forward_adj: dict[str, set[str]]
    reverse_adj: dict[str, set[str]]
    metadata: dict[str, NodeMetadata]
    node_count: int
    edge_count: int


def _infer_module(qualified_name: str) -> str:
    """Infer module from a fully qualified name (prefix up to last dot)."""
    parts = qualified_name.rsplit(".", 1)
    return parts[0] if len(parts) > 1 else ""


def _build_graph_from_storage(index_reader) -> DependencyGraph:
    """Build a DependencyGraph from an IndexReader's declarations and dependencies tables."""
    conn = index_reader._conn

    # Load all declarations
    decl_rows = conn.execute(
        "SELECT id, name, module, kind FROM declarations"
    ).fetchall()

    id_to_name: dict[int, str] = {}
    metadata: dict[str, NodeMetadata] = {}
    forward_adj: dict[str, set[str]] = {}
    reverse_adj: dict[str, set[str]] = {}

    for row in decl_rows:
        decl_id = row[0] if not hasattr(row, 'id') else row.id
        name = row[1] if not hasattr(row, 'name') else row.name
        module = row[2] if not hasattr(row, 'module') else row.module
        kind = row[3] if not hasattr(row, 'kind') else row.kind

        id_to_name[decl_id] = name
        metadata[name] = NodeMetadata(module=module or "", kind=kind or "lemma")
        forward_adj.setdefault(name, set())
        reverse_adj.setdefault(name, set())

    # Load dependencies where relation = 'uses'
    dep_rows = conn.execute(
        "SELECT src, dst, relation FROM dependencies WHERE relation = 'uses'"
    ).fetchall()

    edge_count = 0
    for row in dep_rows:
        src_id = row[0] if not hasattr(row, 'src') else row.src
        dst_id = row[1] if not hasattr(row, 'dst') else row.dst

        src_name = id_to_name.get(src_id)
        dst_name = id_to_name.get(dst_id)
        if src_name is not None and dst_name is not None:
            forward_adj.setdefault(src_name, set()).add(dst_name)
            reverse_adj.setdefault(dst_name, set()).add(src_name)
            edge_count += 1

    return DependencyGraph(
        forward_adj=forward_adj,
        reverse_adj=reverse_adj,
        metadata=metadata,
        node_count=len(metadata),
        edge_count=edge_count,
    )


def _build_graph_from_dpdgraph(dot_file_path: Path) -> DependencyGraph:
    """Build a DependencyGraph from a coq-dpdgraph DOT file."""
    dot_file_path = Path(dot_file_path)

    if not dot_file_path.exists():
        raise AnalysisError(
            "FILE_NOT_FOUND",
            f"DOT file not found: {dot_file_path}",
        )

    content = dot_file_path.read_text()

    # Validate basic DOT structure
    stripped = content.strip()
    if not stripped.endswith("}"):
        raise AnalysisError(
            "PARSE_ERROR",
            "Failed to parse DOT file: missing closing brace",
        )

    # Parse edges: "src" -> "dst"
    edge_pattern = re.compile(r'"([^"]+)"\s*->\s*"([^"]+)"')
    # Parse node declarations: "name" [...]  or just "name";
    node_pattern = re.compile(r'"([^"]+)"')

    forward_adj: dict[str, set[str]] = {}
    reverse_adj: dict[str, set[str]] = {}
    metadata: dict[str, NodeMetadata] = {}
    all_nodes: set[str] = set()
    edge_count = 0

    for match in edge_pattern.finditer(content):
        src, dst = match.group(1), match.group(2)
        all_nodes.add(src)
        all_nodes.add(dst)
        if dst not in forward_adj.setdefault(src, set()):
            forward_adj[src].add(dst)
            reverse_adj.setdefault(dst, set()).add(src)
            edge_count += 1
        else:
            # Duplicate edge, already counted
            pass

    # Also find standalone node declarations
    for match in node_pattern.finditer(content):
        name = match.group(1)
        if name not in ("digraph", "graph", "subgraph"):
            all_nodes.add(name)

    # Ensure all nodes have entries
    for node in all_nodes:
        forward_adj.setdefault(node, set())
        reverse_adj.setdefault(node, set())
        metadata[node] = NodeMetadata(
            module=_infer_module(node),
            kind="definition",  # Default for DOT files; kind not in DOT format
        )

    return DependencyGraph(
        forward_adj=forward_adj,
        reverse_adj=reverse_adj,
        metadata=metadata,
        node_count=len(all_nodes),
        edge_count=edge_count,
    )


def build_graph(
    index_reader=None,
    dot_file_path: Path | str | None = None,
) -> DependencyGraph:
    """Build a DependencyGraph from an IndexReader or a DOT file.

    When both are provided, dot_file_path takes precedence.
    When neither is provided, raises INDEX_MISSING.
    """
    if dot_file_path is not None:
        return _build_graph_from_dpdgraph(Path(dot_file_path))

    if index_reader is not None:
        return _build_graph_from_storage(index_reader)

    raise AnalysisError(
        "INDEX_MISSING",
        "No dependency data available. Provide a coq-dpdgraph DOT file or ensure the index database exists",
    )
