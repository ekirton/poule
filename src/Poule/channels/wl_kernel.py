"""WL Kernel Screening Channel.

Weisfeiler-Lehman graph kernel for fast structural screening of expression trees.

Specification: specification/channel-wl-kernel.md
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from Poule.models.tree import ExprTree, TreeNode


def _md5(text: str) -> str:
    """Return lowercase 32-char hex MD5 digest of UTF-8 encoded text."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _label_type_name(label: Any) -> str:
    """Extract the type name from a node label.

    For string labels (used in tests), returns the string itself.
    For NodeLabel subclass instances, returns the class name.
    """
    if isinstance(label, str):
        return label
    return type(label).__name__


def _collect_nodes(node: TreeNode) -> list[TreeNode]:
    """Collect all nodes in pre-order traversal."""
    result = [node]
    for child in node.children:
        result.extend(_collect_nodes(child))
    return result


def wl_histogram(tree: ExprTree, h: int) -> dict[str, int]:
    """Compute a WL histogram for an expression tree.

    Args:
        tree: A valid ExprTree with depth fields set.
        h: Number of WL refinement iterations (non-negative integer).

    Returns:
        Sparse dict mapping label hashes (32-char hex) to occurrence counts.
    """
    nodes = _collect_nodes(tree.root)

    # Build a map from node id() to its children for fast lookup
    children_map: dict[int, list[int]] = {}
    for node in nodes:
        children_map[id(node)] = [id(c) for c in node.children]

    # Iteration 0: simplified labels
    labels: dict[int, str] = {}
    for node in nodes:
        type_name = _label_type_name(node.label)
        child_count = len(node.children)
        simplified = f"{type_name}_{node.depth}_{child_count}"
        labels[id(node)] = _md5(simplified)

    # Collect all labels across iterations into histogram
    histogram: dict[str, int] = {}

    # Add iteration 0 labels
    for node in nodes:
        lbl = labels[id(node)]
        histogram[lbl] = histogram.get(lbl, 0) + 1

    # Iterations 1..h
    for _i in range(1, h + 1):
        new_labels: dict[int, str] = {}
        for node in nodes:
            node_label = labels[id(node)]
            child_labels = sorted(labels[id(c)] for c in node.children)
            combined = node_label + "".join(child_labels)
            new_labels[id(node)] = _md5(combined)
        labels = new_labels

        # Add this iteration's labels to histogram
        for node in nodes:
            lbl = labels[id(node)]
            histogram[lbl] = histogram.get(lbl, 0) + 1

    return histogram


def wl_cosine(hist_a: dict[str, int], hist_b: dict[str, int]) -> float:
    """Compute cosine similarity between two sparse histograms.

    Args:
        hist_a: Sparse histogram (label hash -> count).
        hist_b: Sparse histogram (label hash -> count).

    Returns:
        Cosine similarity in [0.0, 1.0]. Returns 0.0 if either is empty.
    """
    if not hist_a or not hist_b:
        return 0.0

    # Sparse dot product over shared keys
    dot = 0.0
    # Iterate over the smaller histogram for efficiency
    if len(hist_a) > len(hist_b):
        hist_a, hist_b = hist_b, hist_a
    for key, val_a in hist_a.items():
        val_b = hist_b.get(key, 0)
        dot += val_a * val_b

    norm_a = math.sqrt(sum(v * v for v in hist_a.values()))
    norm_b = math.sqrt(sum(v * v for v in hist_b.values()))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def size_filter(
    query_node_count: int,
    candidate_node_count: int,
    size_ratio: float | None = None,
) -> bool:
    """Check whether a candidate passes the size filter.

    Args:
        query_node_count: Node count of the query tree.
        candidate_node_count: Node count of the candidate tree.
        size_ratio: Optional custom size ratio threshold. When provided,
            reject if max/min > size_ratio. When None, use built-in
            thresholds (1.2 for small queries, 1.8 for large).

    Returns:
        True if the candidate passes (should be considered), False if rejected.
    """
    max_nc = max(query_node_count, candidate_node_count)
    min_nc = max(min(query_node_count, candidate_node_count), 1)  # guard against zero
    ratio = max_nc / min_nc

    if size_ratio is not None:
        return ratio <= size_ratio

    if query_node_count < 600:
        return ratio <= 1.2
    else:
        return ratio <= 1.8


def wl_screen(
    query_histogram: dict[str, int],
    query_node_count: int,
    library_histograms: dict[Any, dict[str, int]],
    library_node_counts: dict[Any, int],
    n: int = 500,
    size_ratio: float | None = None,
) -> list[tuple[Any, float]]:
    """Screen library declarations against a query using WL kernel similarity.

    Args:
        query_histogram: WL histogram for the query.
        query_node_count: Node count of the query tree.
        library_histograms: Map of decl_id -> WL histogram.
        library_node_counts: Map of decl_id -> node count.
        n: Maximum number of candidates to return (default 500).
        size_ratio: Optional custom size ratio threshold forwarded to
            size_filter. When None, use built-in thresholds.

    Returns:
        Up to n (decl_id, cosine_score) pairs, sorted by score descending.
    """
    if not query_histogram:
        return []

    candidates: list[tuple[Any, float]] = []
    for decl_id, lib_hist in library_histograms.items():
        lib_nc = library_node_counts.get(decl_id, 0)
        if not size_filter(query_node_count, lib_nc, size_ratio=size_ratio):
            continue
        score = wl_cosine(query_histogram, lib_hist)
        candidates.append((decl_id, score))

    # Sort by score descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:n]


# Alias for offline indexing
compute_wl_vector = wl_histogram
