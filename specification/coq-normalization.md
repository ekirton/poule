# Coq Expression Normalization

Transforms Coq kernel terms into normalized expression trees for structural similarity retrieval.

**Architecture**: [coq-normalization.md](../doc/architecture/coq-normalization.md), [expression-tree.md](../doc/architecture/data-models/expression-tree.md)

---

## 1. Purpose

Define the normalization pipeline that converts a `ConstrNode` intermediate representation (derived from Coq's `Constr.t` kernel term) into a canonical `ExprTree` suitable for WL histogram computation, tree edit distance, and collapse matching.

## 2. Scope

**In scope**: `ConstrNode` intermediate type, `constr_to_tree()` conversion, inline adaptations (currification, cast stripping, universe erasure, binder name discard, sort mapping, Fix/CoFix destructuring, Proj handling, Construct naming, Int/Float mapping), and the full normalization pipeline orchestrating `constr_to_tree` → `recompute_depths` → `assign_node_ids`.

**Out of scope**: CSE normalization (see [cse-normalization.md](cse-normalization.md)), extraction backend parsing (owned by extraction), serialization (owned by storage).

## 3. Definitions

| Term | Definition |
|------|-----------|
| ConstrNode | Intermediate representation of Coq's `Constr.t` with pre-resolved fully qualified canonical names |
| Currification | Converting n-ary `App(f, [a1, a2, ...])` to nested binary `LApp(LApp(f, a1), a2)` |
| De Bruijn index | Position-based variable reference; `Rel(1)` refers to the nearest enclosing binder |
| FQN | Fully qualified canonical name (e.g., `Coq.Init.Datatypes.nat`) |

## 4. Behavioral Requirements

### 4.1 ConstrNode

The system shall define a `ConstrNode` algebraic type with these variants, mirroring Coq's `Constr.t`:

| Variant | Fields |
|---------|--------|
| `Rel` | `n: int` |
| `Var` | `name: str` |
| `Sort` | `sort: str` (one of: `"Prop"`, `"SProp"`, `"Set"`, `"Type"`) |
| `Cast` | `term: ConstrNode`, `type: ConstrNode` |
| `Prod` | `name: str`, `type: ConstrNode`, `body: ConstrNode` |
| `Lambda` | `name: str`, `type: ConstrNode`, `body: ConstrNode` |
| `LetIn` | `name: str`, `value: ConstrNode`, `type: ConstrNode`, `body: ConstrNode` |
| `App` | `func: ConstrNode`, `args: list[ConstrNode]` |
| `Const` | `fqn: str` |
| `Ind` | `fqn: str` |
| `Construct` | `fqn: str`, `index: int` |
| `Case` | `ind_name: str`, `scrutinee: ConstrNode`, `branches: list[ConstrNode]` |
| `Fix` | `index: int`, `bodies: list[ConstrNode]` |
| `CoFix` | `index: int`, `bodies: list[ConstrNode]` |
| `Proj` | `name: str`, `term: ConstrNode` |
| `Int` | `value: int` |
| `Float` | `value: float` |

Universe parameters are erased by the backend parser before reaching `ConstrNode`. All constant, inductive, and constructor references carry pre-resolved FQNs.

### 4.2 constr_to_tree

The `constr_to_tree` function converts a `ConstrNode` to a `TreeNode`.

- REQUIRES: Input is a valid `ConstrNode` with pre-resolved FQNs and no universe parameters.
- ENSURES: Output is a valid `TreeNode` satisfying all expression tree invariants (binary applications, no casts, no Var nodes, canonical names, discarded binder names).
- MAINTAINS: The conversion is deterministic — the same input always produces the same output.

#### Adaptation rules (applied inline during recursive conversion)

| ConstrNode variant | Adaptation | Result |
|-------------------|------------|--------|
| `App(f, [a1, a2, ...])` | Currify: left-fold into nested binary applications | `LApp(LApp(constr_to_tree(f), constr_to_tree(a1)), constr_to_tree(a2))` ... |
| `App(f, [])` | Empty args: degenerate application | Return `constr_to_tree(f)` (no LApp wrapper) |
| `Cast(term, type)` | Strip: ignore cast, recurse into inner term | `constr_to_tree(term)` |
| `Var(name)` | Reject | Raise `NormalizationError` |
| `Lambda(name, type, body)` | Discard name, discard type | `LAbs` with 1 child: `constr_to_tree(body)` |
| `LetIn(name, value, type, body)` | Discard name, discard type | `LLet` with 2 children: `constr_to_tree(value)`, `constr_to_tree(body)` |
| `Prod(name, type, body)` | Discard name | `LProd` with 2 children: `constr_to_tree(type)`, `constr_to_tree(body)` |
| `Sort(sort)` | Map: `"Prop"` and `"SProp"` → `PROP`; `"Set"` → `SET`; `"Type"` → `TYPE_UNIV` | `LSort(kind)` |
| `Construct(fqn, index)` | FQN is the parent inductive's name | `LConstruct(fqn, index)` |
| `Fix(index, bodies)` | Types and names already discarded by parser | `LFix(index)` with `len(bodies)` children |
| `CoFix(index, bodies)` | Types and names already discarded by parser | `LCoFix(index)` with `len(bodies)` children |
| `Proj(name, term)` | Keep as interior node | `LProj(name)` with 1 child: `constr_to_tree(term)` |
| `Int(value)` | Map to primitive | `LPrimitive(value)` |
| `Float(value)` | Map to primitive | `LPrimitive(value)` |
| `Rel(n)` | Direct mapping | `LRel(n)` |
| `Const(fqn)` | Direct mapping | `LConst(fqn)` |
| `Ind(fqn)` | Direct mapping | `LInd(fqn)` |
| `Case(ind_name, scrutinee, branches)` | Direct mapping | `LCase(ind_name)` with `1 + len(branches)` children |

### 4.3 coq_normalize

The `coq_normalize` function orchestrates the full normalization pipeline (excluding CSE):

```
constr_to_tree(constr_node) → tree_node
ExprTree(root=tree_node, node_count=node_count(tree))
recompute_depths(tree)
assign_node_ids(tree)
→ normalized ExprTree
```

- REQUIRES: Input is a valid `ConstrNode`.
- ENSURES: Output is a valid `ExprTree` with correct `depth`, `node_id`, and `node_count`.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| `Var` node encountered | `NormalizationError` | Abort conversion of this declaration; log and continue extraction |
| Unknown `Sort` string | `NormalizationError` | Abort conversion |
| Recursion depth exceeded | `NormalizationError` | Abort conversion |

`NormalizationError` shall carry:
- `declaration_name: str` — the declaration being normalized (for logging)
- `message: str` — human-readable description

Individual normalization failures do not abort the indexing run. The caller logs the error and proceeds to the next declaration.

## 6. Examples

### Currification

Given: `App(Const("Coq.Init.Nat.add"), [Rel(1), Rel(2)])`

When: `constr_to_tree` is called

Then: Result is:
```
LApp
├── LApp
│   ├── LConst("Coq.Init.Nat.add")
│   └── LRel(1)
└── LRel(2)
```

### Cast stripping

Given: `Cast(Const("Coq.Init.Nat.zero"), Ind("Coq.Init.Datatypes.nat"))`

When: `constr_to_tree` is called

Then: Result is `LConst("Coq.Init.Nat.zero")` — cast is stripped entirely.

### Sort mapping

Given: `Sort("SProp")`

When: `constr_to_tree` is called

Then: Result is `LSort(SortKind.PROP)` — SProp maps to PROP.

## 7. Language-Specific Notes (Python)

- Implement `ConstrNode` variants as a union of frozen dataclasses, or use a tagged union pattern.
- `constr_to_tree` should be recursive with Python's default recursion limit (1000) as the practical depth bound. For terms exceeding this, catch `RecursionError` and raise `NormalizationError`.
- Package location: `src/wily_rooster/normalization/`.
