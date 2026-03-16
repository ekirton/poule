# Implementation Plan: CSE Normalization

Implements the Common Subexpression Elimination algorithm described in [specification/cse-normalization.md](../specification/cse-normalization.md).

**Architecture:** [doc/architecture/coq-normalization.md](../doc/architecture/coq-normalization.md)
**Data model:** [doc/architecture/data-models/expression-tree.md](../doc/architecture/data-models/expression-tree.md)
**Feedback:** [specification/feedback/cse-normalization.md](../specification/feedback/cse-normalization.md) — 6 issues filed (2 high, 3 medium, 1 low)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, TreeNode, NodeLabel hierarchy, `recompute_depths`, `assign_node_ids`
- [coq-normalization.md](../specification/coq-normalization.md) — `coq_normalize()`, pipeline position (CSE runs after Coq normalization)

---

## Prerequisites

Before this component can be implemented:

1. **NodeLabel type hierarchy** — All concrete `NodeLabel` subtypes must be defined, including `LConst`, `LInd`, `LConstruct`, `LCseVar`, `LApp`, `LAbs`/`LLambda`, `LLet`/`LLetIn`, `LProj`, `LCase`, `LRel`, `LVar`, `LSort`, `LPrimitive`/`LInt`, `LProd`, `LFix`, `LCoFix`. **Blocked on feedback Issue 1** (naming conflict between specs).
2. **`ExprTree` and `TreeNode` dataclasses** — From data-structures tasks.
3. **`recompute_depths()` and `assign_node_ids()`** — From data-structures tasks (utility functions called after CSE replacement).
4. **`LPrimitive`/`LInt` constant-preservation decision** — Whether primitive literals are excluded from CSE replacement. **Blocked on feedback Issue 5.**

> **Naming convention:** This plan uses the expression-tree data model names (`LAbs`, `LLet`, `LPrimitive`) as recommended in feedback Issue 1. Adjust if the spec resolves differently.

> **Leaf hashing:** This plan assumes all nodes (leaf and interior) produce MD5 hex digest hashes, as recommended in feedback Issue 2. The spec pseudocode produces raw strings for leaves; uniform MD5 is safer and simpler.

> **Pass 3 first-occurrence semantics:** The spec pseudocode retains the first occurrence of a repeated subtree (processing its children) and replaces subsequent occurrences with `LCseVar`. Example 2 in the spec is consistent with this behavior. This plan follows the pseudocode: first occurrence kept, subsequent occurrences replaced.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **`tag()` and `to_string()` are separate functions (T1, T2)** rather than a single combined function, following the spec's pseudocode structure. The complete mapping tables are inferred from the expression-tree data model since the spec only provides partial examples (feedback Issue 4).
- **Iterative traversal** is used for all three passes (T3, T4, T5) instead of recursive traversal, to avoid Python's recursion limit on deep trees (> 1000 levels). The spec does not prescribe traversal strategy.
- **`next_var_id` is implemented as mutable shared state** (a single-element list or nonlocal variable) rather than a passed-by-value parameter, to fix the pseudocode's pass-by-value bug (feedback Issue 3).
- **The hash dict is keyed by `id(node)`** (Python object identity) rather than by node_id or positional index, since node_ids may be stale or reused during transformation. This is an implementation detail not addressed by the spec.

---

## Tasks

### Phase A: Hash Helper Functions

- [ ] **T1: `tag()` function** — Map each `NodeLabel` subtype to its canonical string tag for hash computation
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 1; [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization)
  - **Depends on:** data-structures tasks (NodeLabel hierarchy)
  - **Produces:** `tag()` function in `src/coq_search/normalization/cse.py`
  - **Done when:** `tag()` returns the correct string for all node label types: `LRel`->`"Rel"`, `LVar`->`"Var"`, `LSort`->`"Sort"`, `LConst`->`"Const"`, `LInd`->`"Ind"`, `LConstruct`->`"Construct"`, `LCseVar`->`"CseVar"`, `LPrimitive`->`"Prim"`, `LProd`->`"Prod"`, `LAbs`->`"Lambda"`, `LLet`->`"LetIn"`, `LApp`->`"App"`, `LCase`->`"Case"`, `LFix`->`"Fix"`, `LCoFix`->`"CoFix"`, `LProj`->`"Proj"`; raises `ValueError` for unrecognized label types; each label type maps to exactly one tag string

- [ ] **T2: `to_string()` function** — Convert a leaf node's label payload to a deterministic string for hash input
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 1; [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization)
  - **Depends on:** T1; data-structures tasks (NodeLabel hierarchy)
  - **Produces:** `to_string()` function in `src/coq_search/normalization/cse.py`
  - **Done when:** `to_string()` returns correct strings for all leaf label types: `LConst(name)`->name, `LInd(name)`->name, `LConstruct(name, idx)`->name+"."+str(idx), `LRel(n)`->str(n), `LSort(kind)`->kind name (`"Prop"`, `"Set"`, `"TypeUniv"`), `LCseVar(id)`->`"cse."+str(id)`, `LVar(name)`->name, `LPrimitive(value)`->str(value); is not called on interior node types; the combination `tag(label) + to_string(label)` is distinct for semantically different labels (e.g., `LRel(3)` produces `"Rel3"` vs `LPrimitive(3)` produces `"Prim3"`)

### Phase B: Three-Pass Algorithm

- [ ] **T3: Pass 1 — subexpression hashing** — Compute a structural MD5 hash for every node in the tree, bottom-up
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 1; [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization)
  - **Depends on:** T1, T2
  - **Produces:** `_hash_subtrees()` function in `src/coq_search/normalization/cse.py`
  - **Done when:** Traverses all nodes bottom-up (children before parents) using iterative post-order traversal (explicit stack) to avoid Python recursion limit; for leaf nodes computes `md5((tag(label) + to_string(label)).encode("utf-8")).hexdigest()`; for interior nodes computes `md5((tag(label) + "-" + "-".join(child_hashes)).encode("utf-8")).hexdigest()`; returns `dict[int, str]` mapping `id(node)` to 32-character lowercase hex digest for every node in the tree; two structurally identical subtrees at different positions produce the same hash; time complexity is O(n)

- [ ] **T4: Pass 2 — frequency counting** — Count occurrences of each distinct subtree hash across the entire tree
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 2; [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization)
  - **Depends on:** T3
  - **Produces:** `_count_frequencies()` function in `src/coq_search/normalization/cse.py`
  - **Done when:** Accepts the hash dict from Pass 1; returns `dict[str, int]` mapping each hash to its occurrence count; uses `collections.Counter` over the hash dict values; every node contributes exactly once; time complexity is O(n)

- [ ] **T5: Pass 3 — variable replacement** — Replace repeated non-constant subtrees with `LCseVar` nodes
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 3; Section 4 (Key Invariant); [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization)
  - **Depends on:** T3, T4; data-structures tasks (`LCseVar`, `TreeNode`)
  - **Produces:** `_cse_replace()` function in `src/coq_search/normalization/cse.py`
  - **Done when:** For each node with hash frequency >= 2 that is NOT a constant node (`LConst`, `LInd`, `LConstruct`): the first occurrence encountered (pre-order traversal) is retained with its children recursively processed, and all subsequent occurrences are replaced with `LCseVar(id)` where id is assigned sequentially from 0; constant nodes are never replaced regardless of frequency (key invariant); the root node follows normal rules (can be replaced if it has a duplicate, though this is unlikely in practice); CSE variable IDs are unique per distinct hash; uses mutable shared state for `next_var_id` and `seen` dict (not pass-by-value); constructs new `TreeNode` objects (does not mutate input tree); time complexity is O(n)

### Phase C: Public Entry Point

- [ ] **T6: Input validation** — Validate preconditions before running CSE
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 5 (Error Specification); [doc/architecture/data-models/expression-tree.md](../doc/architecture/data-models/expression-tree.md) (non-idempotent note)
  - **Depends on:** data-structures tasks (`ExprTree`, `LCseVar`)
  - **Produces:** Validation logic at the top of `cse_normalize()` in `src/coq_search/normalization/cse.py`
  - **Done when:** Returns input unchanged if the tree is empty (no nodes) or has a single node (no duplicates possible), per error spec edge cases; raises `ValueError` if any node in the input tree has an `LCseVar` label (CSE has already been applied; non-idempotent per expression-tree data model); validation traversal is O(n)

- [ ] **T7: `cse_normalize()` orchestrator** — Wire the three passes into the public entry point with post-pass metadata recomputation
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Sections 3 and 5; [doc/architecture/data-models/expression-tree.md](../doc/architecture/data-models/expression-tree.md) (normalization pipeline); [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization)
  - **Depends on:** T3, T4, T5, T6; data-structures tasks (`recompute_depths`, `assign_node_ids`, `node_count`)
  - **Produces:** `cse_normalize()` function in `src/coq_search/normalization/cse.py`; `src/coq_search/normalization/__init__.py` updated to export `cse_normalize`
  - **Done when:** `cse_normalize(tree: ExprTree) -> ExprTree` validates input (T6), runs Pass 1 (T3), Pass 2 (T4), Pass 3 (T5) in sequence, then calls `recompute_depths()` and `assign_node_ids()` on the result tree; returns a new `ExprTree` with updated `node_count`; the returned tree satisfies all structural invariants from data-structures.md; if no replacements were made (no repeated non-constant subtrees), returns a structurally equivalent tree (not necessarily the same object); the function is the sole public API of this module

### Phase D: Package Structure

- [ ] **T8: Normalization package scaffolding** — Create the normalization subpackage
  - **Traces to:** Project structure
  - **Depends on:** None (implement first, before T1-T7)
  - **Produces:** `src/coq_search/normalization/__init__.py`, `src/coq_search/normalization/cse.py`
  - **Done when:** `from coq_search.normalization.cse import cse_normalize` is importable; `from coq_search.normalization import cse_normalize` works after T7 populates the export; `pytest` discovers tests under `tests/normalization/`

### Phase E: Unit Tests

- [ ] **T9: Unit tests — `tag()` and `to_string()`** — Verify string mapping functions for all label types
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 1
  - **Depends on:** T1, T2
  - **Produces:** `tests/normalization/test_cse_helpers.py`
  - **Done when:** Tests verify: `tag()` returns correct tag for all 16 label types; `to_string()` returns correct string for all leaf label types; `to_string()` covers all `SortKind` values; combination `tag(label) + to_string(label)` is distinct for semantically different labels (e.g., `LRel(3)` vs `LPrimitive(3)`); `tag()` raises `ValueError` for unknown label types

- [ ] **T10: Unit tests — Pass 1 hash computation** — Verify structural hash correctness and uniformity
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 1
  - **Depends on:** T3
  - **Produces:** `tests/normalization/test_cse_hashing.py`
  - **Done when:** Tests verify: single leaf produces a 32-character lowercase hex string; two identical leaves produce the same hash; two different leaves produce different hashes; interior node hash depends on child order (`App(A, B)` != `App(B, A)`); two structurally identical subtrees at different tree positions produce the same hash; interior nodes with same tag but different children produce different hashes; every node in tree has an entry in the returned dict; hash is deterministic (same tree produces same hashes on repeated calls)

- [ ] **T11: Unit tests — Pass 2 frequency counting** — Verify frequency table correctness
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 2
  - **Depends on:** T4
  - **Produces:** `tests/normalization/test_cse_frequency.py`
  - **Done when:** Tests verify: single-node tree has frequency 1 for its hash; two identical `LInd("nat")` leaves in a tree produce frequency 2; repeated compound subtree (e.g., `App(Ind("list"), Ind("nat"))` appearing twice) counted correctly; unique subtrees all have frequency 1; three copies of the same subtree produce frequency 3

- [ ] **T12: Unit tests — Pass 3 replacement and constant preservation** — Verify CSE variable replacement logic
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3, Pass 3; Section 4 (Key Invariant)
  - **Depends on:** T5
  - **Produces:** `tests/normalization/test_cse_replace.py`
  - **Done when:** Tests verify: constant nodes (`LConst`, `LInd`, `LConstruct`) are never replaced regardless of frequency; repeated non-constant subtrees are replaced with `LCseVar`; first occurrence of a repeated subtree is retained (children processed), subsequent occurrences become `LCseVar`; CSE variable IDs are sequential starting from 0; original tree is not mutated (copy-on-write verified); multiple distinct repeated subtrees each get unique IDs; nested repeated subtrees: inner repetitions replaced before outer ones are considered

- [ ] **T13: Unit tests — input validation** — Verify error handling for invalid inputs
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 5 (Error Specification)
  - **Depends on:** T6
  - **Produces:** `tests/normalization/test_cse_validation.py`
  - **Done when:** Tests verify: empty tree (no nodes) returns empty tree unchanged; single-node tree returns unchanged; tree containing existing `LCseVar` nodes raises `ValueError`; tree with all-constant nodes returns unchanged (no replacements made); valid tree with repeated subtrees does not raise

- [ ] **T14: Unit tests — `cse_normalize()` end-to-end with spec examples** — Verify the full pipeline against specification examples and edge cases
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 6 (Examples)
  - **Depends on:** T7
  - **Produces:** `tests/normalization/test_cse_normalize.py`
  - **Done when:** Tests verify:
    - **Spec Example 1** (repeated constant `Ind("nat")`): tree for `nat -> nat -> nat` is returned unchanged because `LInd` is a constant type; node count remains 5
    - **Spec Example 2** (repeated compound `App(Ind("list"), Ind("nat"))`): tree for `list nat -> list nat` reduces from 7 nodes to 4; second `App(Ind("list"), Ind("nat"))` replaced with `LCseVar(0)`; result structure matches spec: `Prod(App(Ind("list"), Ind("nat")), CseVar(0))`
    - **Spec Example 3** (no duplicates): tree for `nat -> bool` returned unchanged
    - **Edge case**: single leaf returned unchanged
    - **Edge case**: tree with no repeated non-constant subtrees returned unchanged
    - **Post-CSE invariants**: `depth` values start at 0 at root and increase monotonically; `node_id` values are unique contiguous integers in pre-order; `node_count` on returned `ExprTree` matches actual traversal count

### Phase F: Integration and Performance Tests

- [ ] **T15: Integration test — CSE after Coq normalization pipeline** — Verify CSE integrates correctly as the step after `coq_normalize()`
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 2 (pipeline position); [doc/architecture/data-models/expression-tree.md](../doc/architecture/data-models/expression-tree.md) (normalization pipeline)
  - **Depends on:** T7; coq-normalization tasks (`coq_normalize`)
  - **Produces:** `tests/normalization/test_cse_integration.py`
  - **Done when:** A `ConstrNode` with repeated compound subexpressions passes through `coq_normalize()` then `cse_normalize()` producing a correctly reduced tree; a `ConstrNode` with only constant repetitions passes through both stages unchanged; output tree satisfies all structural invariants from data-structures.md; `LCseVar` nodes appear only after CSE normalization, never before; `recompute_depths` and `assign_node_ids` have been called on the final tree (verified by checking depth and node_id values)

- [ ] **T16: Performance test — large and deep tree CSE** — Verify O(n) time complexity and stack safety
  - **Traces to:** [cse-normalization.md](../specification/cse-normalization.md) Section 3 (O(n) time); Python recursion limit concern
  - **Depends on:** T7
  - **Produces:** `tests/normalization/test_cse_performance.py`
  - **Done when:** CSE normalization completes on a tree with 10,000+ nodes without stack overflow (marked `@pytest.mark.performance`); CSE normalization completes on a tree with depth > 1,000 without stack overflow (validates iterative traversal); runtime scales linearly with node count (measure on trees of 1K, 5K, 10K nodes and assert sub-quadratic growth); memory usage does not grow unboundedly beyond input tree size

---

## Dependency Graph

```
T8 (package scaffolding) — implement first
│
├── T1 (tag function)
│   └── T2 (to_string function)
│       └── T3 (Pass 1: hashing)
│           ├── T4 (Pass 2: frequency counting)
│           └── T5 (Pass 3: replacement)
│               └── T7 (cse_normalize orchestrator)
│                   ├── T6 (input validation) ──┘
│                   ├── T14 (end-to-end unit tests)
│                   ├── T15 (integration test)
│                   └── T16 (performance test)
│
├── T9 (unit tests: tag/to_string) ← T1, T2
├── T10 (unit tests: hashing) ← T3
├── T11 (unit tests: frequency) ← T4
├── T12 (unit tests: replacement) ← T5
└── T13 (unit tests: validation) ← T6
```

External dependencies (from other task plans):
- data-structures tasks: `ExprTree`, `TreeNode`, `NodeLabel` hierarchy, `recompute_depths`, `assign_node_ids`, `node_count`
- coq-normalization tasks: `coq_normalize()` (needed only for T15 integration test)
