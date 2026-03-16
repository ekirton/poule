# Implementation Plan: Core Data Structures

**Specification:** [specification/data-structures.md](../specification/data-structures.md)
**Architecture:** [doc/architecture/data-models/expression-tree.md](../doc/architecture/data-models/expression-tree.md), [doc/architecture/data-models/index-entities.md](../doc/architecture/data-models/index-entities.md)
**Feedback:** [specification/feedback/data-structures.md](../specification/feedback/data-structures.md)

**Spec dependencies:**
- [coq-normalization.md](../specification/coq-normalization.md) — defines the normalization pipeline that produces ExprTree
- [cse-normalization.md](../specification/cse-normalization.md) — defines CSE algorithm that consumes and mutates ExprTree
- [channel-wl-kernel.md](../specification/channel-wl-kernel.md) — defines WL labeling using `simplified_label` over NodeLabel types
- [storage.md](../specification/storage.md) — defines schema for serialized trees, WL histograms, symbol sets
- [channel-ted.md](../specification/channel-ted.md) — consumes ExprTree for edit distance computation

---

## Prerequisites

Before implementation of this component can begin:

1. **Python >= 3.11** with `dataclasses`, `enum`, `abc` from stdlib. No external dependencies.
2. **No upstream component dependencies** — this is the foundation layer. All other components depend on these types.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **Naming conflict between spec and architecture:** The spec uses `LLambda`, `LLetIn`, `LInt`; the architecture data model uses `LAbs`, `LLet`, `LPrimitive`. The coq-normalization spec and WL kernel spec both reference the architecture names. This plan uses the **architecture names** (`LAbs`, `LLet`, `LPrimitive`) since they are referenced by more downstream specs. See feedback Issue 1.
- **`LVar` excluded:** The spec includes `LVar` as a node label variant, but the architecture data model excludes it and coq-normalization treats `Var` as an error. This plan does not implement `LVar` in the canonical type system. See feedback Issue 2.
- **`LCase` given a payload:** The spec defines `LCase` with no payload; the architecture data model defines `LCase(ind_name: str)`. This plan follows the architecture and gives `LCase` a string payload for the inductive type name. See feedback Issue 1.
- **`LAbs` child count:** The spec says `LLambda` has 2 children (type, body); the architecture says `LAbs` has 1 child (body only). This plan follows the architecture (1 child) since the normalization pipeline discards binder types for lambda. See feedback Issue 4. **This needs architect resolution before implementation.**
- **Separate `TreeNode` and `ExprTree`:** The spec's Python example defines `ExprTree` as both the node and the tree (a single class with `label`, `children`, `depth`, `node_id`). The architecture data model defines them as separate entities (`ExprTree` with `root` and `node_count`, `TreeNode` with `label`, `children`, `depth`, `node_id`). This plan follows the architecture's two-type design since `node_count` is stored on the declaration record and `ExprTree` needs to carry it.
- **Iterative traversal for deep trees:** The spec requires handling trees up to 1000 levels deep. Python's default recursion limit is ~1000. Utility functions (`recompute_depths`, `assign_node_ids`, `node_count`) will use iterative (stack-based) traversal to avoid `RecursionError`.
- **`SortKind` enum values:** The spec maps `Prop` and `SProp` both to `PROP` (per coq-normalization architecture). The spec's `SortKind` enum has 3 members: `PROP`, `SET`, `TYPE_UNIV`.
- **Functions defined elsewhere but operating on these types:** `simplified_label` (WL kernel), `cse_tag` (CSE normalization), `node_category`/`same_category` (TED) are NOT part of this plan. They belong to their respective component task plans even though they operate on `NodeLabel` types.

---

## Tasks

### Phase A: Package Scaffold

- [ ] **T1: Package scaffold** — Create the `coq_search` Python package with the `data_structures` module
  - **Traces to:** All stories (every component imports these types)
  - **Depends on:** None
  - **Produces:** `src/coq_search/__init__.py`, `src/coq_search/data_structures.py`, `pyproject.toml` (Python >= 3.11)
  - **Done when:** `from coq_search.data_structures import ExprTree` succeeds in a Python REPL; `pytest` discovers tests under `test/`

### Phase B: Enumerations and Base Types

- [ ] **T2: SortKind enumeration** — Define the `SortKind` enum for sort classification
  - **Traces to:** Spec Section 3 (Node Labels — `LSort`); coq-normalization.md Section 6 (sort mapping: Prop+SProp -> PROP, Set -> SET, Type(u) -> TYPE_UNIV)
  - **Depends on:** T1
  - **Produces:** `SortKind` enum in `src/coq_search/data_structures.py`
  - **Done when:** `SortKind` has exactly 3 members: `PROP`, `SET`, `TYPE_UNIV`; is importable and usable in type annotations

- [ ] **T3: DeclKind enumeration** — Define the declaration kind enumeration
  - **Traces to:** index-entities.md `declarations.kind` (7 values: lemma, theorem, definition, instance, inductive, constructor, axiom); [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name) (results include kind)
  - **Depends on:** T1
  - **Produces:** `DeclKind` enum in `src/coq_search/data_structures.py`
  - **Done when:** All 7 kind values are enum members with lowercase string values; enum is importable

- [ ] **T4: NodeLabel abstract base class** — Define `NodeLabel` as an ABC that prevents direct instantiation
  - **Traces to:** Spec Section 3 (node labels must be equality-comparable and hashable); expression-tree.md (label is abstract base type, must not be instantiated directly)
  - **Depends on:** T1
  - **Produces:** `NodeLabel` ABC in `src/coq_search/data_structures.py`
  - **Done when:** `NodeLabel()` raises `TypeError`; concrete subclasses can be instantiated; base class establishes equality and hashing contract

### Phase C: Node Label Subtypes

- [ ] **T5: Leaf NodeLabel subtypes** — Define frozen dataclasses for all leaf label types
  - **Traces to:** Spec Section 3 (Node Labels table — leaf types); expression-tree.md (Leaf types table)
  - **Depends on:** T2, T4
  - **Produces:** `LRel(index: int)`, `LSort(kind: SortKind)`, `LConst(name: str)`, `LInd(name: str)`, `LConstruct(name: str, index: int)`, `LCseVar(var_id: int)`, `LPrimitive(value: int | float)` as `@dataclass(frozen=True)` subclasses of `NodeLabel` in `src/coq_search/data_structures.py`
  - **Done when:** 7 frozen dataclasses defined; `LConst("a") == LConst("a")` is `True`; `LConst("a") != LInd("a")` is `True`; all are hashable; `hash(LConst("a")) == hash(LConst("a"))`; assignment to any field raises `FrozenInstanceError`

- [ ] **T6: Interior NodeLabel subtypes** — Define frozen dataclasses for all interior label types
  - **Traces to:** Spec Section 3 (Node Labels table — interior types); expression-tree.md (Interior types table)
  - **Depends on:** T4
  - **Produces:** `LApp()`, `LAbs()`, `LLet()`, `LProd()`, `LProj(name: str)`, `LCase(ind_name: str)`, `LFix(mutual_index: int)`, `LCoFix(mutual_index: int)` as `@dataclass(frozen=True)` subclasses of `NodeLabel` in `src/coq_search/data_structures.py`
  - **Done when:** 8 frozen dataclasses defined; payload-less types are singletons for comparison (`LApp() == LApp()` is `True`); payload types compare by value (`LCase("nat") != LCase("bool")`); all are hashable and frozen

### Phase D: Tree Types

- [ ] **T7: TreeNode dataclass** — Define the mutable tree node type
  - **Traces to:** Spec Section 3 (Tree Node table); expression-tree.md (Tree Node entity)
  - **Depends on:** T5, T6
  - **Produces:** `TreeNode` dataclass in `src/coq_search/data_structures.py` with fields: `label: NodeLabel`, `children: list[TreeNode]` (default empty), `depth: int` (default 0), `node_id: int` (default 0)
  - **Done when:** `TreeNode(label=LApp(), children=[...])` creates a valid node; `children` defaults to empty list; `__eq__` compares by `label` and `children` only (ignores `depth` and `node_id` for structural equality); `__hash__` uses `id(self)` since nodes are mutable

- [ ] **T8: ExprTree dataclass** — Define the top-level expression tree wrapper
  - **Traces to:** expression-tree.md (Expression Tree entity: root + node_count); Spec Section 3 (tree's node count stored on declaration record)
  - **Depends on:** T7
  - **Produces:** `ExprTree` dataclass in `src/coq_search/data_structures.py` with fields: `root: TreeNode`, `node_count: int`
  - **Done when:** `ExprTree(root=TreeNode(label=LConst("nat")), node_count=1)` is instantiable; fields are accessible

### Phase E: Type Aliases

- [ ] **T9: Type aliases** — Define `WlHistogram`, `Symbol`, `SymbolSet` type aliases
  - **Traces to:** Spec Section 4 (WL Histogram), Section 5 (Symbol Set); storage.md Section 3.3 (wl_vectors histogram JSON), Section 3.1 (declarations symbol_set JSON)
  - **Depends on:** T1
  - **Produces:** `WlHistogram = dict[str, int]`, `Symbol = str`, `SymbolSet = list[Symbol]` in `src/coq_search/data_structures.py`
  - **Done when:** Type aliases are importable and usable in type annotations

### Phase F: Result and Response Types

- [ ] **T10: ScoredResult dataclass** — Define the internal scored result type returned by individual channels
  - **Traces to:** Spec Section 6 (ScoredResult table: decl_id, channel, rank, raw_score)
  - **Depends on:** T1
  - **Produces:** `ScoredResult` dataclass in `src/coq_search/data_structures.py`
  - **Done when:** `ScoredResult(decl_id=1, channel="wl", rank=1, raw_score=0.95)` is instantiable; all fields accessible

- [ ] **T11: SearchResult dataclass** — Define the external search result type returned by MCP tools
  - **Traces to:** [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name) (results include name, statement, type, module, kind, score); Spec Section 6
  - **Depends on:** T3
  - **Produces:** `SearchResult` dataclass in `src/coq_search/data_structures.py` with fields: `name: str`, `statement: str`, `type: str`, `module: str`, `kind: DeclKind`, `score: float`
  - **Done when:** All fields accessible; `kind` uses the `DeclKind` enum

- [ ] **T12: LemmaDetail dataclass** — Define the detailed result type for `get_lemma`
  - **Traces to:** [Story 2.6](../doc/requirements/stories/tree-search-mcp.md#26-get-lemma-details) (full details: dependencies, dependents, proof_sketch, symbols, node_count)
  - **Depends on:** T3
  - **Produces:** `LemmaDetail` dataclass in `src/coq_search/data_structures.py` with fields: `name: str`, `statement: str`, `type: str`, `module: str`, `kind: DeclKind`, `score: float`, `dependencies: list[str]`, `dependents: list[str]`, `proof_sketch: str | None`, `symbols: list[str]`, `node_count: int`
  - **Done when:** All 11 fields accessible; `score` defaults to 1.0; `dependencies` and `dependents` are `list[str]`

- [ ] **T13: Module dataclass** — Define the module listing type for `list_modules`
  - **Traces to:** [Story 2.8](../doc/requirements/stories/tree-search-mcp.md#28-list-modules) (module names and declaration counts)
  - **Depends on:** T1
  - **Produces:** `Module` dataclass in `src/coq_search/data_structures.py` with fields: `name: str`, `decl_count: int`
  - **Done when:** `Module(name="Coq.Arith.PeanoNat", decl_count=42)` is instantiable

### Phase G: Utility Functions

- [ ] **T14: recompute_depths utility** — Set depth metadata on all tree nodes
  - **Traces to:** expression-tree.md (Utility Functions: recompute_depths contract); Spec Section 3 (depth values form monotonically increasing path); normalization pipeline (called between constr_to_tree and cse_normalize, and again after cse_normalize)
  - **Depends on:** T8
  - **Produces:** `recompute_depths(tree: ExprTree) -> None` in `src/coq_search/data_structures.py`
  - **Done when:** Root gets depth=0; each child gets `parent.depth + 1`; modifies in place; handles trees up to 1000 levels deep without stack overflow (use iterative traversal); idempotent; spec example: `nat -> nat` tree `LProd(LInd("nat"), LInd("nat"))` gets depths [0, 1, 1]

- [ ] **T15: assign_node_ids utility** — Assign unique sequential IDs in pre-order traversal
  - **Traces to:** expression-tree.md (Utility Functions: assign_node_ids contract — pre-order, sequential from 0); Spec Section 3 (node_id unique within tree)
  - **Depends on:** T8
  - **Produces:** `assign_node_ids(tree: ExprTree) -> None` in `src/coq_search/data_structures.py`
  - **Done when:** Pre-order (depth-first, parent before children, left-to-right) assignment; sequential from 0; modifies in place; handles 1000-level trees; idempotent; spec example: `S (S O)` tree gets IDs [0, 1, 2, 3, 4]

- [ ] **T16: node_count utility** — Count total nodes in an expression tree
  - **Traces to:** expression-tree.md (Utility Functions: node_count contract); Spec Section 3 (node count is total of interior + leaf)
  - **Depends on:** T8
  - **Produces:** `node_count(tree: ExprTree) -> int` in `src/coq_search/data_structures.py`
  - **Done when:** Pure function, no side effects; single leaf returns 1; spec example `nat -> nat` returns 3; spec example `S (S O)` returns 5; handles 1000-level trees

### Phase H: Serialization

- [ ] **T17: ExprTree serialization** — Implement round-trip serialization of ExprTree to bytes
  - **Traces to:** expression-tree.md (Serialization section: must round-trip without data loss, preserve all node types, labels, children ordering, tree structure); storage.md Section 3.1 (constr_tree BLOB column)
  - **Depends on:** T8
  - **Produces:** `serialize_tree(tree: ExprTree) -> bytes` and `deserialize_tree(data: bytes) -> ExprTree` in `src/coq_search/data_structures.py`
  - **Done when:** `deserialize_tree(serialize_tree(t))` produces structurally equal tree for all spec example trees; preserves all label payloads, children ordering, depth, node_id, and node_count; handles trees with all 15 label types (7 leaf + 8 interior)

### Phase I: Validation

- [ ] **T18: Structural invariant validation** — Check all tree structural invariants
  - **Traces to:** Spec Section 3 (Structural Invariants table); expression-tree.md (Invariants table); Spec Section 7 (Error Specification)
  - **Depends on:** T7, T8
  - **Produces:** `validate_tree(tree: ExprTree) -> list[str]` in `src/coq_search/data_structures.py`
  - **Done when:** Returns empty list for valid trees; detects and reports: (1) `LApp` with != 2 children, (2) `LAbs` with != 1 child, (3) `LLet` with != 2 children, (4) `LProd` with != 2 children, (5) `LProj` with != 1 child, (6) `LCase` with < 1 child, (7) `LFix` with < 1 child, (8) `LCoFix` with < 1 child, (9) leaf labels with > 0 children, (10) negative depth or node_id, (11) duplicate node_ids, (12) non-monotonic depth path from root to leaf; does not raise exceptions — returns violation descriptions

- [ ] **T19: WlHistogram validation** — Check WL histogram invariants
  - **Traces to:** Spec Section 4 (WL Histogram MAINTAINS: every value >= 1); retrieval-pipeline.md (MD5 produces lowercase 32-char hex)
  - **Depends on:** T9
  - **Produces:** `validate_histogram(hist: WlHistogram) -> bool` in `src/coq_search/data_structures.py`
  - **Done when:** Returns `True` for valid histogram with lowercase hex32 keys and positive integer values; returns `False` for non-hex keys, non-lowercase keys, values <= 0; returns `True` for empty dict (valid degenerate case per spec)

### Phase J: Module Exports

- [ ] **T20: Module exports** — Configure `__all__` and convenience re-exports
  - **Traces to:** All stories (every component imports these types)
  - **Depends on:** T2-T19
  - **Produces:** `__all__` list in `src/coq_search/data_structures.py`; re-exports in `src/coq_search/__init__.py`
  - **Done when:** `from coq_search.data_structures import ExprTree, TreeNode, NodeLabel, LConst, LAbs, LCase, SortKind, ScoredResult, SearchResult, LemmaDetail, Module` works; `from coq_search import ExprTree` works as convenience import

### Phase K: Unit Tests

- [ ] **T21: Unit tests — NodeLabel hierarchy** — Test instantiation, equality, hashing, and immutability for all 15 label types
  - **Traces to:** Spec Section 3 (node labels: equality-comparable and hashable)
  - **Depends on:** T4, T5, T6
  - **Produces:** `test/test_node_labels.py`
  - **Done when:** Tests verify: (1) `NodeLabel()` raises `TypeError`, (2) all 15 concrete subtypes are instantiable, (3) frozen dataclasses are immutable (assignment raises `FrozenInstanceError`), (4) same-type same-payload labels are equal, (5) same-type different-payload labels are not equal, (6) cross-type same-payload labels are not equal (`LConst("x") != LInd("x")`), (7) all subtypes are hashable and usable as dict keys, (8) payload-less `LApp() == LApp()`, (9) `LConstruct("nat", 0) == LConstruct("nat", 0)` and `!= LConstruct("nat", 1)`, (10) `LPrimitive(42) == LPrimitive(42)` and `LPrimitive(42) != LPrimitive(3.14)`

- [ ] **T22: Unit tests — TreeNode and ExprTree construction** — Test tree construction and structural equality
  - **Traces to:** Spec Section 3 (Tree Node, Construction rule); Spec Section 8 (Examples)
  - **Depends on:** T7, T8
  - **Produces:** `test/test_expr_tree.py`
  - **Done when:** Tests verify: (1) TreeNode equality ignores `depth` and `node_id`, (2) child order matters for equality, (3) ExprTree wraps root and node_count correctly, (4) spec example `nat -> nat` tree constructable: `LProd` root with two `LInd("Coq.Init.Datatypes.nat")` children — node count 3, (5) spec example `S (S O)` tree constructable: `LApp` root with `LConstruct("Coq.Init.Datatypes.nat", 1)` and nested `LApp` children — node count 5

- [ ] **T23: Unit tests — recompute_depths** — Test depth assignment with spec examples
  - **Traces to:** expression-tree.md (recompute_depths contract); Spec Section 8 (Examples with depth values)
  - **Depends on:** T14
  - **Produces:** Tests in `test/test_expr_tree.py`
  - **Done when:** Tests verify: (1) single-node tree gets depth=0, (2) spec `nat -> nat` example: root depth=0, both children depth=1, (3) spec `S (S O)` example: depths [0, 1, 1, 2, 2], (4) idempotency (calling twice gives same result), (5) after tree mutation and re-call, depths are recalculated correctly

- [ ] **T24: Unit tests — assign_node_ids** — Test pre-order node ID assignment with spec examples
  - **Traces to:** expression-tree.md (assign_node_ids contract: pre-order, sequential from 0); Spec Section 8 (Examples with node_id values)
  - **Depends on:** T15
  - **Produces:** Tests in `test/test_expr_tree.py`
  - **Done when:** Tests verify: (1) single-node tree gets node_id=0, (2) spec `nat -> nat` example: IDs [0, 1, 2] in pre-order, (3) spec `S (S O)` example: IDs [0, 1, 2, 3, 4] in pre-order, (4) idempotency, (5) IDs are contiguous `[0, node_count-1]`

- [ ] **T25: Unit tests — node_count** — Test node counting
  - **Traces to:** expression-tree.md (node_count contract); Spec Section 8 (Examples)
  - **Depends on:** T16
  - **Produces:** Tests in `test/test_expr_tree.py`
  - **Done when:** Tests verify: (1) single leaf returns 1, (2) spec `nat -> nat` returns 3, (3) spec `S (S O)` returns 5, (4) result is always >= 1

- [ ] **T26: Unit tests — structural invariant validation** — Test all invariant checks
  - **Traces to:** Spec Section 3 (Structural Invariants); Spec Section 7 (Error Specification)
  - **Depends on:** T18
  - **Produces:** `test/test_validation.py`
  - **Done when:** Tests verify: (1) valid spec example trees return empty violations list, (2) `LApp` with 0, 1, or 3 children is detected, (3) `LAbs` with 0 or 2 children is detected, (4) `LLet` with != 2 children is detected, (5) `LProd` with != 2 children is detected, (6) `LProj` with 0 or 2 children is detected, (7) `LCase` with 0 children is detected, (8) `LFix`/`LCoFix` with 0 children is detected, (9) leaf node with children is detected (`LConst` with 1 child), (10) negative depth detected, (11) negative node_id detected, (12) duplicate node_ids detected, (13) non-monotonic depth detected, (14) `LCseVar(0)` as leaf is valid, (15) single leaf node is valid, (16) `LConstruct` as leaf is valid

- [ ] **T27: Unit tests — WlHistogram validation** — Test histogram invariant checks
  - **Traces to:** Spec Section 4 (WL Histogram MAINTAINS)
  - **Depends on:** T19
  - **Produces:** Tests in `test/test_validation.py`
  - **Done when:** Tests verify: (1) valid histogram with hex32 keys and positive values returns `True`, (2) uppercase hex key returns `False`, (3) key with wrong length returns `False`, (4) non-hex characters in key returns `False`, (5) value of 0 returns `False`, (6) negative value returns `False`, (7) empty dict returns `True`

- [ ] **T28: Unit tests — serialization round-trip** — Test ExprTree serialization fidelity
  - **Traces to:** expression-tree.md (Serialization: round-trip without data loss)
  - **Depends on:** T17, T18
  - **Produces:** `test/test_serialization.py`
  - **Done when:** Tests verify: (1) round-trip for spec `nat -> nat` example preserves all fields, (2) round-trip for spec `S (S O)` example preserves all fields, (3) single-node tree round-trips, (4) tree with all 15 label types round-trips correctly, (5) deserialized tree passes `validate_tree()`, (6) label payloads, children order, depth, node_id, node_count all preserved

- [ ] **T29: Unit tests — ScoredResult, SearchResult, LemmaDetail, Module** — Test response type construction
  - **Traces to:** Spec Section 6; [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name); [Story 2.6](../doc/requirements/stories/tree-search-mcp.md#26-get-lemma-details); [Story 2.8](../doc/requirements/stories/tree-search-mcp.md#28-list-modules)
  - **Depends on:** T10, T11, T12, T13
  - **Produces:** `test/test_response_types.py`
  - **Done when:** Tests verify: (1) `ScoredResult` instantiable with representative scores from each channel (WL cosine in [0,1], FTS BM25 negative values, MePo unbounded positive), (2) `SearchResult.kind` uses `DeclKind` enum, (3) `LemmaDetail` has all 11 fields with correct types, (4) `LemmaDetail.score` defaults to 1.0, (5) `Module` construction and field access

### Phase L: Performance Test

- [ ] **T30: Performance test — deep tree traversal** — Validate 1000-level tree handling
  - **Traces to:** expression-tree.md (trees can be deep — normalization of deeply nested Coq terms)
  - **Depends on:** T14, T15, T16
  - **Produces:** `test/test_performance.py`
  - **Done when:** 1000-level deep tree constructed; `recompute_depths`, `assign_node_ids`, and `node_count` all complete without `RecursionError`; execution time is reasonable (< 1 second for 1000-node linear chain)

---

## Dependency Graph

```
T1 (scaffold)
├── T2 (SortKind enum)
│   └── T5 (leaf labels)
├── T3 (DeclKind enum)
│   ├── T11 (SearchResult)
│   └── T12 (LemmaDetail)
├── T4 (NodeLabel ABC)
│   ├── T5 (leaf labels)
│   │   └── T7 (TreeNode)
│   │       └── T8 (ExprTree)
│   │           ├── T14 (recompute_depths)
│   │           ├── T15 (assign_node_ids)
│   │           ├── T16 (node_count)
│   │           ├── T17 (serialization)
│   │           └── T18 (validate_tree)
│   └── T6 (interior labels)
│       └── T7 (TreeNode)
├── T9 (type aliases)
│   └── T19 (validate_histogram)
├── T10 (ScoredResult)
└── T13 (Module)

T20 (exports) depends on T2-T19
Tests (T21-T30) depend on their corresponding implementation tasks
```
