# Implementation Plan: Coq Expression Normalization

**Specification:** [specification/coq-normalization.md](../specification/coq-normalization.md)
**Architecture:** [doc/architecture/coq-normalization.md](../doc/architecture/coq-normalization.md)
**Feedback:** [specification/feedback/coq-normalization.md](../specification/feedback/coq-normalization.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, NodeLabel hierarchy, SortKind, `recompute_depths`, `assign_node_ids`, `node_count`
- [cse-normalization.md](../specification/cse-normalization.md) — `cse_normalize` (downstream consumer, not a dependency of this plan)

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, complete `NodeLabel` hierarchy (all 16 concrete subtypes including `LRel`, `LSort`, `LLambda`, `LLetIn`, `LApp`, `LConst`, `LInd`, `LConstruct`, `LCase`, `LFix`, `LCoFix`, `LProj`, `LInt`, `LCseVar`, `LVar`), `SortKind` enum, utility functions (`recompute_depths`, `assign_node_ids`, `node_count`).

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **ConstrNode intermediate type is defined in this plan (T1)** even though the spec does not mention it. The extraction spec (extraction.md T12) and the architecture doc (coq-normalization.md) both reference a `ConstrNode` type that carries pre-resolved FQNs. This plan defines it as the input contract for `constr_to_tree()`. See feedback Issue 4.
- **The complete Constr.t variant mapping is implemented in T3** despite the spec only covering 6 transforms explicitly. The architecture doc and data-structures spec together define mappings for all variants (Rel, Sort, Lambda, Prod, LetIn, Case, Fix, CoFix, Var). See feedback Issue 3.
- **Label names follow data-structures.md** (`LLambda`, `LLetIn`) rather than the spec pseudocode (`LAbs`, `LLet`). See feedback Issue 1.
- **Int/Float handling follows data-structures.md `LInt` type** for integers. Float handling is deferred pending spec clarification (feedback Issue 2). If a `Float` variant is encountered during normalization, it is treated as an unrecognized variant and the declaration is skipped with a warning.
- **LetIn discards the type annotation** per the architecture doc, keeping only `[value_tree, body_tree]` as children. See feedback Issue 6.
- **`recompute_depths` and `assign_node_ids` are placed in the data-structures module** rather than the normalization module, since data-structures.md Section 7 defines their contracts and they are also called by CSE normalization. If a data-structures task plan already implements these, this plan's T4 defers to it.

---

## Tasks

### Phase A: Input Types and Error Handling

- [ ] **T1: ConstrNode intermediate representation** — Define the parsed intermediate type that `constr_to_tree()` consumes
  - **Traces to:** [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization); [extraction.md](../specification/extraction.md) Section 5.4
  - **Depends on:** None
  - **Produces:** `src/coq_search/normalization/constr_node.py`
  - **Done when:** A `ConstrNode` base type exists with frozen-dataclass subtypes for all 17 `Constr.t` variants: `CRel(index: int)`, `CVar(name: str)`, `CSort(sort_value: str)`, `CProd(name: str | None, type: ConstrNode, body: ConstrNode)`, `CLambda(name: str | None, type: ConstrNode, body: ConstrNode)`, `CLetIn(name: str | None, value: ConstrNode, type: ConstrNode, body: ConstrNode)`, `CApp(func: ConstrNode, args: list[ConstrNode])`, `CConst(fqn: str)`, `CInd(fqn: str)`, `CConstruct(ind_fqn: str, index: int)`, `CCase(ind_fqn: str, scrutinee: ConstrNode, branches: list[ConstrNode])`, `CFix(rec_index: int, bodies: list[ConstrNode])`, `CCoFix(rec_index: int, bodies: list[ConstrNode])`, `CProj(proj_name: str, term: ConstrNode)`, `CCast(expr: ConstrNode, type: ConstrNode)`, `CInt(value: int)`, `CFloat(value: float)`; FQN fields (`fqn`, `ind_fqn`, `proj_name`) carry pre-resolved fully qualified names (resolution happens during extraction parsing, before normalization); all subtypes are equality-comparable; unit test verifies construction and field access for each variant

- [ ] **T2: Normalization error types** — Define custom exception types for the normalization module
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Section 11 (Error Specification); [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization)
  - **Depends on:** None
  - **Produces:** `src/coq_search/normalization/errors.py`
  - **Done when:** Exception classes defined: `NormalizationError` (base), `UnrecognizedConstrVariantError(variant_tag: str, decl_name: str)`, `VarInClosedTermError(var_name: str, decl_name: str)`, `RecursionDepthExceededError(decl_name: str, depth: int)`, `EmptyTreeError(decl_name: str)`; all are subclasses of `NormalizationError`; each carries context fields accessible as attributes; unit test verifies each exception can be raised, caught by base class, and has correct message formatting

### Phase B: Core Tree Construction

- [ ] **T3: constr_to_tree() — Complete Constr.t to ExprTree conversion** — Implement the main tree construction function handling all Constr.t variants with inline transforms
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Sections 3–9; [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization) AC: "it handles at minimum: application form, type casts, universe annotations, projections, and notation expansion"
  - **Depends on:** T1, T2, data-structures tasks (ExprTree, NodeLabel types, SortKind)
  - **Produces:** `src/coq_search/normalization/constr_to_tree.py`
  - **Done when:** `constr_to_tree(node: ConstrNode, decl_name: str = "", _depth_counter: int = 0) -> ExprTree` converts a `ConstrNode` to an `ExprTree` by recursive traversal, applying all Coq-specific transforms inline. The function handles every `ConstrNode` variant as follows:
    - `CRel(n)` → `ExprTree(LRel(n))` leaf
    - `CVar(name)` → raises `VarInClosedTermError` (Var should not occur in closed `.vo` terms, per architecture doc)
    - `CSort(sort_value)` → `ExprTree(LSort(kind))` leaf, mapping `"Prop"`/`"SProp"` → `SortKind.PROP`, `"Set"` → `SortKind.SET`, `"Type"` (any universe) → `SortKind.TYPE_UNIV`
    - `CProd(name, type, body)` → `ExprTree(LProd(), [type_tree, body_tree])`, binder name discarded
    - `CLambda(name, type, body)` → `ExprTree(LLambda(), [type_tree, body_tree])`, binder name discarded
    - `CLetIn(name, value, type, body)` → `ExprTree(LLetIn(), [value_tree, body_tree])`, binder name and type annotation discarded
    - `CApp(func, args)` → currified binary `LApp` nodes per spec Section 3: left-fold `App(App(f, a1), a2)` for args `[a1, a2]`; 0-arg `CApp(f, [])` returns `f` tree unchanged (spec Section 11)
    - `CConst(fqn)` → `ExprTree(LConst(fqn))` leaf; universe already erased in ConstrNode (spec Section 5)
    - `CInd(fqn)` → `ExprTree(LInd(fqn))` leaf; universe already erased
    - `CConstruct(ind_fqn, index)` → `ExprTree(LConstruct(ind_fqn, index))` leaf; carries parent inductive FQN (spec Section 5)
    - `CCase(ind_fqn, scrutinee, branches)` → `ExprTree(LCase(), [scrutinee_tree, *branch_trees])`; 0-branch case valid for empty types
    - `CFix(rec_index, bodies)` → `ExprTree(LFix(rec_index), [body_trees...])`; names and types already discarded in ConstrNode
    - `CCoFix(rec_index, bodies)` → `ExprTree(LCoFix(rec_index), [body_trees...])`
    - `CProj(proj_name, term)` → `ExprTree(LProj(proj_name), [term_tree])` (spec Section 6)
    - `CCast(expr, type)` → recurse into `expr`, discard cast entirely (spec Section 4); recursive stripping handles nested casts
    - `CInt(value)` → `ExprTree(LInt(value))` leaf
    - `CFloat(value)` → raises `UnrecognizedConstrVariantError` (deferred pending spec clarification, see feedback Issue 2)
    - Unrecognized variant → raises `UnrecognizedConstrVariantError` with variant tag and declaration name
    Recursion depth tracked via `_depth_counter`; capped at 1,000 per spec Section 11; raises `RecursionDepthExceededError` if exceeded; Python `sys.setrecursionlimit` set appropriately or an iterative stack-based approach used

### Phase C: Pipeline Orchestration

- [ ] **T4: coq_normalize() — Full normalization pipeline** — Orchestrate the complete normalization pipeline from ConstrNode to ready-for-CSE ExprTree
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Section 10; [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization) AC: "GIVEN a Coq expression at indexing time WHEN it is stored THEN it is normalized"
  - **Depends on:** T3, data-structures tasks (`recompute_depths`, `assign_node_ids`)
  - **Produces:** `src/coq_search/normalization/pipeline.py`
  - **Done when:** `coq_normalize(constr_node: ConstrNode, decl_name: str = "") -> ExprTree` performs the three-step pipeline from spec Section 10: (1) `constr_to_tree(constr_node, decl_name)` — raw conversion with all inline transforms, (2) `recompute_depths(tree)` — set depth on all nodes (root=0, children=parent.depth+1), (3) `assign_node_ids(tree)` — set unique node_id on all nodes in pre-order traversal; returns the normalized tree ready for CSE normalization; raises `NormalizationError` subclasses on fatal conversion errors; if `constr_to_tree` produces an empty/degenerate tree, raises `EmptyTreeError`; the function is stateless and deterministic — identical input always produces identical output

### Phase D: Package Structure

- [ ] **T5: Normalization package scaffolding** — Create the normalization subpackage and test directories
  - **Traces to:** Project setup
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/normalization/__init__.py`, `tests/normalization/__init__.py`
  - **Done when:** `from coq_search.normalization import coq_normalize, ConstrNode, NormalizationError` works; `from coq_search.normalization.constr_to_tree import constr_to_tree` works; `from coq_search.normalization.errors import NormalizationError` works; `pytest` discovers tests under `tests/normalization/`; the `__init__.py` exports: `coq_normalize`, `ConstrNode`, `NormalizationError`, `constr_to_tree`

### Phase E: Unit Tests

- [ ] **T6: Unit tests — ConstrNode construction** — Test all ConstrNode variants
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Sections 3–9 (all variants must be representable)
  - **Depends on:** T1
  - **Produces:** `tests/normalization/test_constr_node.py`
  - **Done when:** Tests cover construction of every `ConstrNode` variant; tests verify field access for payload variants (`CRel.index`, `CConst.fqn`, `CConstruct.ind_fqn`, `CConstruct.index`, `CSort.sort_value`, `CProj.proj_name`, `CInt.value`); tests verify that FQN fields accept fully qualified names; tests verify equality comparison for variants with identical payloads

- [ ] **T7: Unit tests — currification** — Test n-ary App to binary App conversion
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Section 3; Section 12 (currification example)
  - **Depends on:** T3
  - **Produces:** `tests/normalization/test_currification.py`
  - **Done when:** Tests cover: `CApp(f, [a, b, c])` produces 3 nested binary `LApp` nodes per spec Section 12 example — structure is `App(App(App(f_tree, a_tree), b_tree), c_tree)`; `CApp(f, [a])` produces single `LApp` with 2 children `[f_tree, a_tree]`; `CApp(f, [])` (0-arg degenerate) returns `f_tree` unchanged per spec Section 11; node count for n-arg App increases from 1 App to n App nodes; every `LApp` in output has exactly 2 children; combined cast+app `CCast(CApp(f, [a, b]), type)` strips cast then currifies

- [ ] **T8: Unit tests — cast stripping** — Test Cast node removal
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Section 4; Section 12 (cast stripping example)
  - **Depends on:** T3
  - **Produces:** `tests/normalization/test_cast_stripping.py`
  - **Done when:** Tests cover: `CCast(CApp(f, [a]), type)` produces `LApp(f_tree, a_tree)` — cast discarded per spec Section 12 example; nested casts `CCast(CCast(expr, t1), t2)` produce just `expr_tree` (recursive stripping); cast at root level produces the inner expression's tree; cast stripping does not affect child count of parent nodes; no `LCast` or cast-derived node appears in any output tree

- [ ] **T9: Unit tests — universe erasure and FQN handling** — Test that universe annotations are erased and names are fully qualified
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Sections 5, 8; Section 12 (universe erasure example)
  - **Depends on:** T3
  - **Produces:** `tests/normalization/test_universe_and_fqn.py`
  - **Done when:** Tests cover: `CConst("Coq.Init.Logic.eq")` produces `LConst("Coq.Init.Logic.eq")` per spec Section 12 — FQN preserved, no universe in label; `CInd("Coq.Init.Datatypes.nat")` produces `LInd("Coq.Init.Datatypes.nat")`; `CConstruct("Coq.Init.Datatypes.nat", 1)` produces `LConstruct("Coq.Init.Datatypes.nat", 1)` — carries parent inductive FQN and constructor index; two `CConst` nodes with the same FQN produce identical `ExprTree` labels (universe erasure means identical treatment regardless of original universe instance)

- [ ] **T10: Unit tests — projection normalization** — Test Proj to LProj conversion
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Section 6
  - **Depends on:** T3
  - **Produces:** `tests/normalization/test_projection.py`
  - **Done when:** Tests cover: `CProj("field_name", term)` produces `ExprTree(LProj("field_name"), [term_tree])` with exactly 1 child; projection name is preserved in the label; two projections with the same name produce matching labels

- [ ] **T11: Unit tests — Sort, Rel, Lambda, Prod, LetIn, Case, Fix, CoFix mapping** — Test all remaining Constr.t variant conversions
  - **Traces to:** Architecture doc coq-normalization.md adaptation table; data-structures.md Section 3 (node type enumeration)
  - **Depends on:** T3
  - **Produces:** `tests/normalization/test_variant_mapping.py`
  - **Done when:** Tests cover:
    - `CRel(3)` → `ExprTree(LRel(3), children=[])` — leaf, de Bruijn index preserved
    - `CSort("Prop")` → `LSort(SortKind.PROP)`, `CSort("SProp")` → `LSort(SortKind.PROP)`, `CSort("Set")` → `LSort(SortKind.SET)`, `CSort("Type")` → `LSort(SortKind.TYPE_UNIV)`
    - `CLambda(name, type, body)` → `ExprTree(LLambda(), [type_tree, body_tree])` — name discarded, exactly 2 children
    - `CProd(name, type, body)` → `ExprTree(LProd(), [type_tree, body_tree])` — name discarded, exactly 2 children
    - `CLetIn(name, value, type, body)` → `ExprTree(LLetIn(), [value_tree, body_tree])` — name and type discarded, exactly 2 children
    - `CCase(ind_fqn, scrutinee, branches)` → `ExprTree(LCase(), [scrutinee_tree, *branch_trees])` — at least 1 child; 0-branch case (empty type like `False`) produces `LCase` with 1 child
    - `CFix(idx, bodies)` → `ExprTree(LFix(idx), [body_trees...])` — at least 1 child
    - `CCoFix(idx, bodies)` → `ExprTree(LCoFix(idx), [body_trees...])` — at least 1 child
    - `CInt(42)` → `ExprTree(LInt(42), children=[])` — leaf
    - `CVar("x")` → raises `VarInClosedTermError`

- [ ] **T12: Unit tests — error handling** — Test all error conditions from spec Section 11
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Section 11 (Error Specification)
  - **Depends on:** T3, T4
  - **Produces:** `tests/normalization/test_errors.py`
  - **Done when:** Tests cover every row from spec Section 11 error table:
    - Unrecognized `Constr.t` variant → raises `UnrecognizedConstrVariantError` with variant tag and declaration name
    - Name resolution failure → not applicable at this layer (FQNs pre-resolved in ConstrNode; verified by testing that the FQN from ConstrNode is used as-is)
    - Cyclic references / deep recursion → recursion depth capped at 1,000; raises `RecursionDepthExceededError` when exceeded; test with a `ConstrNode` nested to depth 1,001
    - Cast stripping produces empty tree → raises `EmptyTreeError` via `coq_normalize`
    - 0-arg App → returns `f` tree unchanged, no error; test `CApp(CConst("f"), [])`

### Phase F: Integration Tests

- [ ] **T13: Integration test — full normalization pipeline with spec examples** — Test `coq_normalize()` end-to-end against specification examples
  - **Traces to:** [coq-normalization.md](../specification/coq-normalization.md) Sections 10, 12; [Story 4.1](../doc/requirements/stories/tree-search-mcp.md#41-expression-normalization) AC: "GIVEN a query expression at search time WHEN it is processed THEN the same normalization is applied"
  - **Depends on:** T4
  - **Produces:** `tests/normalization/test_pipeline_integration.py`
  - **Done when:** Tests verify the three spec Section 12 examples end-to-end:
    - **Currification example**: `CApp(f, [a, b, c])` → 3 nested `LApp` nodes, node count increases from 1 to 3 App nodes, all nodes have correct depth and node_id values
    - **Universe erasure example**: `CConst("Coq.Init.Logic.eq")` (originally with universe `[Set]`) → `ExprTree(LConst("Coq.Init.Logic.eq"))`, identical to a second occurrence with universe `[Type]`
    - **Cast stripping example**: `CCast(CApp(f, [a]), type)` → `ExprTree(LApp, [f_tree, a_tree])`, cast wrapper gone
    Additional integration tests: (1) a representative composite term (e.g., `forall n : nat, n + n = n + n`) passes through `coq_normalize()` producing an `ExprTree` with all nodes having `depth` values set (root=0, monotonically increasing) and unique `node_id` values assigned in pre-order; (2) `node_count` matches expected count after currification and cast stripping; (3) the pipeline is deterministic — same `ConstrNode` normalized twice produces structurally identical trees; (4) the output tree satisfies all structural invariants from data-structures.md Section 3 (`LApp` has exactly 2 children, `LProd`/`LLambda` have exactly 2 children, `LLetIn` has exactly 2 children, `LProj` has exactly 1 child, leaf nodes have 0 children)
