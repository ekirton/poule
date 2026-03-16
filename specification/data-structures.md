# Data Structures

Core data structures shared across the Coq/Rocq semantic lemma search system.

**Architecture**: [expression-tree.md](../doc/architecture/data-models/expression-tree.md), [index-entities.md](../doc/architecture/data-models/index-entities.md), [response-types.md](../doc/architecture/data-models/response-types.md)

---

## 1. Purpose

Define the canonical Python types for expression trees, node labels, enumerations, and response types used across all components — extraction, normalization, storage, retrieval, and MCP server.

## 2. Scope

**In scope**: Enumerations (`SortKind`, `DeclKind`), node label hierarchy (abstract base + 15 concrete subtypes), `TreeNode`, `ExprTree`, response types (`SearchResult`, `LemmaDetail`, `Module`), and tree utility functions (`recompute_depths`, `assign_node_ids`, `node_count`).

**Out of scope**: Serialization format (owned by storage), normalization logic (owned by coq-normalization and cse-normalization), retrieval algorithms.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Expression tree | A rooted, ordered tree representing the normalized structure of a single Coq declaration's kernel term |
| Node label | The type tag on a tree node that determines whether it is a leaf or interior node and what payload it carries |
| CSE variable | A placeholder node (`LCseVar`) introduced by Common Subexpression Elimination to replace repeated non-constant subexpressions |
| Qualified name | A fully qualified canonical Coq name (e.g., `Coq.Init.Datatypes.nat`) |

## 4. Behavioral Requirements

### 4.1 Enumerations

#### SortKind

The system shall define a `SortKind` enumeration with exactly three members: `PROP`, `SET`, `TYPE_UNIV`.

#### DeclKind

The system shall define a `DeclKind` enumeration with members: `LEMMA`, `THEOREM`, `DEFINITION`, `INSTANCE`, `INDUCTIVE`, `CONSTRUCTOR`, `AXIOM`. Each member's string value shall be the lowercase form (e.g., `DeclKind.LEMMA` → `"lemma"`).

### 4.2 Node Labels

The system shall define an abstract base `NodeLabel` type that is equality-comparable and hashable. All 15 concrete label subtypes shall inherit from `NodeLabel`.

**Leaf labels** (nodes with zero children):

| Label | Payload | Hashable by |
|-------|---------|-------------|
| `LConst` | `name: str` (fully qualified) | name |
| `LInd` | `name: str` (fully qualified) | name |
| `LConstruct` | `name: str` (parent inductive FQN), `index: int` (≥ 0) | name + index |
| `LCseVar` | `id: int` (≥ 0) | id |
| `LRel` | `index: int` (≥ 0, de Bruijn index) | index |
| `LSort` | `kind: SortKind` | kind |
| `LPrimitive` | `value: int | float` | value |

**Interior labels** (nodes with one or more children):

| Label | Payload | Children constraint |
|-------|---------|---------------------|
| `LApp` | none | Exactly 2 |
| `LAbs` | none | Exactly 1 |
| `LLet` | none | Exactly 2 |
| `LProj` | `name: str` (projection name) | Exactly 1 |
| `LCase` | `ind_name: str` (inductive type name) | At least 1 |
| `LProd` | none | Exactly 2 |
| `LFix` | `mutual_index: int` (≥ 0) | At least 1 |
| `LCoFix` | `mutual_index: int` (≥ 0) | At least 1 |

Each concrete label shall implement `__eq__` and `__hash__` based on its type and payload.

MAINTAINS: Two labels are equal if and only if they have the same concrete type and identical payload values.

### 4.3 TreeNode

The system shall define a `TreeNode` with fields:

| Field | Type | Default |
|-------|------|---------|
| `label` | `NodeLabel` | Required |
| `children` | `list[TreeNode]` | Required (empty list for leaves) |
| `depth` | `int` | 0 (set by `recompute_depths`) |
| `node_id` | `int` | 0 (set by `assign_node_ids`) |

### 4.4 ExprTree

The system shall define an `ExprTree` with fields:

| Field | Type | Constraint |
|-------|------|-----------|
| `root` | `TreeNode` | Required |
| `node_count` | `int` | Required; must be > 0 |

### 4.5 Utility Functions

#### recompute_depths

- REQUIRES: `tree` is a valid `ExprTree`
- ENSURES: `depth` on all nodes is set; root gets 0, each child gets `parent.depth + 1`. Modifies in place.

#### assign_node_ids

- REQUIRES: `tree` is a valid `ExprTree`
- ENSURES: `node_id` on all nodes is set via pre-order traversal (depth-first, parent before children); sequential from 0. Modifies in place.

#### node_count

- REQUIRES: `tree` is a valid `ExprTree`
- ENSURES: Returns total node count (interior + leaf).

### 4.6 Response Types

#### SearchResult

| Field | Type | Constraint |
|-------|------|-----------|
| `name` | `str` | Required; fully qualified canonical name |
| `statement` | `str` | Required |
| `type` | `str` | Required |
| `module` | `str` | Required |
| `kind` | `DeclKind` | Required |
| `score` | `float` | Required; range [0.0, 1.0] |

#### LemmaDetail

Extends `SearchResult` with:

| Field | Type | Constraint |
|-------|------|-----------|
| `dependencies` | `list[str]` | Required; may be empty |
| `dependents` | `list[str]` | Required; may be empty |
| `proof_sketch` | `str` | Required; empty string when unavailable |
| `symbols` | `list[str]` | Required; may be empty |
| `node_count` | `int` | Required; must be > 0 |

#### Module

| Field | Type | Constraint |
|-------|------|-----------|
| `name` | `str` | Required; fully qualified module name |
| `decl_count` | `int` | Required; ≥ 0 |

## 5. Data Model

All entities defined in this specification are value types with no persistence logic. They are serialized/deserialized by the storage layer and produced by the retrieval pipeline.

## 6. Interface Contracts

### Tree utility functions

| Function | Input | Output | Error |
|----------|-------|--------|-------|
| `recompute_depths(tree)` | `ExprTree` | `None` (mutates in place) | None — always succeeds on valid trees |
| `assign_node_ids(tree)` | `ExprTree` | `None` (mutates in place) | None — always succeeds on valid trees |
| `node_count(tree)` | `ExprTree` | `int` | None — always succeeds on valid trees |

## 7. Error Specification

### Validation errors

| Condition | Error |
|-----------|-------|
| `LCseVar.id < 0` | `ValueError`: CSE variable ID must be non-negative |
| `LRel.index < 0` | `ValueError`: de Bruijn index must be non-negative |
| `LConstruct.index < 0` | `ValueError`: constructor index must be non-negative |
| `LFix.mutual_index < 0` | `ValueError`: mutual index must be non-negative |
| `LCoFix.mutual_index < 0` | `ValueError`: mutual index must be non-negative |
| `ExprTree.node_count < 1` | `ValueError`: node count must be positive |

Validation shall occur at construction time.

## 8. Examples

### Creating a simple expression tree

Given a Coq term `Nat.add`:

```
tree = ExprTree(
    root=TreeNode(label=LConst("Coq.Init.Nat.add"), children=[]),
    node_count=1
)
```

### Binary application after currification

Given `Nat.add 1 2` (currified to `LApp(LApp(Nat.add, 1), 2)`):

```
inner = TreeNode(label=LApp(), children=[
    TreeNode(label=LConst("Coq.Init.Nat.add"), children=[]),
    TreeNode(label=LPrimitive(1), children=[])
])
outer = TreeNode(label=LApp(), children=[inner,
    TreeNode(label=LPrimitive(2), children=[])
])
tree = ExprTree(root=outer, node_count=5)
recompute_depths(tree)  # root.depth=0, inner.depth=1, leaves.depth=2
assign_node_ids(tree)   # pre-order: outer=0, inner=1, Nat.add=2, 1=3, 2=4
```

### Equality semantics

```
LConst("Coq.Init.Nat.add") == LConst("Coq.Init.Nat.add")  # True
LConst("Coq.Init.Nat.add") == LInd("Coq.Init.Nat.add")    # False (different types)
LSort(SortKind.PROP) == LSort(SortKind.PROP)                # True
hash(LConst("x")) == hash(LConst("x"))                      # True
```

## 9. Language-Specific Notes (Python)

- Use `@dataclass(frozen=True)` for all node label types to get `__eq__` and `__hash__` for free.
- Use `@dataclass` (mutable) for `TreeNode` since `depth` and `node_id` are mutated in place.
- Use `@dataclass` (mutable) for `ExprTree` since `node_count` may be recomputed after CSE.
- Use `enum.Enum` for `SortKind` and `DeclKind`.
- Use `@dataclass(frozen=True)` for `SearchResult`, `LemmaDetail`, and `Module` — response types are immutable once created.
- Package location: `src/wily_rooster/models/`.
