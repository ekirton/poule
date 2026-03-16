"""CSE (Common Subexpression Elimination) normalization for expression trees."""

from __future__ import annotations

import hashlib
from collections import Counter

from wily_rooster.models.labels import (
    LConst,
    LConstruct,
    LCseVar,
    LInd,
)
from wily_rooster.models.tree import (
    ExprTree,
    TreeNode,
    assign_node_ids,
    node_count,
    recompute_depths,
)
from wily_rooster.normalization.errors import NormalizationError

# Label types that are "constant" and must never be replaced by CSE
_CONSTANT_LABEL_TYPES = (LConst, LInd, LConstruct)


def _structural_hash(node: TreeNode, hashes: dict[int, str]) -> str:
    """Compute structural hash for a node (post-order). Stores in hashes keyed by id(node)."""
    child_hashes = []
    for child in node.children:
        child_hashes.append(_structural_hash(child, hashes))

    label = node.label
    tag = f"{type(label).__name__}:{_label_payload(label)}"
    content = tag + "|" + ",".join(child_hashes)
    h = hashlib.md5(content.encode("utf-8")).hexdigest()
    hashes[id(node)] = h
    return h


def _label_payload(label: object) -> str:
    """Return a deterministic string representation of the label's payload."""
    if hasattr(label, "__dataclass_fields__"):
        fields = label.__dataclass_fields__  # type: ignore[attr-defined]
        parts = []
        for name in fields:
            val = getattr(label, name)
            parts.append(f"{name}={val!r}")
        return ",".join(parts)
    return ""


def _is_constant_label(label: object) -> bool:
    """Check if a label is a constant type that must not be replaced."""
    return isinstance(label, _CONSTANT_LABEL_TYPES)


def _has_constant_descendant(node: TreeNode) -> bool:
    """Check if a subtree contains any constant-labeled node (including node itself)."""
    if _is_constant_label(node.label):
        return True
    return any(_has_constant_descendant(c) for c in node.children)


def _has_inner_candidate(node: TreeNode, freq: Counter[str], hashes: dict[int, str]) -> bool:
    """Check if any PROPER descendant (not node itself) is a non-constant candidate."""
    for child in node.children:
        h = hashes[id(child)]
        if freq[h] >= 2 and not _is_constant_label(child.label):
            return True
        if _has_inner_candidate(child, freq, hashes):
            return True
    return False


def cse_normalize(tree: ExprTree) -> None:
    """Apply three-pass CSE to an ExprTree, mutating it in place.

    Pass 1: Structural hashing (post-order)
    Pass 2: Frequency counting
    Pass 3: Replacement (pre-order), first occurrence preserved.
            A non-first candidate is NOT replaced if its subtree contains
            constant-labeled descendants AND inner non-constant candidates;
            instead, the inner candidates are replaced.
    Then: recompute_depths, assign_node_ids, update node_count.
    """
    if tree.node_count <= 1:
        recompute_depths(tree)
        assign_node_ids(tree)
        return

    try:
        # Pass 1: Structural hashing
        hashes: dict[int, str] = {}
        _structural_hash(tree.root, hashes)

        # Pass 2: Frequency counting
        freq: Counter[str] = Counter(hashes.values())

        # Pre-compute which candidate subtrees should not be replaced wholesale
        # because they contain both constant descendants and inner candidates.
        skip_wholesale: set[str] = set()  # hashes to not replace wholesale

        def _check_skip(node: TreeNode) -> None:
            h = hashes[id(node)]
            if freq[h] >= 2 and not _is_constant_label(node.label):
                if (_has_constant_descendant(node)
                        and _has_inner_candidate(node, freq, hashes)):
                    skip_wholesale.add(h)
            for child in node.children:
                _check_skip(child)

        _check_skip(tree.root)

        # Pass 3: Replacement (pre-order)
        seen: dict[str, int] = {}  # hash -> cse_var_id
        next_id = [0]

        def _replace(node: TreeNode) -> TreeNode:
            h = hashes[id(node)]
            is_candidate = freq[h] >= 2 and not _is_constant_label(node.label)

            if is_candidate and h not in skip_wholesale:
                if h in seen:
                    # Subsequent occurrence -> replace with LCseVar
                    return TreeNode(label=LCseVar(seen[h]), children=[])
                else:
                    # First occurrence -> preserve, register, recurse
                    seen[h] = next_id[0]
                    next_id[0] += 1
                    node.children = [_replace(c) for c in node.children]
                    return node
            else:
                # Not a candidate or skipped -> recurse into children
                node.children = [_replace(c) for c in node.children]
                return node

        tree.root = _replace(tree.root)

    except RecursionError:
        raise NormalizationError(
            declaration_name="<unknown>",
            message="Recursion depth exceeded during CSE normalization",
        )

    # Post-replacement: recompute metadata
    tree.node_count = node_count(tree.root)
    recompute_depths(tree)
    assign_node_ids(tree)
