# Task: Coq-Specific Normalization

Implements the six Coq-specific transforms and two post-processing passes described in [specification/coq-normalization.md](../../specification/coq-normalization.md).

---

## 1. Overview

The Coq normalization module converts raw Coq `Constr.t` kernel terms into canonical `ExprTree` form. This is the first stage of the indexing pipeline after extraction: every declaration's type expression passes through `coq_normalize()` before CSE normalization or any retrieval channel consumes it.

The transforms exist because Coq's kernel term representation differs from the uniform binary-application, no-cast form that the WL kernel and TED algorithms expect. Without normalization, structurally equivalent expressions produce different trees, degrading retrieval quality.

**Entry point**: `coq_normalize(constr_t) -> ExprTree`

**Transforms applied during `constr_to_tree()`**:
1. Cast stripping
2. N-ary App currification to binary
3. Universe erasure on Const/Ind/Construct
4. Projection normalization
5. Fully qualified name resolution
6. Section variable abstraction (handled by extraction from `.vo` files)

**Post-processing passes**:
7. `recompute_depths(tree)` -- set depth field on all nodes
8. `assign_node_ids(tree)` -- set unique node_id on all nodes

---

## 2. Dependencies

### Must be implemented first

| Dependency | Spec | Reason |
|------------|------|--------|
| Data structures (`ExprTree`, `NodeLabel` hierarchy) | [data-structures.md](../../specification/data-structures.md) | All transforms produce `ExprTree` nodes with `NodeLabel` variants |

### Must be implemented concurrently or after

| Dependent | Spec | Reason |
|-----------|------|--------|
| Extraction pipeline | [extraction.md](../../specification/extraction.md) | Provides the `Constr.t` input; calls `coq_normalize()` |
| CSE normalization | [cse-normalization.md](../../specification/cse-normalization.md) | Consumes the output of `coq_normalize()` |

### External dependencies

| Dependency | Purpose |
|------------|---------|
| coq-lsp or SerAPI (Python bindings) | Provides `Constr.t` terms and canonical name resolution |
| Coq installation with `.vo` files | Source of declarations and environment for FQN resolution |

---

## 3. Implementation Steps

### Step 0: Scaffold the module

Create `src/normalization/coq_normalize.py` with the public API:

```
coq_normalize(constr_t) -> ExprTree
```

This function orchestrates the pipeline:
1. `tree = constr_to_tree(constr_t, depth=0)`
2. `tree = recompute_depths(tree)`
3. `tree = assign_node_ids(tree)`
4. Return `tree`

Import the `ExprTree` and `NodeLabel` types from the data-structures module.

### Step 1: Define the Constr.t input representation

Before implementing transforms, define how Python receives Coq's `Constr.t` terms. coq-lsp/SerAPI serialize `Constr.t` as S-expressions or JSON. Define a parsing layer that converts the serialized form into a Python intermediate representation (e.g., tagged tuples or a simple AST).

Define an enum or tag set for `Constr.t` variants:
- `Rel`, `Var`, `Sort`, `Prod`, `Lambda`, `LetIn`, `App`, `Const`, `Ind`, `Construct`, `Case`, `Fix`, `CoFix`, `Proj`, `Cast`, `Int`

Each variant carries its own payload shape (see Coq kernel documentation).

Handle unrecognized variants by logging a warning and returning `None` (skip declaration).

### Step 2: Implement cast stripping

**Within `constr_to_tree()`**: When the current `Constr.t` node is a `Cast(expr, kind, type)`:
- Ignore `kind` and `type`
- Recurse into `expr` as if the `Cast` wrapper did not exist
- `LCast` never appears in the output `ExprTree`

**Edge case**: If stripping a cast produces an empty/null result (e.g., the inner expression itself fails conversion), log a warning and return `None` for this declaration.

**Test case (from spec)**:
- Input: `Cast(App(f, [a]), VMcast, nat_type)`
- Output: `ExprTree(label=LApp, children=[f_tree, a_tree])`

### Step 3: Implement currification of n-ary App

**Within `constr_to_tree()`**: When the current node is `App(f, [a1, a2, ..., an])`:

```python
def currify_app(f_tree, arg_trees):
    result = f_tree
    for a in arg_trees:
        result = ExprTree(label=LApp(), children=[result, a])
    return result
```

- First, recursively convert `f` and each `ai` to `ExprTree`
- Then fold them into nested binary `LApp` nodes
- **Degenerate case**: If `args` is empty, return `f_tree` unchanged (no `LApp` node created)

**Invariant**: Every `LApp` node in the output has exactly 2 children.

**Test cases**:
- `App(f, [a, b, c])` -> `App(App(App(f_tree, a_tree), b_tree), c_tree)` (3 LApp nodes)
- `App(f, [a])` -> `App(f_tree, a_tree)` (1 LApp node)
- `App(f, [])` -> `f_tree` (0 LApp nodes)

### Step 4: Implement universe erasure

**Within `constr_to_tree()`**: When constructing nodes from `Const`, `Ind`, or `Construct`:

- `Const(name, univs)` -> `ExprTree(label=LConst(canonical_fqn(name)), children=[])`
- `Ind((name, i), univs)` -> `ExprTree(label=LInd(canonical_fqn(name)), children=[])`
- `Construct(((name, i), j), univs)` -> `ExprTree(label=LConstruct(canonical_fqn(name), j), children=[])`

Discard the `univs` parameter entirely. The universe instance is never represented in the tree.

**Test case (from spec)**:
- `Const("Coq.Init.Logic.eq", [Set])` -> `ExprTree(label=LConst("Coq.Init.Logic.eq"), children=[])`
- `Const("Coq.Init.Logic.eq", [Type])` -> identical tree node

### Step 5: Implement fully qualified name resolution

All names stored in `LConst`, `LInd`, and `LConstruct` labels must be fully qualified canonical names.

Implement `canonical_fqn(name) -> str`:
- Use the Coq environment (via coq-lsp/SerAPI) to resolve a kernel name to its fully qualified form
- If resolution fails, fall back to the raw name as-is and log a warning
- The FQN is the path used in Coq's `Require Import` plus the definition name (e.g., `Coq.Arith.PeanoNat.Nat.add_comm`)

This function is called from Step 4 (universe erasure). It applies to all three constant-like node types.

**Error handling**: Name resolution failure is a dependency error. Use the raw name as-is; log a warning with the declaration name and the unresolved name.

### Step 6: Implement projection normalization

**Within `constr_to_tree()`**: When the current node is `Proj(proj, term)`:

```python
proj_name = projection_to_string(proj)
child = constr_to_tree(term, ...)
return ExprTree(label=LProj(proj_name), children=[child])
```

- `projection_to_string()` extracts the fully qualified projection name from the Coq `projection` structure
- The `LProj` node has exactly 1 child (the term being projected)

**Invariant**: Every `LProj` node has exactly 1 child.

### Step 7: Implement remaining Constr.t variant handlers

Complete the `constr_to_tree()` dispatch for all remaining variants:

| Constr.t variant | Output label | Children |
|------------------|-------------|----------|
| `Rel(n)` | `LRel(n)` | 0 (leaf) |
| `Var(name)` | `LVar(name)` | 0 (leaf) |
| `Sort(s)` | `LSort(kind)` | 0 (leaf). Map Coq sorts to `SortKind`: `Prop`->`PROP`, `Set`->`SET`, `Type`->`TYPE_UNIV` |
| `Prod(name, ty, body)` | `LProd()` | 2: `[convert(ty), convert(body)]` |
| `Lambda(name, ty, body)` | `LLambda()` | 2: `[convert(ty), convert(body)]` |
| `LetIn(name, val, ty, body)` | `LLetIn()` | 2: `[convert(val), convert(body)]`. Note: the type annotation `ty` is dropped (like cast stripping -- it is a type assertion, not a computational term) |
| `Case(info, scrutinee, branches)` | `LCase()` | 1 + len(branches): `[convert(scrutinee)] + [convert(b) for b in branches]` |
| `Fix(index, names, types, bodies)` | `LFix(index)` | len(bodies): `[convert(b) for b in bodies]` |
| `CoFix(index, names, types, bodies)` | `LCoFix(index)` | len(bodies): `[convert(b) for b in bodies]` |
| `Int(n)` | `LInt(n)` | 0 (leaf) |

**Binder names**: The `name` parameter in `Prod`, `Lambda`, `LetIn` is discarded. It is a display hint, not semantically relevant (de Bruijn indices handle binding).

**Recursion depth**: Track current recursion depth. If depth exceeds 1,000, abort conversion for this declaration, log a warning, and return `None`.

### Step 8: Implement section variable abstraction

**Action**: No runtime transform needed. The extraction pipeline (see extraction.md) indexes only closed forms from compiled `.vo` files, where sections are already discharged. Section variables have been abstracted into universal quantifiers by the Coq compiler.

**Implementation note**: Add a comment in `constr_to_tree()` documenting this design decision. If a future phase needs to handle open sections, the transform would wrap the tree in `LProd` nodes for each section variable.

### Step 9: Implement `recompute_depths(tree)`

Set the `depth` field on every node, starting from 0 at the root, incrementing by 1 for each level.

```python
def recompute_depths(tree: ExprTree, depth: int = 0) -> ExprTree:
    tree.depth = depth
    for child in tree.children:
        recompute_depths(child, depth + 1)
    return tree
```

**Invariant**: `depth` values form a monotonically increasing path from root (depth=0) to leaves.

**Note**: This is a simple in-place traversal. The spec says "bottom-up" for currification depth assignment, but since currification is handled during `constr_to_tree()` and `recompute_depths()` runs afterward over the complete tree, a top-down pass is correct and simpler.

### Step 10: Implement `assign_node_ids(tree)`

Assign a unique non-negative integer `node_id` to each node, using a pre-order (depth-first, left-to-right) traversal.

```python
def assign_node_ids(tree: ExprTree, counter: list[int] = None) -> ExprTree:
    if counter is None:
        counter = [0]
    tree.node_id = counter[0]
    counter[0] += 1
    for child in tree.children:
        assign_node_ids(child, counter)
    return tree
```

**Invariant**: `node_id` values are unique within a single tree. IDs are assigned in pre-order traversal order.

### Step 11: Wire up `coq_normalize()` with error handling

The top-level function:

```python
def coq_normalize(constr_t) -> ExprTree | None:
    try:
        tree = constr_to_tree(constr_t, current_depth=0)
        if tree is None:
            logger.warning("constr_to_tree returned None")
            return None
        recompute_depths(tree)
        assign_node_ids(tree)
        return tree
    except RecursionDepthExceeded as e:
        logger.warning(f"Recursion depth exceeded: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in coq_normalize: {e}")
        return None
```

Return `None` for any declaration that cannot be normalized. The extraction pipeline skips such declarations.

---

## 4. Module Structure

```
src/
  normalization/
    __init__.py
    coq_normalize.py        # Public API: coq_normalize(), constr_to_tree()
    constr_parser.py         # Parse serialized Constr.t (S-expr/JSON) into Python representation
    name_resolution.py       # canonical_fqn(), projection_to_string()
    tree_passes.py           # recompute_depths(), assign_node_ids()
  data_structures/
    __init__.py
    expr_tree.py             # ExprTree, NodeLabel hierarchy (from data-structures spec)
    scored_result.py         # ScoredResult (from data-structures spec)
    types.py                 # WlHistogram, Symbol, SymbolSet type aliases
```

The `normalization/` package is the scope of this task. The `data_structures/` package is a prerequisite.

---

## 5. Testing Plan

### 5.1 Unit tests for each transform

All tests go in `test/normalization/`.

#### Cast stripping (`test_cast_stripping.py`)

| Test | Input | Expected output |
|------|-------|----------------|
| Basic cast strip | `Cast(App(f, [a]), VMcast, nat_type)` | `ExprTree(LApp, [f_tree, a_tree])` -- no LCast in output |
| Nested casts | `Cast(Cast(x, _, _), _, _)` | `x_tree` -- both casts removed |
| Cast around leaf | `Cast(Rel(0), _, _)` | `ExprTree(LRel(0))` |
| Cast with empty inner (if possible) | Degenerate input | Returns `None`, logs warning |

#### Currification (`test_currification.py`)

| Test | Input | Expected output |
|------|-------|----------------|
| Ternary app (spec example) | `App(f, [a, b, c])` | `App(App(App(f, a), b), c)` -- 3 LApp nodes |
| Binary app | `App(f, [a, b])` | `App(App(f, a), b)` -- 2 LApp nodes |
| Unary app | `App(f, [a])` | `App(f, a)` -- 1 LApp node |
| Degenerate 0-arg app | `App(f, [])` | `f_tree` -- no LApp node |
| Nested app | `App(App(f, [a]), [b])` | `App(App(f, a), b)` -- already binary inner, then outer adds one |
| All LApp nodes have exactly 2 children | Any app input | Assert invariant holds |

#### Universe erasure (`test_universe_erasure.py`)

| Test | Input | Expected output |
|------|-------|----------------|
| Const with universe (spec example) | `Const("Coq.Init.Logic.eq", [Set])` | `LConst("Coq.Init.Logic.eq")` |
| Same const, different universe | `Const("Coq.Init.Logic.eq", [Type])` | Identical to above |
| Ind with universe | `Ind(("Coq.Init.Datatypes.nat", 0), [Set])` | `LInd("Coq.Init.Datatypes.nat")` |
| Construct with universe | `Construct((("nat", 0), 1), [Set])` | `LConstruct("...", 1)` |

#### Projection normalization (`test_projection.py`)

| Test | Input | Expected output |
|------|-------|----------------|
| Basic projection | `Proj(fst_proj, pair_term)` | `LProj("fst_name")` with 1 child |
| LProj has exactly 1 child | Any Proj input | Assert invariant |

#### Fully qualified names (`test_fqn.py`)

| Test | Input | Expected output |
|------|-------|----------------|
| Known name resolves | Short name "eq" with env | `"Coq.Init.Logic.eq"` |
| Unknown name fallback | Unresolvable name | Raw name returned, warning logged |

### 5.2 Integration tests for `constr_to_tree()`

#### All variants (`test_constr_to_tree.py`)

| Test | Input | Checks |
|------|-------|--------|
| `Rel(0)` | Single bound var | `LRel(0)`, leaf, 0 children |
| `Var("x")` | Named variable | `LVar("x")`, leaf |
| `Sort(Prop)` | Sort | `LSort(SortKind.PROP)`, leaf |
| `Prod(_, nat, nat)` | Arrow type | `LProd` with 2 children |
| `Lambda(_, nat, Rel(0))` | Identity fn | `LLambda` with 2 children |
| `LetIn(_, val, ty, body)` | Let binding | `LLetIn` with 2 children (val, body); ty dropped |
| `Case(info, scrut, [b1, b2])` | Match | `LCase` with 3 children |
| `Fix(0, _, _, [body])` | Fixpoint | `LFix(0)` with 1 child |
| `CoFix(0, _, _, [body])` | Cofixpoint | `LCoFix(0)` with 1 child |
| `Int(42)` | Primitive int | `LInt(42)`, leaf |

#### Combined transforms (`test_combined.py`)

| Test | Input | Checks |
|------|-------|--------|
| Cast inside App | `App(Cast(f, _, _), [a])` | Cast stripped, then app currified |
| App with Const children | `App(Const("eq", [u]), [Ind("nat", [u])])` | Universes erased, names qualified, binary app |
| Deeply nested term | 500-level nesting | Completes without hitting 1000-depth cap |
| Term at depth limit | 1001-level nesting | Returns `None`, logs warning |

### 5.3 Tests for post-processing passes

#### `recompute_depths()` (`test_depths.py`)

| Test | Input | Expected |
|------|-------|----------|
| Single node | Leaf | depth=0 |
| Linear chain | Root->child->grandchild | depths 0, 1, 2 |
| Binary tree | 3-level balanced | Root=0, children=1, grandchildren=2 |
| Post-currification | `App(App(f, a), b)` | All depths consistent |

#### `assign_node_ids()` (`test_node_ids.py`)

| Test | Input | Expected |
|------|-------|----------|
| Single node | Leaf | node_id=0 |
| Pre-order assignment | 3-node tree | IDs 0, 1, 2 in pre-order |
| All IDs unique | Any tree | `len(set(ids)) == len(ids)` |

### 5.4 End-to-end test for `coq_normalize()`

| Test | Input | Checks |
|------|-------|--------|
| `nat -> nat` (from data-structures spec) | `Prod(_, Ind("nat", []), Ind("nat", []))` | Tree matches spec example: LProd root, two LInd children, depths 0/1/1, node_ids 0/1/2 |
| `S (S O)` (from data-structures spec) | `App(Construct(("nat",0),1), [App(Construct(("nat",0),1), [Construct(("nat",0),0)])])` | 5 nodes, correct structure, depths, and IDs |
| Error: unrecognized variant | Unknown tag | Returns `None`, logs warning |
| Error: cyclic/deep term | Depth > 1000 | Returns `None`, logs warning |
| Error: cast produces empty | Degenerate cast | Returns `None`, logs warning |

---

## 6. Acceptance Criteria

1. `coq_normalize()` accepts a serialized `Constr.t` term and returns a valid `ExprTree` or `None`
2. No `LCast` nodes appear in any output tree
3. Every `LApp` node has exactly 2 children
4. Every `LProd` and `LLambda` node has exactly 2 children
5. Every `LProj` node has exactly 1 child
6. All leaf nodes (`LRel`, `LVar`, `LSort`, `LConst`, `LInd`, `LConstruct`, `LInt`) have 0 children
7. Universe instances are discarded -- two `Const` nodes with the same name but different universes produce identical `ExprTree` nodes
8. All names in `LConst`, `LInd`, `LConstruct` labels are fully qualified
9. `depth` field is 0 at root and increments by 1 per level
10. `node_id` values are unique within each tree
11. Recursion depth exceeding 1,000 produces `None` with a logged warning
12. Unrecognized `Constr.t` variants produce `None` with a logged warning
13. Failed name resolution falls back to raw name with a logged warning
14. All spec examples (Section 12 of the spec) produce the documented output
15. All structural invariants from data-structures.md Section 3 hold for every output tree

---

## 7. Risks and Mitigations

### Risk 1: Coq Constr.t interface instability

**Risk**: The serialization format of `Constr.t` from coq-lsp or SerAPI may vary across Coq versions, or may not expose all needed fields (e.g., projection details, universe instances).

**Mitigation**: Isolate all Coq interface code in `constr_parser.py`. Define a stable Python intermediate representation for `Constr.t` variants. Write integration tests against a known Coq version (8.18 or 8.19). Pin Coq version in the project configuration.

### Risk 2: Recursion depth limits in Python

**Risk**: Python's default recursion limit (typically 1,000) may be hit before the explicit 1,000-node depth cap is reached, especially since `constr_to_tree()` is itself recursive and each level may involve multiple recursive calls (e.g., processing children).

**Mitigation**: Use `sys.setrecursionlimit()` to raise Python's limit to at least 3,000 within the normalization module. Additionally, track depth explicitly with a counter parameter rather than relying solely on Python stack depth. Consider an iterative (stack-based) implementation if stack overflows occur in practice.

### Risk 3: Name resolution requires Coq environment

**Risk**: `canonical_fqn()` needs access to the Coq environment to resolve names. This means normalization is not a pure function -- it depends on having an active Coq session or preloaded name mapping.

**Mitigation**: Two options (choose during implementation):
1. **Eager resolution**: During extraction, resolve all names while the Coq environment is active and embed FQNs directly in the serialized `Constr.t` before passing to `constr_to_tree()`.
2. **Lazy resolution**: Pass a name-resolution callback to `constr_to_tree()` that the extraction layer provides.

Option 1 is simpler and decouples normalization from Coq. Prefer it unless there is a reason not to.

### Risk 4: LetIn child count ambiguity

**Risk**: The spec says `LLetIn` has 2 children but `LetIn` in Coq has 3 sub-terms: value, type annotation, and body. The spec is silent on which two to keep.

**Mitigation**: Keep `value` and `body` (the computationally relevant parts). Drop the type annotation, consistent with the cast-stripping rationale (type annotations are computationally irrelevant). Document this decision in code comments. See feedback document for spec clarification request.

### Risk 5: Case/Fix/CoFix child structure

**Risk**: The spec defines child counts for leaf and binary nodes precisely but does not specify the exact child layout for `LCase`, `LFix`, and `LCoFix`. Coq's `Case` has a complex structure (case info, match return type, scrutinee, branches). Depending on what is included, the child count varies.

**Mitigation**: Follow the Coq kernel structure: for `Case`, include scrutinee + branches as children (omit match return type and case info, which are type-level metadata). For `Fix`/`CoFix`, include only the bodies (omit types and names). Document decisions and add assertions for expected child counts. See feedback document for spec clarification request.

### Risk 6: Large expression trees from libraries like MathComp

**Risk**: MathComp uses heavy type class machinery that can produce very large `Constr.t` terms (thousands of nodes). The 1,000-depth cap handles depth, but wide trees (e.g., large `Case` with many branches) could still cause performance issues.

**Mitigation**: The 1,000 limit is on depth, not total node count. Performance testing with MathComp is needed during integration. If needed, add a total-node-count cap (e.g., 10,000) as a safety valve, skipping declarations that exceed it.
