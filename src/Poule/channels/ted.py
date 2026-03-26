"""TED fine-ranking channel: Zhang-Shasha tree edit distance.

Computes pairwise tree edit distance between expression trees, converting
distances to similarity scores for fine-grained structural ranking.

Specification: specification/channel-ted.md
"""

from __future__ import annotations

from Poule.models.labels import (
    LAbs,
    LApp,
    LCase,
    LCoFix,
    LConst,
    LConstruct,
    LCseVar,
    LFix,
    LInd,
    LLet,
    LPrimitive,
    LProj,
    LProd,
    LRel,
    LSort,
    NodeLabel,
)
from Poule.models.tree import ExprTree, TreeNode

# ---------------------------------------------------------------------------
# Node categories for rename cost
# ---------------------------------------------------------------------------

_CATEGORY: dict[type, str] = {
    LAbs: "Binder",
    LProd: "Binder",
    LLet: "Binder",
    LApp: "Application",
    LConst: "ConstantRef",
    LInd: "ConstantRef",
    LConstruct: "ConstantRef",
    LRel: "Variable",
    LCseVar: "Variable",
    LSort: "Sort",
    LCase: "Control",
    LFix: "Control",
    LCoFix: "Control",
    LProj: "Projection",
    LPrimitive: "Primitive",
}


def rename_cost(label_a: NodeLabel, label_b: NodeLabel) -> float:
    """Return the rename cost between two node labels.

    Returns 0.0 if labels are equal, 0.5 if same category but different
    labels, 1.0 if different categories.  LSort acts as a wildcard (from
    the parser's ``_`` token) and matches any label at cost 0.0.
    """
    if label_a == label_b:
        return 0.0
    if isinstance(label_a, LSort) or isinstance(label_b, LSort):
        return 0.0
    cat_a = _CATEGORY[type(label_a)]
    cat_b = _CATEGORY[type(label_b)]
    if cat_a == cat_b:
        return 0.5
    return 1.0


# ---------------------------------------------------------------------------
# Zhang-Shasha tree edit distance
# ---------------------------------------------------------------------------


def _postorder(node: TreeNode) -> list[TreeNode]:
    """Return nodes in post-order (children before parent)."""
    result: list[TreeNode] = []
    stack: list[tuple[TreeNode, bool]] = [(node, False)]
    while stack:
        n, visited = stack.pop()
        if visited:
            result.append(n)
        else:
            stack.append((n, True))
            # Push children in reverse so leftmost is processed first
            for child in reversed(n.children):
                stack.append((child, False))
    return result


def _leftmost_leaf(nodes: list[TreeNode], node_to_idx: dict[int, int]) -> list[int]:
    """Compute leftmost leaf descendant index for each node in post-order list.

    Returns a list where lml[i] is the post-order index of the leftmost leaf
    descendant of nodes[i].
    """
    n = len(nodes)
    lml = [0] * n
    for i, node in enumerate(nodes):
        if not node.children:
            lml[i] = i
        else:
            # Leftmost child in post-order
            first_child = node.children[0]
            first_child_idx = node_to_idx[id(first_child)]
            lml[i] = lml[first_child_idx]
    return lml


def _keyroots(lml: list[int]) -> list[int]:
    """Identify keyroots: nodes whose leftmost leaf descendant differs from
    their parent's. The root is always a keyroot.

    Returns sorted list of post-order indices.
    """
    n = len(lml)
    # A node is a keyroot if no later node shares its leftmost leaf descendant.
    # Equivalently, for each unique lml value, the rightmost (highest index)
    # node with that lml value is a keyroot.
    kr: dict[int, int] = {}
    for i in range(n):
        kr[lml[i]] = i
    return sorted(kr.values())


def ted(tree_a: ExprTree, tree_b: ExprTree) -> float:
    """Compute tree edit distance using the Zhang-Shasha algorithm.

    Both trees must be valid ExprTree instances with node_id fields set.
    Handles empty trees (root=None, node_count=0).
    """
    # Handle empty trees
    a_empty = tree_a.root is None or tree_a.node_count == 0
    b_empty = tree_b.root is None or tree_b.node_count == 0
    if a_empty and b_empty:
        return 0.0
    if a_empty:
        return float(tree_b.node_count)
    if b_empty:
        return float(tree_a.node_count)

    # Step 1: Post-order traversal
    nodes_a = _postorder(tree_a.root)
    nodes_b = _postorder(tree_b.root)
    na = len(nodes_a)
    nb = len(nodes_b)

    # Map object id to post-order index
    id_to_idx_a: dict[int, int] = {id(n): i for i, n in enumerate(nodes_a)}
    id_to_idx_b: dict[int, int] = {id(n): i for i, n in enumerate(nodes_b)}

    # Step 2: Leftmost leaf descendants
    lml_a = _leftmost_leaf(nodes_a, id_to_idx_a)
    lml_b = _leftmost_leaf(nodes_b, id_to_idx_b)

    # Step 3: Keyroots
    kr_a = _keyroots(lml_a)
    kr_b = _keyroots(lml_b)

    # Step 4: Tree distance DP
    # td[i][j] = tree edit distance between subtree rooted at nodes_a[i]
    # and subtree rooted at nodes_b[j]
    td = [[0.0] * nb for _ in range(na)]

    for i in kr_a:
        for j in kr_b:
            # Forest distance matrix
            # Indices range from lml_a[i]..i and lml_b[j]..j
            li = lml_a[i]
            lj = lml_b[j]

            # fd is indexed [s - li + 1][t - lj + 1] where s in [li-1..i], t in [lj-1..j]
            # fd[0][0] = 0 (empty vs empty)
            rows = i - li + 2
            cols = j - lj + 2

            fd = [[0.0] * cols for _ in range(rows)]

            # Base cases: deleting all nodes from forest
            for s in range(1, rows):
                fd[s][0] = fd[s - 1][0] + 1.0  # delete cost
            for t in range(1, cols):
                fd[0][t] = fd[0][t - 1] + 1.0  # insert cost

            for s in range(1, rows):
                for t in range(1, cols):
                    s_idx = s + li - 1  # actual post-order index in A
                    t_idx = t + lj - 1  # actual post-order index in B

                    cost_del = fd[s - 1][t] + 1.0
                    cost_ins = fd[s][t - 1] + 1.0

                    if lml_a[s_idx] == lml_a[i] and lml_b[t_idx] == lml_b[j]:
                        # Both are in the same "leftmost path" as the keyroots
                        rc = rename_cost(nodes_a[s_idx].label, nodes_b[t_idx].label)
                        cost_ren = fd[s - 1][t - 1] + rc
                        fd[s][t] = min(cost_del, cost_ins, cost_ren)
                        td[s_idx][t_idx] = fd[s][t]
                    else:
                        # Use previously computed tree distances
                        p = lml_a[s_idx] - li + 1
                        q = lml_b[t_idx] - lj + 1
                        cost_td = fd[p - 1][q - 1] + td[s_idx][t_idx]
                        fd[s][t] = min(cost_del, cost_ins, cost_td)

    return td[na - 1][nb - 1]


def ted_similarity(tree_a: ExprTree, tree_b: ExprTree) -> float:
    """Compute TED-based similarity score.

    Returns max(0.0, 1.0 - ted(a, b) / max(nc_a, nc_b)).
    """
    distance = ted(tree_a, tree_b)
    max_nc = max(tree_a.node_count, tree_b.node_count)
    if max_nc == 0:
        return 1.0
    return max(0.0, 1.0 - distance / max_nc)
