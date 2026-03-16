# Task: Core Data Structures Implementation

## Overview

Implement the shared in-memory type definitions from `specification/data-structures.md`. These types form the internal API consumed by every other component: extraction, normalization, all retrieval channels, and fusion. This is the foundational module with zero internal dependencies -- it must be implemented first before any other component can begin.

The deliverable is a Python package providing `NodeLabel` (16 variants), `ExprTree`, `SortKind`, `WlHistogram`, `SymbolSet`, `ScoredResult`, plus tree utility functions (`recompute_depths`, `assign_node_ids`, `validate_tree`, `node_count`, `extract_symbols`) and serialization helpers.

---

## Dependencies

### Must Exist Before This Task

None. This is the first implementation task. No `src/` directory exists yet.

### Must Exist Before Downstream Tasks

Every other task depends on this one:
- `coq-normalization` (consumes `ExprTree`, `NodeLabel`, calls `recompute_depths`, `assign_node_ids`)
- `cse-normalization` (consumes `ExprTree`, produces `LCseVar` nodes)
- `channel-wl-kernel` (consumes `ExprTree`, produces `WlHistogram`)
- `channel-mepo` (consumes `SymbolSet`)
- `channel-ted` (consumes `ExprTree`)
- `channel-const-jaccard` (consumes `ExprTree`)
- `channel-fts` (no direct dependency, but uses `ScoredResult`)
- `fusion` (consumes `ScoredResult`)
- `storage` (serializes/deserializes `ExprTree`, `WlHistogram`)
- `extraction` (calls `extract_symbols`, tree utilities)

---

## Module Structure

```
src/
  coq_search/
    __init__.py
    models/
      __init__.py          # re-exports all public types
      node_labels.py       # SortKind, NodeLabel, and all 16 label variants
      expr_tree.py         # ExprTree dataclass
      scored_result.py     # ScoredResult dataclass
      type_aliases.py      # WlHistogram, Symbol, SymbolSet
    tree/
      __init__.py          # re-exports public functions
      traversal.py         # iteration helpers (dfs, bfs, leaves, etc.)
      construction.py      # recompute_depths, assign_node_ids
      validation.py        # validate_tree, invariant checks
      symbols.py           # extract_symbols
      serialization.py     # pickle-based ExprTree serialization
```

---

## Implementation Steps

### Step 1: Project Scaffolding

Create the Python package skeleton.

**Files**: `src/coq_search/__init__.py`, `src/coq_search/models/__init__.py`, `src/coq_search/tree/__init__.py`

All `__init__.py` files start minimal. The top-level `__init__.py` may remain empty or contain a version string. The `models/__init__.py` and `tree/__init__.py` will re-export public names once the modules are populated.

---

### Step 2: Node Labels (`src/coq_search/models/node_labels.py`)

Implement exactly as specified in Section 3 + Language-Specific Notes of the spec.

```python
from dataclasses import dataclass
from enum import Enum, auto


class SortKind(Enum):
    PROP = auto()
    SET = auto()
    TYPE_UNIV = auto()


class NodeLabel:
    """Base class for the node label tagged union. Do not instantiate directly."""
    pass


@dataclass(frozen=True)
class LRel(NodeLabel):
    index: int

@dataclass(frozen=True)
class LVar(NodeLabel):
    name: str

@dataclass(frozen=True)
class LSort(NodeLabel):
    kind: SortKind

@dataclass(frozen=True)
class LProd(NodeLabel):
    pass

@dataclass(frozen=True)
class LLambda(NodeLabel):
    pass

@dataclass(frozen=True)
class LLetIn(NodeLabel):
    pass

@dataclass(frozen=True)
class LApp(NodeLabel):
    pass

@dataclass(frozen=True)
class LConst(NodeLabel):
    name: str

@dataclass(frozen=True)
class LInd(NodeLabel):
    name: str

@dataclass(frozen=True)
class LConstruct(NodeLabel):
    name: str
    index: int

@dataclass(frozen=True)
class LCase(NodeLabel):
    pass

@dataclass(frozen=True)
class LFix(NodeLabel):
    mutual_index: int

@dataclass(frozen=True)
class LCoFix(NodeLabel):
    mutual_index: int

@dataclass(frozen=True)
class LProj(NodeLabel):
    name: str

@dataclass(frozen=True)
class LInt(NodeLabel):
    value: int

@dataclass(frozen=True)
class LCseVar(NodeLabel):
    var_id: int
```

**Key implementation notes**:
- `frozen=True` gives automatic `__hash__` and `__eq__` on all fields. This is required because labels are used as dict keys in WL computation.
- Payload-less labels (`LProd`, `LLambda`, `LLetIn`, `LApp`, `LCase`) are singletons for comparison: `LProd() == LProd()` is `True`.
- `NodeLabel` base class is NOT a dataclass and NOT frozen. It exists only for isinstance checks and type annotations.
- Consider adding `__slots__ = ()` to `NodeLabel` base class for memory efficiency (optional).

**Verification**: `hash(LConst("foo")) == hash(LConst("foo"))` must be True. `LProd() == LProd()` must be True. `LConst("foo") != LConst("bar")` must be True.

---

### Step 3: ExprTree (`src/coq_search/models/expr_tree.py`)

```python
from dataclasses import dataclass, field
from .node_labels import NodeLabel


@dataclass
class ExprTree:
    label: NodeLabel
    children: list["ExprTree"] = field(default_factory=list)
    depth: int = 0
    node_id: int = 0
```

**Key implementation notes**:
- `ExprTree` is intentionally **mutable**. The `depth` and `node_id` fields are set after construction by `recompute_depths()` and `assign_node_ids()`. Children may be replaced during CSE normalization.
- `ExprTree` is NOT hashable (mutable dataclass). This is correct. CSE normalization uses a separate content-hashing function, not Python's `__hash__`.
- The `children` list uses `field(default_factory=list)` to avoid the mutable default argument pitfall.

---

### Step 4: Type Aliases (`src/coq_search/models/type_aliases.py`)

```python
WlHistogram = dict[str, int]
Symbol = str
SymbolSet = list[Symbol]
```

These are pure type aliases. They carry no runtime behavior but provide documentation value and enable type checking.

---

### Step 5: ScoredResult (`src/coq_search/models/scored_result.py`)

```python
from dataclasses import dataclass


@dataclass
class ScoredResult:
    decl_id: int
    channel: str
    rank: int
    raw_score: float
```

**Key implementation notes**:
- `decl_id` is a positive integer (FK to `declarations.id`).
- `rank` is 1-based within the channel.
- `raw_score` semantics vary by channel (cosine similarity, BM25 score, etc.). It is channel-specific and not comparable across channels.

---

### Step 6: Models Re-exports (`src/coq_search/models/__init__.py`)

```python
from .node_labels import (
    SortKind, NodeLabel,
    LRel, LVar, LSort, LProd, LLambda, LLetIn, LApp,
    LConst, LInd, LConstruct, LCase, LFix, LCoFix,
    LProj, LInt, LCseVar,
)
from .expr_tree import ExprTree
from .scored_result import ScoredResult
from .type_aliases import WlHistogram, Symbol, SymbolSet

__all__ = [
    "SortKind", "NodeLabel",
    "LRel", "LVar", "LSort", "LProd", "LLambda", "LLetIn", "LApp",
    "LConst", "LInd", "LConstruct", "LCase", "LFix", "LCoFix",
    "LProj", "LInt", "LCseVar",
    "ExprTree", "ScoredResult",
    "WlHistogram", "Symbol", "SymbolSet",
]
```

---

### Step 7: Tree Traversal (`src/coq_search/tree/traversal.py`)

Provide iteration helpers used by validation, symbol extraction, and downstream components.

```python
from collections.abc import Iterator
from coq_search.models import ExprTree


def dfs_preorder(tree: ExprTree) -> Iterator[ExprTree]:
    """Yield all nodes in depth-first pre-order (root first)."""
    yield tree
    for child in tree.children:
        yield from dfs_preorder(child)


def dfs_postorder(tree: ExprTree) -> Iterator[ExprTree]:
    """Yield all nodes in depth-first post-order (leaves first)."""
    for child in tree.children:
        yield from dfs_postorder(child)
    yield tree


def leaves(tree: ExprTree) -> Iterator[ExprTree]:
    """Yield all leaf nodes (nodes with no children)."""
    for node in dfs_preorder(tree):
        if not node.children:
            yield node


def node_count(tree: ExprTree) -> int:
    """Return total number of nodes in the tree."""
    return sum(1 for _ in dfs_preorder(tree))
```

**Key implementation notes**:
- Use generators for memory efficiency on large trees.
- `dfs_preorder` is the default traversal for most operations.
- Consider adding a recursion limit guard for deeply nested trees (coq-normalization.md caps at 1,000 depth).

---

### Step 8: Tree Construction Utilities (`src/coq_search/tree/construction.py`)

```python
from coq_search.models import ExprTree


def recompute_depths(tree: ExprTree, starting_depth: int = 0) -> ExprTree:
    """Set depth field on all nodes. Mutates tree in place and returns it.

    REQUIRES: tree is a valid ExprTree.
    ENSURES: root.depth == starting_depth; each child's depth == parent.depth + 1.
    """
    tree.depth = starting_depth
    for child in tree.children:
        recompute_depths(child, starting_depth + 1)
    return tree


def assign_node_ids(tree: ExprTree, starting_id: int = 0) -> ExprTree:
    """Assign unique node_id to every node via pre-order traversal.
    Mutates tree in place and returns it.

    REQUIRES: tree is a valid ExprTree.
    ENSURES: Every node has a unique node_id >= starting_id, assigned in pre-order.
    """
    counter = [starting_id]  # mutable container for closure

    def _assign(node: ExprTree) -> None:
        node.node_id = counter[0]
        counter[0] += 1
        for child in node.children:
            _assign(child)

    _assign(tree)
    return tree
```

**Key implementation notes**:
- Both functions mutate the tree in place. This matches the pipeline flow: `constr_to_tree()` creates the tree, then `recompute_depths()` and `assign_node_ids()` annotate it.
- `assign_node_ids` uses pre-order traversal, matching the examples in the spec (root gets id 0, first child gets id 1, etc.).
- These are called during extraction (per-declaration processing step 3-4).

---

### Step 9: Tree Validation (`src/coq_search/tree/validation.py`)

Implement invariant checking from Section 3 (Structural Invariants) and Section 7 (Error Specification).

```python
from coq_search.models import (
    ExprTree, NodeLabel,
    LApp, LProd, LLambda, LLetIn, LProj,
    LRel, LVar, LSort, LConst, LInd, LConstruct, LInt, LCseVar,
    LCase, LFix, LCoFix,
)
from coq_search.tree.traversal import dfs_preorder
import logging

logger = logging.getLogger(__name__)

# Labels that must be leaves (0 children)
LEAF_LABELS = (LRel, LVar, LSort, LConst, LInd, LConstruct, LInt, LCseVar)


class TreeValidationError(Exception):
    """Raised when a tree violates structural invariants."""
    pass


def validate_tree(tree: ExprTree, declaration_name: str = "<unknown>") -> list[str]:
    """Check all structural invariants. Returns list of violation descriptions.
    Empty list means the tree is valid.

    Does NOT raise exceptions -- returns violations for the caller to handle.
    """
    violations: list[str] = []

    seen_ids: set[int] = set()

    for node in dfs_preorder(tree):
        label = node.label
        n_children = len(node.children)

        # Child count constraints
        if isinstance(label, LApp) and n_children != 2:
            violations.append(
                f"LApp node (id={node.node_id}) has {n_children} children, expected 2"
            )
        elif isinstance(label, (LProd, LLambda)) and n_children != 2:
            violations.append(
                f"{type(label).__name__} node (id={node.node_id}) has {n_children} children, expected 2"
            )
        elif isinstance(label, LLetIn) and n_children != 2:
            violations.append(
                f"LLetIn node (id={node.node_id}) has {n_children} children, expected 2"
            )
        elif isinstance(label, LProj) and n_children != 1:
            violations.append(
                f"LProj node (id={node.node_id}) has {n_children} children, expected 1"
            )
        elif isinstance(label, LEAF_LABELS) and n_children != 0:
            violations.append(
                f"{type(label).__name__} node (id={node.node_id}) has {n_children} children, expected 0 (leaf)"
            )

        # Depth and node_id non-negativity
        if node.depth < 0:
            violations.append(f"Node id={node.node_id} has negative depth={node.depth}")
        if node.node_id < 0:
            violations.append(f"Node has negative node_id={node.node_id}")

        # node_id uniqueness
        if node.node_id in seen_ids:
            violations.append(f"Duplicate node_id={node.node_id}")
        seen_ids.add(node.node_id)

        # Depth monotonicity (children must be deeper than parent)
        for child in node.children:
            if child.depth <= node.depth:
                violations.append(
                    f"Child id={child.node_id} depth={child.depth} not greater than "
                    f"parent id={node.node_id} depth={node.depth}"
                )

    if violations:
        logger.error(
            "Tree validation failed for %s: %d violations", declaration_name, len(violations)
        )

    return violations
```

**Key implementation notes**:
- Returns a list of violations rather than raising on first error. This gives complete diagnostic information.
- The caller (extraction pipeline) decides whether to reject the tree based on non-empty violations list.
- Logs at ERROR level per the error spec ("Reject tree; log error with declaration name").

---

### Step 10: Symbol Extraction (`src/coq_search/tree/symbols.py`)

```python
from coq_search.models import ExprTree, LConst, LInd, LConstruct, SymbolSet
from coq_search.tree.traversal import dfs_preorder


def extract_symbols(tree: ExprTree) -> SymbolSet:
    """Extract all distinct fully qualified symbol names from the tree.

    Collects names from LConst, LInd, and LConstruct nodes.
    Returns a sorted, deduplicated list.

    REQUIRES: tree is a normalized ExprTree.
    ENSURES: Result is sorted lexicographically. Each symbol appears exactly once.
    """
    symbols: set[str] = set()
    for node in dfs_preorder(tree):
        label = node.label
        if isinstance(label, (LConst, LInd)):
            symbols.add(label.name)
        elif isinstance(label, LConstruct):
            symbols.add(label.name)
    return sorted(symbols)
```

This matches the pseudocode in extraction.md Section 4.3 exactly.

---

### Step 11: Serialization (`src/coq_search/tree/serialization.py`)

```python
import pickle
from coq_search.models import ExprTree


def serialize_tree(tree: ExprTree) -> bytes:
    """Serialize an ExprTree to bytes for storage in SQLite BLOB.

    Uses pickle protocol 5 as specified in storage.md Section 9.1.

    REQUIRES: tree is a valid, fully annotated ExprTree.
    ENSURES: deserialize_tree(serialize_tree(tree)) produces an identical tree.
    """
    return pickle.dumps(tree, protocol=5)


def deserialize_tree(data: bytes) -> ExprTree:
    """Deserialize an ExprTree from bytes.

    REQUIRES: data was produced by serialize_tree.
    ENSURES: Result is a valid ExprTree with all labels, children, depths, and node_ids preserved.
    """
    tree = pickle.loads(data)
    if not isinstance(tree, ExprTree):
        raise ValueError(f"Expected ExprTree, got {type(tree).__name__}")
    return tree
```

**Key implementation notes**:
- Pickle protocol 5 (Python 3.8+) supports out-of-band data and is efficient for nested objects.
- The format is internal -- never exposed over the network or to untrusted input.
- A type check on deserialization catches corruption or version mismatches.

---

### Step 12: WL Histogram Validation (`src/coq_search/tree/validation.py` -- append)

Add histogram validation to the existing validation module.

```python
from coq_search.models import WlHistogram


def validate_histogram(histogram: WlHistogram) -> list[str]:
    """Validate WL histogram invariants.

    MAINTAINS: Every value in the histogram is >= 1.
    """
    violations: list[str] = []
    for key, count in histogram.items():
        if count <= 0:
            violations.append(f"Histogram key '{key}' has non-positive count={count}")
        if not isinstance(key, str):
            violations.append(f"Histogram key {key!r} is not a string")
    return violations
```

---

### Step 13: Tree Re-exports (`src/coq_search/tree/__init__.py`)

```python
from .traversal import dfs_preorder, dfs_postorder, leaves, node_count
from .construction import recompute_depths, assign_node_ids
from .validation import validate_tree, validate_histogram, TreeValidationError
from .symbols import extract_symbols
from .serialization import serialize_tree, deserialize_tree

__all__ = [
    "dfs_preorder", "dfs_postorder", "leaves", "node_count",
    "recompute_depths", "assign_node_ids",
    "validate_tree", "validate_histogram", "TreeValidationError",
    "extract_symbols",
    "serialize_tree", "deserialize_tree",
]
```

---

## Testing Plan

All tests live under `test/` mirroring the `src/` structure:

```
test/
  coq_search/
    models/
      test_node_labels.py
      test_expr_tree.py
      test_scored_result.py
    tree/
      test_traversal.py
      test_construction.py
      test_validation.py
      test_symbols.py
      test_serialization.py
```

### Test Cases by Module

#### `test_node_labels.py`

1. **Equality**: `LProd() == LProd()`, `LConst("foo") == LConst("foo")`, `LConst("foo") != LConst("bar")`
2. **Hashing**: `hash(LProd()) == hash(LProd())`, `hash(LConst("a")) == hash(LConst("a"))`
3. **Dict key usage**: Use `NodeLabel` instances as dict keys, verify correct lookup
4. **Immutability**: Attempting to set an attribute on a frozen dataclass raises `FrozenInstanceError`
5. **All 16 variants constructible**: Create one instance of each variant with valid arguments
6. **SortKind enum**: Verify `SortKind.PROP`, `SortKind.SET`, `SortKind.TYPE_UNIV` are distinct
7. **isinstance checks**: `isinstance(LConst("foo"), NodeLabel)` is True for all variants

#### `test_expr_tree.py`

1. **Leaf construction**: `ExprTree(label=LConst("foo"))` has empty children, depth=0, node_id=0
2. **Interior construction**: Build the `nat -> nat` example from the spec (Section 8) and verify structure
3. **Mutable fields**: Verify depth and node_id can be reassigned
4. **Default children**: Two different `ExprTree` instances have independent children lists (no shared mutable default)

#### `test_traversal.py`

1. **dfs_preorder on spec examples**: Build `nat -> nat` tree, verify preorder yields [LProd, LInd("nat"), LInd("nat")]
2. **dfs_preorder on S(S(O)) example**: Verify preorder yields [LApp, LConstruct(nat,1), LApp, LConstruct(nat,1), LConstruct(nat,0)]
3. **dfs_postorder**: Same trees, verify post-order sequence
4. **leaves**: Verify only leaf nodes returned
5. **node_count**: Verify `nat -> nat` returns 3, `S(S(O))` returns 5
6. **Single-node tree**: dfs_preorder yields exactly one node
7. **Empty children**: Leaf node yields just itself

#### `test_construction.py`

1. **recompute_depths**: Build a 3-level tree, call recompute_depths, verify root=0, children=1, grandchildren=2
2. **recompute_depths with non-zero start**: Verify starting_depth parameter works
3. **assign_node_ids**: Build `nat -> nat` tree, verify ids are [0, 1, 2] in preorder
4. **assign_node_ids on S(S(O))**: Verify ids match the spec example [0, 1, 2, 3, 4]
5. **Idempotency**: Running recompute_depths twice produces the same result
6. **assign_node_ids starting_id**: Verify non-zero starting_id works

#### `test_validation.py`

1. **Valid `nat -> nat` tree**: Returns empty violations list
2. **Valid `S(S(O))` tree**: Returns empty violations list
3. **LApp with 1 child**: Returns violation
4. **LApp with 3 children**: Returns violation
5. **LProd with 1 child**: Returns violation
6. **LProj with 0 children**: Returns violation
7. **LProj with 2 children**: Returns violation
8. **Leaf node (LConst) with children**: Returns violation
9. **Negative depth**: Returns violation
10. **Negative node_id**: Returns violation
11. **Duplicate node_ids**: Returns violation
12. **Depth non-monotonic (child.depth <= parent.depth)**: Returns violation
13. **Multiple violations**: Returns all of them, not just the first
14. **Histogram with count=0**: Returns violation
15. **Histogram with negative count**: Returns violation
16. **Valid histogram**: Returns empty list
17. **Empty histogram**: Returns empty list (valid per spec)

#### `test_symbols.py`

1. **`nat -> nat` example**: Returns `["Coq.Init.Datatypes.nat"]`
2. **`S(S(O))` example**: Returns `["Coq.Init.Datatypes.nat"]` (constructors carry the inductive name)
3. **Tree with mixed LConst, LInd, LConstruct**: All names collected
4. **Tree with no symbol nodes** (e.g., only LRel): Returns empty list
5. **Deduplication**: Same symbol appearing multiple times yields one entry
6. **Sorted output**: Verify lexicographic ordering

#### `test_serialization.py`

1. **Round-trip `nat -> nat`**: serialize then deserialize, verify structural equality
2. **Round-trip `S(S(O))`**: Same
3. **Round-trip with all label types**: Build a tree containing at least one of each NodeLabel variant, serialize, deserialize, compare
4. **Type check on deserialize**: Passing non-ExprTree pickle data raises ValueError
5. **Large tree**: Create a tree with 1,000 nodes, verify round-trip

### Property-Based Testing (Hypothesis)

Excellent opportunities for property-based testing with the `hypothesis` library:

1. **NodeLabel hashing consistency**: For any randomly generated NodeLabel, `hash(label) == hash(copy_of_label)` when values match
2. **recompute_depths idempotency**: For any tree, `recompute_depths(recompute_depths(tree)) == recompute_depths(tree)` (depth values unchanged)
3. **assign_node_ids uniqueness**: For any tree, all node_ids after assignment are unique
4. **node_count matches traversal length**: `node_count(tree) == len(list(dfs_preorder(tree)))`
5. **extract_symbols is sorted and deduplicated**: For any tree, result is sorted and has no duplicates
6. **Serialization round-trip**: For any tree, `deserialize(serialize(tree))` produces structurally identical tree
7. **validate_tree passes for well-constructed trees**: For trees built using only valid construction patterns, validation returns no violations

**Hypothesis strategy for ExprTree**: Write a recursive strategy that generates trees respecting invariants (correct child counts per label type, non-negative depths, unique node_ids). Use `recompute_depths` + `assign_node_ids` to ensure well-formedness after generation.

---

## Acceptance Criteria

1. All 16 `NodeLabel` variants are constructible, frozen, hashable, and equality-comparable
2. `ExprTree` is constructible with default values and mutable for annotation
3. The two spec examples (`nat -> nat`, `S(S(O))`) can be constructed and produce correct `node_count` and `extract_symbols` results
4. `recompute_depths` produces monotonically increasing depth paths from root to leaves
5. `assign_node_ids` produces unique IDs across all nodes within a tree
6. `validate_tree` detects all invariant violations listed in Section 3 of the spec
7. `validate_tree` returns no violations for well-formed trees
8. `extract_symbols` returns a sorted, deduplicated list matching the extraction.md pseudocode
9. `serialize_tree` / `deserialize_tree` round-trips preserve all fields exactly
10. All tests pass (unit + property-based)
11. Type annotations pass `mypy --strict` (or at minimum `mypy` with no errors)
12. `from coq_search.models import *` and `from coq_search.tree import *` provide all public API names

---

## Risks and Mitigations

### Risk 1: Deep Recursion on Large Trees

**Problem**: `recompute_depths`, `assign_node_ids`, `dfs_preorder`, and `validate_tree` all use recursion. Coq expressions can be deeply nested (coq-normalization.md caps at 1,000 depth). Python's default recursion limit is 1,000.

**Mitigation**: For the initial implementation, use recursive implementations (clearer, matches spec pseudocode). Add a `sys.setrecursionlimit(5000)` guard in the tree module init, or convert critical functions to iterative (stack-based) implementations if recursion depth becomes an issue in practice. The coq-normalization spec already caps recursion at 1,000, so trees deeper than 1,000 are rejected before reaching these functions.

### Risk 2: Pickle Compatibility Across Versions

**Problem**: If the `ExprTree` or `NodeLabel` class definitions change (fields added/removed/renamed), previously pickled trees in the SQLite database become unreadable.

**Mitigation**: The storage spec mandates full re-indexing on schema version changes. When any data structure changes, bump `schema_version` in `index_meta`. This triggers a full rebuild, re-serializing all trees with the new class definitions. No backward compatibility needed for pickle data.

### Risk 3: Memory Usage for Large Libraries

**Problem**: The storage spec says WL histograms for 50K declarations are loaded into memory at startup. If ExprTree instances are also loaded, memory could be significant.

**Mitigation**: ExprTree instances are NOT loaded into memory at startup (only WL histograms and symbol sets are). Trees are deserialized on demand for TED computation, which only processes the top ~500 candidates. No mitigation needed for this task specifically, but downstream tasks should be aware.

### Risk 4: `NodeLabel` Base Class Not Enforced as Abstract

**Problem**: Nothing prevents `NodeLabel()` from being instantiated directly. Python does not have sealed classes.

**Mitigation**: The docstring says "Do not instantiate directly." Add a runtime guard in `NodeLabel.__init_subclass__` or use `ABC` from `abc` module if stricter enforcement is desired. For the initial implementation, the docstring warning is sufficient -- all production code uses the specific subclasses via type annotations and isinstance checks.

### Risk 5: `LLetIn` Children Ambiguity

**Problem**: The spec says `LLetIn` has 2 children (value, body), but Coq's `LetIn` has 3 sub-terms (value, type_annotation, body). The spec feedback file notes this ambiguity.

**Mitigation**: This task implements the data structures as specified (2 children for LLetIn). The coq-normalization task will handle the mapping from 3-argument `LetIn` to 2-child `LLetIn` by discarding the type annotation. Document this assumption in `validation.py` with a comment.

### Risk 6: No `pyproject.toml` or Build Configuration

**Problem**: No project configuration exists yet. Import paths like `from coq_search.models import ...` require the package to be installed or the `src/` directory to be on `sys.path`.

**Mitigation**: Create a minimal `pyproject.toml` as part of Step 1 (or as a prerequisite task). Use a `[project]` table with `name = "coq-search"` and `[tool.setuptools.packages.find]` pointing to `src/`. For development, use `pip install -e .` (editable install). This is project scaffolding and may be split into its own task if preferred.
