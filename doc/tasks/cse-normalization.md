# Task: Implement CSE Normalization

## Overview

Implement Common Subexpression Elimination (CSE) normalization as specified in `specification/cse-normalization.md`. CSE reduces expression tree size by replacing repeated non-constant subexpressions with fresh `LCseVar` leaf nodes, recovering the DAG structure that is lost when Coq kernel terms are serialized to trees.

CSE is applied after Coq normalization (`coq_normalize`) and before any retrieval channel processing. It improves retrieval quality by: (1) making WL histograms more discriminating when duplicated boilerplate is collapsed, and (2) making TED computation feasible for expressions that would otherwise exceed the 50-node threshold.

The algorithm is a 3-pass tree transformation: hash every subtree, count subtree frequencies, then replace duplicated non-constant subtrees with fresh variables.

## Dependencies

The following must be implemented before CSE normalization:

1. **Data structures** (`specification/data-structures.md`): The `ExprTree`, `NodeLabel`, and all label variants (`LRel`, `LVar`, `LSort`, `LProd`, `LLambda`, `LLetIn`, `LApp`, `LConst`, `LInd`, `LConstruct`, `LCase`, `LFix`, `LCoFix`, `LProj`, `LInt`, `LCseVar`) must exist as Python classes.

2. **Tree utility functions** (`specification/coq-normalization.md`): `recompute_depths()` and `assign_node_ids()` must be available, as they are called after CSE to restore tree invariants.

3. **Coq normalization** (`specification/coq-normalization.md`): CSE consumes the output of `coq_normalize()`. While CSE can be developed in parallel (it operates on `ExprTree` regardless of how the tree was produced), integration testing requires working Coq normalization.

## Module Structure

```
src/
  wily_rooster/
    normalization/
      __init__.py
      cse.py              # CSE algorithm: hash_subtree, count_frequencies, cse_replace, cse_normalize
    tree/
      __init__.py
      expr_tree.py         # ExprTree, NodeLabel classes (from data-structures spec)
      tree_utils.py        # recompute_depths, assign_node_ids
test/
  test_cse.py              # All CSE tests
```

The CSE module (`src/wily_rooster/normalization/cse.py`) exports one public function:

```python
def cse_normalize(tree: ExprTree) -> ExprTree:
    """Apply CSE normalization to an expression tree.

    Returns a new tree with repeated non-constant subtrees replaced
    by LCseVar leaf nodes. Depths and node_ids are recomputed on the result.
    """
```

## Implementation Steps

### Step 1: Define the tag and string representation functions

Create two helper functions used by the hashing pass.

**`label_tag(label: NodeLabel) -> str`**

Returns a short unique prefix string for each label variant. Define a complete mapping:

| Label | Tag |
|-------|-----|
| `LRel` | `"Rel"` |
| `LVar` | `"Var"` |
| `LSort` | `"Sort"` |
| `LProd` | `"Prod"` |
| `LLambda` | `"Lam"` |
| `LLetIn` | `"Let"` |
| `LApp` | `"App"` |
| `LConst` | `"Const"` |
| `LInd` | `"Ind"` |
| `LConstruct` | `"Constr"` |
| `LCase` | `"Case"` |
| `LFix` | `"Fix"` |
| `LCoFix` | `"CoFix"` |
| `LProj` | `"Proj"` |
| `LInt` | `"Int"` |
| `LCseVar` | `"CseVar"` |

Implementation: use `isinstance` checks or a dispatch dict keyed on `type(label)`.

**`label_to_string(label: NodeLabel) -> str`**

Returns the payload portion of a label as a string for hashing. For labels with no payload, return an empty string. For labels with payloads:

| Label | String |
|-------|--------|
| `LRel(index=3)` | `"3"` |
| `LVar(name="x")` | `"x"` |
| `LSort(kind=Prop)` | `"Prop"` |
| `LConst(name="Coq.Init.Logic.eq")` | `"Coq.Init.Logic.eq"` |
| `LInd(name="Coq.Init.Datatypes.nat")` | `"Coq.Init.Datatypes.nat"` |
| `LConstruct(name="Coq.Init.Datatypes.nat", index=1)` | `"Coq.Init.Datatypes.nat:1"` |
| `LFix(mutual_index=0)` | `"0"` |
| `LCoFix(mutual_index=0)` | `"0"` |
| `LProj(name="fst")` | `"fst"` |
| `LInt(value=42)` | `"42"` |
| `LCseVar(var_id=0)` | `"0"` |

Use `:` as the separator for `LConstruct` to avoid ambiguity with the `-` used in interior node hash construction.

### Step 2: Implement Pass 1 -- `hash_subtree`

```python
import hashlib

def hash_subtree(node: ExprTree) -> None:
    """Compute and store a content hash on every node, bottom-up.

    Mutates node.hash (a new str field) on every node in the tree.
    """
```

Algorithm:

1. Recursively hash all children first (bottom-up).
2. For leaf nodes (no children): compute `MD5(tag + label_string)` where `tag = label_tag(node.label)` and `label_string = label_to_string(node.label)`. Store as hex digest.
3. For interior nodes: compute `MD5(tag + "-" + child_hash_1 + "-" + child_hash_2 + ...)`. Store as hex digest.

Note: The spec uses raw strings for leaf hashes, but uniformly applying MD5 to all nodes (see `specification/feedback/cse-normalization.md`, Issue 2) simplifies downstream code. Use MD5 for all nodes.

The hash is stored as a temporary attribute on `ExprTree` nodes. Since `ExprTree` is a dataclass (not frozen), add a `hash` field with `default=""` or store hashes in a separate `dict[int, str]` keyed by `id(node)`. The separate dict approach avoids modifying the `ExprTree` class.

**Recommended approach**: Use a `dict[int, str]` mapping `id(node) -> hash_hex_string`, returned from `hash_subtree`. This avoids polluting the `ExprTree` dataclass with a temporary field.

```python
def hash_subtree(node: ExprTree) -> dict[int, str]:
    """Return a mapping from id(node) -> MD5 hex hash for every node in the tree."""
    hashes: dict[int, str] = {}
    _hash_subtree_recursive(node, hashes)
    return hashes

def _hash_subtree_recursive(node: ExprTree, hashes: dict[int, str]) -> str:
    tag = label_tag(node.label)
    label_str = label_to_string(node.label)

    if not node.children:
        h = hashlib.md5((tag + label_str).encode()).hexdigest()
    else:
        child_hashes = []
        for c in node.children:
            ch = _hash_subtree_recursive(c, hashes)
            child_hashes.append(ch)
        preimage = tag + "-" + "-".join(child_hashes)
        h = hashlib.md5(preimage.encode()).hexdigest()

    hashes[id(node)] = h
    return h
```

Time complexity: O(n) where n = total node count.

### Step 3: Implement Pass 2 -- `count_frequencies`

```python
def count_frequencies(node: ExprTree, hashes: dict[int, str]) -> dict[str, int]:
    """Count how many times each subtree hash appears in the tree."""
    freq: dict[str, int] = {}
    _count_recursive(node, hashes, freq)
    return freq

def _count_recursive(node: ExprTree, hashes: dict[int, str], freq: dict[str, int]) -> None:
    h = hashes[id(node)]
    freq[h] = freq.get(h, 0) + 1
    for c in node.children:
        _count_recursive(c, hashes, freq)
```

Time complexity: O(n).

### Step 4: Implement Pass 3 -- `cse_replace`

This is the most complex pass. Key design decisions:

**Mutable counter for `next_var_id`**: The spec's pseudocode passes `next_var_id` by value, which is incorrect (see feedback Issue 1). Use a mutable counter object:

```python
class _Counter:
    def __init__(self, start: int = 0):
        self.value = start

    def next(self) -> int:
        v = self.value
        self.value += 1
        return v
```

**Constant check**: The key invariant is that `LConst`, `LInd`, and `LConstruct` are never replaced. Implement as:

```python
def _is_constant_label(label: NodeLabel) -> bool:
    return isinstance(label, (LConst, LInd, LConstruct))
```

**Algorithm**:

```python
def cse_replace(
    node: ExprTree,
    freq: dict[str, int],
    hashes: dict[int, str],
    counter: _Counter,
    seen: dict[str, int],
) -> ExprTree:
    # Key invariant: never replace constants
    if _is_constant_label(node.label):
        return node

    h = hashes[id(node)]

    if freq[h] > 1:
        if h in seen:
            # Second+ occurrence: replace with CSE variable
            return ExprTree(label=LCseVar(var_id=seen[h]))
        else:
            # First occurrence: record the variable id, but keep this subtree
            seen[h] = counter.next()
            # Still process children (they may have their own CSE opportunities)
            new_children = [
                cse_replace(c, freq, hashes, counter, seen)
                for c in node.children
            ]
            return ExprTree(label=node.label, children=new_children)
    else:
        # Unique subtree: recurse into children
        new_children = [
            cse_replace(c, freq, hashes, counter, seen)
            for c in node.children
        ]
        return ExprTree(label=node.label, children=new_children)
```

Important notes:

- The function returns a new tree (does not mutate the input).
- `seen` is a shared mutable dict mapping `hash -> var_id`. It is populated on first encounter and consulted on subsequent encounters.
- `counter` is a shared mutable counter. It must be shared across the entire tree traversal so that each distinct CSE variable gets a unique id.
- Children are processed left-to-right. The counter and seen dict are mutated during child processing, so order matters.
- When a constant-labeled node is encountered, it is returned as-is without examining its hash or frequency. Constants that are leaves have no children to recurse into. Constants that hypothetically had children (which doesn't happen per the data model -- `LConst`, `LInd`, `LConstruct` are all leaves) would still be skipped entirely.

### Step 5: Implement the top-level `cse_normalize` function

```python
def cse_normalize(tree: ExprTree) -> ExprTree:
    """Apply CSE normalization to an expression tree.

    Returns a new tree with repeated non-constant subtrees replaced
    by LCseVar leaf nodes. Depths and node_ids are recomputed on the result.
    Returns the input unchanged for empty or single-node trees.
    """
    # Edge case: empty tree (None root -- depends on how empty is represented)
    if tree is None:
        return tree

    # Edge case: single node -- no duplicates possible
    if not tree.children:
        return tree

    # Pass 1: hash every subtree
    hashes = hash_subtree(tree)

    # Pass 2: count frequencies
    freq = count_frequencies(tree, hashes)

    # Pass 3: replace duplicates
    counter = _Counter(start=0)
    seen: dict[str, int] = {}
    result = cse_replace(tree, freq, hashes, counter, seen)

    # Restore tree invariants
    result = recompute_depths(result)
    result = assign_node_ids(result)

    return result
```

### Step 6: Recompute depths and node IDs

These functions are shared with Coq normalization and should live in `tree_utils.py`. They are not CSE-specific but are called as the final step of CSE normalization.

```python
def recompute_depths(node: ExprTree, depth: int = 0) -> ExprTree:
    """Return a new tree with depth fields set correctly."""
    new_children = [recompute_depths(c, depth + 1) for c in node.children]
    return ExprTree(label=node.label, children=new_children, depth=depth)

def assign_node_ids(node: ExprTree) -> ExprTree:
    """Return a new tree with unique sequential node_ids (pre-order)."""
    counter = _Counter(0)
    return _assign_ids_recursive(node, counter)

def _assign_ids_recursive(node: ExprTree, counter: _Counter) -> ExprTree:
    nid = counter.next()
    new_children = [_assign_ids_recursive(c, counter) for c in node.children]
    return ExprTree(label=node.label, children=new_children, depth=node.depth, node_id=nid)
```

## Testing Plan

All tests go in `test/test_cse.py`. Use pytest.

### Unit Tests for Helpers

1. **`test_label_tag_all_variants`**: Verify `label_tag()` returns the correct string for every one of the 16 label types.

2. **`test_label_to_string_all_variants`**: Verify `label_to_string()` returns the correct payload string for every label type, including empty string for payload-free labels.

3. **`test_is_constant_label`**: Verify that `LConst`, `LInd`, `LConstruct` return `True`, and all other labels return `False`.

### Unit Tests for Pass 1 (Hashing)

4. **`test_hash_single_leaf`**: A single `LInd("nat")` leaf gets a consistent MD5 hash.

5. **`test_hash_identical_leaves_same_hash`**: Two separate `LInd("nat")` nodes produce the same hash string.

6. **`test_hash_different_leaves_different_hash`**: `LInd("nat")` and `LInd("bool")` produce different hashes.

7. **`test_hash_interior_node`**: An `LApp` node with two `LInd` children produces a hash that depends on the children's hashes.

8. **`test_hash_structural_equality`**: Two independently constructed but structurally identical subtrees (`App(Ind("list"), Ind("nat"))`) produce the same hash.

9. **`test_hash_structural_difference`**: `App(Ind("list"), Ind("nat"))` and `App(Ind("list"), Ind("bool"))` produce different hashes.

### Unit Tests for Pass 2 (Frequency Counting)

10. **`test_freq_no_duplicates`**: A tree with all unique subtrees has all frequencies = 1.

11. **`test_freq_with_duplicates`**: The `list nat -> list nat` example has the `App(Ind("list"), Ind("nat"))` hash appearing with frequency 2, and each `Ind` leaf hash appearing with frequency >= 2.

12. **`test_freq_single_node`**: A single leaf has frequency 1.

### Unit Tests for Pass 3 (Replacement)

13. **`test_replace_no_duplicates`**: When all frequencies are 1, the tree is returned structurally unchanged.

14. **`test_replace_constant_not_replaced`**: Duplicated `LInd` nodes are not replaced even though their frequency > 1 (key invariant).

15. **`test_replace_compound_duplicate`**: A duplicated `LApp` subtree is replaced on its second occurrence.

16. **`test_replace_first_occurrence_kept`**: The first occurrence of a duplicated subtree is preserved (with children recursed), not replaced.

17. **`test_replace_var_ids_unique`**: When multiple distinct subtrees are replaced, each gets a unique `var_id` (0, 1, 2, ...).

18. **`test_replace_nested_duplicates`**: When a duplicated subtree contains a sub-duplicated subtree, both levels of CSE are applied correctly.

### Integration Tests (Spec Examples)

19. **`test_example_nat_arrow_nat_arrow_nat`** (Spec Example 1):
    - Input: `Prod(Ind("nat"), Prod(Ind("nat"), Ind("nat")))` (nat -> nat -> nat)
    - Expected: Tree returned unchanged. All three `Ind("nat")` nodes are constants, so the key invariant prevents replacement.
    - Node count: 5 in, 5 out.

20. **`test_example_list_nat_arrow_list_nat`** (Spec Example 2):
    - Input: `Prod(App(Ind("list"), Ind("nat")), App(Ind("list"), Ind("nat")))` (list nat -> list nat)
    - Expected: Second `App(Ind("list"), Ind("nat"))` replaced by `CseVar(0)`.
    - Output: `Prod(App(Ind("list"), Ind("nat")), CseVar(0))`
    - Node count: 7 in, 4 out.

21. **`test_example_nat_arrow_bool`** (Spec Example 3):
    - Input: `Prod(Ind("nat"), Ind("bool"))` (nat -> bool)
    - Expected: No duplicated non-constant subtrees. Tree returned unchanged.

### Edge Case Tests

22. **`test_empty_tree`**: If the tree is `None` (or however empty is represented), return it unchanged.

23. **`test_single_node_tree`**: A single `LConst("foo")` node. No children, no duplicates. Returned unchanged.

24. **`test_all_constant_nodes`**: A tree consisting entirely of `LConst`, `LInd`, `LConstruct` nodes. No replacements made regardless of duplication.

25. **`test_depth_recomputed_after_cse`**: After CSE replacement, all `depth` values are correct. The `CseVar` leaf that replaces a deep subtree has the correct depth.

26. **`test_node_ids_recomputed_after_cse`**: After CSE replacement, `node_id` values are contiguous (0, 1, 2, ..., n-1) in pre-order.

27. **`test_large_tree_performance`**: A synthetic tree with 1000+ nodes completes CSE normalization in under 1 second. This validates O(n) time complexity.

28. **`test_deeply_nested_tree`**: A tree with depth 500+ (e.g., chain of `LApp` nodes) does not hit Python's default recursion limit. If it does, this signals the need for an iterative implementation. (Note: Python's default recursion limit is 1000; the spec mentions Coq normalization caps at 1000. CSE should handle trees up to that depth.)

### Hash Consistency Tests

29. **`test_hash_deterministic`**: Hashing the same tree twice produces the same hash map.

30. **`test_hash_independent_of_depth_and_node_id`**: Two structurally identical trees with different `depth` and `node_id` values produce the same hashes (hashing is based on labels and structure, not metadata).

## Acceptance Criteria

1. `cse_normalize()` passes all spec examples exactly:
   - `nat -> nat -> nat`: unchanged (constant invariant)
   - `list nat -> list nat`: second `App(Ind("list"), Ind("nat"))` replaced by `CseVar(0)`, node count 7 -> 4
   - `nat -> bool`: unchanged (no duplicates)

2. The key invariant holds: no `LConst`, `LInd`, or `LConstruct` node is ever replaced by `LCseVar`, regardless of duplication.

3. `LCseVar` `var_id` values are unique and sequential (0, 1, 2, ...) within a single tree.

4. Output trees have correct `depth` (monotonically increasing root-to-leaf) and contiguous `node_id` values.

5. The algorithm is O(n) in time and space (three linear passes plus MD5 hashing).

6. Empty trees and single-node trees are returned unchanged.

7. All 30 tests pass.

8. No mutations to the input tree -- `cse_normalize` returns a new tree.

## Risks and Mitigations

### Risk 1: MD5 Hash Collisions

**Risk**: Two structurally different subtrees produce the same MD5 hash, causing incorrect CSE replacement.

**Likelihood**: Extremely low. MD5's 128-bit output space gives a collision probability of ~2^-64 via birthday attack. For typical Coq expression trees (< 10K nodes, so < 10K distinct hashes), the probability is negligible (~10^-31).

**Mitigation**: Accept the risk as the spec does. If paranoia is warranted, add an optional structural equality check when a hash match is found in `seen`, but this changes the algorithm from O(n) to O(n^2) in the worst case. Not recommended unless collisions are observed in practice.

### Risk 2: Python Recursion Limit on Deep Trees

**Risk**: Deeply nested trees (depth > 1000) cause `RecursionError` in Python.

**Likelihood**: Moderate. Coq terms with deeply nested applications (e.g., long chains of `App`) after currification can approach this depth.

**Mitigation**: The Coq normalization spec already caps recursion at 1000 depth, so CSE should never see trees deeper than 1000. As a defense-in-depth measure, set `sys.setrecursionlimit()` appropriately at module initialization, or convert the recursive implementation to iterative (using an explicit stack) if depth > 500 trees are common.

### Risk 3: Performance on Large Trees

**Risk**: Trees with many thousands of nodes could make the three passes slow, especially due to MD5 computation.

**Likelihood**: Low. MD5 is fast (hundreds of MB/s), and each node is hashed exactly once. The bottleneck would be Python overhead on very large trees (> 50K nodes).

**Mitigation**: The WL screening threshold is 50 nodes for TED, and typical Coq declarations have 10-200 nodes. Trees above ~1000 nodes are rare. Profile before optimizing. If needed, consider using `hashlib.md5` with precomputed byte strings to reduce Python object overhead.

### Risk 4: Mutable State Correctness in Pass 3

**Risk**: The shared mutable `counter` and `seen` dict are modified during left-to-right child traversal. If the traversal order changes (e.g., parallelization), CSE variable assignment becomes non-deterministic.

**Likelihood**: Low for the initial serial implementation. Higher if the code is later parallelized.

**Mitigation**: Document that Pass 3 traversal is strictly left-to-right, pre-order. Add a comment warning against parallelization. The serial traversal order is deterministic, so `var_id` assignment is deterministic for a given tree.

### Risk 5: Hash Independence from Metadata

**Risk**: If hashing accidentally incorporates `depth` or `node_id` fields, structurally identical subtrees at different positions would get different hashes, defeating CSE.

**Mitigation**: The hashing function must use only `label` and `children` (recursively). Add a specific test (test 30) that verifies identical structures at different depths produce the same hash.
