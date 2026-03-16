# Core Data Structures

Shared types used by all retrieval channels. Every channel consumes `ExprTree` as input and produces `ScoredResult` as output.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)

---

## 1. Purpose

Define the canonical in-memory representations shared across extraction, normalization, retrieval channels, and fusion. These types form the internal API that all components program against.

---

## 2. Scope

Covers type definitions, field constraints, and structural invariants for `ExprTree`, `NodeLabel`, `WlHistogram`, `SymbolSet`, and `ScoredResult`. Does not cover the algorithms that produce or consume these types (see individual channel and normalization specs).

---

## 3. Expression Tree

The internal tree representation used by all retrieval channels. Every Coq `Constr.t` term is converted to this form after extraction.

### Node Labels

A node label is a tagged value — exactly one of the following variants:

| Label | Payload | Description |
|-------|---------|-------------|
| `LRel` | integer (de Bruijn index) | Bound variable reference |
| `LVar` | text (name) | Named variable |
| `LSort` | sort kind: `Prop`, `Set`, or `TypeUniv` | Universe sort |
| `LProd` | — | Dependent product / forall |
| `LLambda` | — | Lambda abstraction |
| `LLetIn` | — | Let binding |
| `LApp` | — | Application (always binary after currification) |
| `LConst` | text (fully qualified name) | Constant reference |
| `LInd` | text (fully qualified name) | Inductive type reference |
| `LConstruct` | text (inductive name) + integer (constructor index) | Constructor reference |
| `LCase` | — | Pattern match / elimination |
| `LFix` | integer (mutual index) | Fixpoint |
| `LCoFix` | integer (mutual index) | Cofixpoint |
| `LProj` | text (projection name) | Primitive projection |
| `LInt` | integer | Primitive integer literal |
| `LCseVar` | integer (variable id) | CSE-introduced variable (see [cse-normalization.md](cse-normalization.md)) |

Node labels must be equality-comparable and hashable. Labels with no payload are singletons for comparison purposes; labels with payloads compare by value.

### Tree Node

An `ExprTree` node consists of:

| Field | Type | Description |
|-------|------|-------------|
| `label` | node label | One of the 16 variants above |
| `children` | ordered list of `ExprTree` | Child subtrees, left-to-right |
| `depth` | non-negative integer | Distance from root, set during construction |
| `node_id` | non-negative integer | Unique within this tree, for WL bookkeeping |

**Construction rule**: children are ordered left-to-right as they appear in the kernel term. For `Prod(name, ty, body)`, children are `[ty_tree, body_tree]`. For `App(f, a)` (after currification), children are `[f_tree, a_tree]`.

A tree's **node count** is the total number of nodes (interior + leaf). Store this on the declaration record for size filtering.

### Structural Invariants

| Invariant | Enforcement point |
|-----------|-------------------|
| `LApp` nodes always have exactly 2 children | `constr_to_tree()` currification |
| `LProd`, `LLambda` nodes always have exactly 2 children (type, body) | `constr_to_tree()` |
| `LLetIn` nodes always have exactly 2 children (value, body) | `constr_to_tree()` |
| `LProj` nodes always have exactly 1 child | `constr_to_tree()` |
| Leaf nodes (`LRel`, `LVar`, `LSort`, `LConst`, `LInd`, `LInt`, `LCseVar`) have 0 children | `constr_to_tree()` |
| `LConstruct` nodes have 0 children (leaf) | `constr_to_tree()` |
| `depth` values form a monotonically increasing path from root (depth=0) to leaves | `recompute_depths()` |
| `node_id` values are unique within a single tree | `assign_node_ids()` |
| No `LCseVar` nodes exist before CSE normalization | Pipeline ordering |

---

## 4. WL Histogram

A sparse map from hashed label strings to occurrence counts.

- **Key**: MD5 hex string of the WL label
- **Value**: number of nodes carrying that label (positive integer)

Stored in SQLite as a JSON object `{"<md5>": count, ...}`. Typical size: 50–500 entries for a declaration of 20–200 nodes.

**MAINTAINS**: Every value in the histogram is ≥ 1. An empty histogram (no keys) is valid and represents a degenerate tree.

---

## 5. Symbol Set and Frequency Table

A **symbol** is a fully qualified constant, inductive, or constructor name (text).

A **symbol set** is the list of distinct symbols appearing in a declaration's expression tree. Extracted during indexing. Stored as a JSON array in `declarations.symbol_set`.

The global `symbol_freq` table maps each symbol to the number of declarations in the library that mention it. Built once during indexing; used by MePo weighting (see [channel-mepo.md](channel-mepo.md)).

**MAINTAINS**: Every entry in `symbol_freq` has freq ≥ 1. Every symbol in a declaration's symbol set appears in `symbol_freq`.

---

## 6. Search Result (Internal)

A `ScoredResult` represents one candidate returned by a single channel:

| Field | Type | Description |
|-------|------|-------------|
| `decl_id` | positive integer | `declarations.id` foreign key |
| `channel` | text | Which channel produced this result |
| `rank` | positive integer | 1-based rank within the channel |
| `raw_score` | float | Channel-specific score |

After fusion, results carry an `rrf_score` and a combined rank. See [fusion.md](fusion.md).

---

## 7. Error Specification

These are invariant violations — they indicate bugs in the producing code, not user-facing errors.

| Condition | Classification | Outcome |
|-----------|---------------|---------|
| `LApp` node with child count ≠ 2 | Invariant violation | Reject tree; log error with declaration name |
| `depth` or `node_id` < 0 | Invariant violation | Reject tree; log error |
| `ScoredResult` with `decl_id` not in `declarations` table | Invariant violation | Skip result; log warning |
| Empty `ExprTree` (null root) | Invariant violation | Skip declaration; log warning |
| WL histogram value ≤ 0 | Invariant violation | Reject histogram; recompute |

---

## 8. Examples

### Example: Tree for `nat → nat`

The Coq type `nat → nat` (a non-dependent arrow, which is syntactic sugar for `forall _ : nat, nat`) produces:

```
ExprTree(
  label = LProd,
  depth = 0,
  node_id = 0,
  children = [
    ExprTree(label=LInd("Coq.Init.Datatypes.nat"), depth=1, node_id=1, children=[]),
    ExprTree(label=LInd("Coq.Init.Datatypes.nat"), depth=1, node_id=2, children=[]),
  ]
)
```

Node count: 3. Symbol set: `["Coq.Init.Datatypes.nat"]`.

### Example: Tree for `S (S O)`

The expression `S (S O)` (the natural number 2) produces, after currification:

```
ExprTree(
  label = LApp,
  depth = 0,
  node_id = 0,
  children = [
    ExprTree(label=LConstruct("Coq.Init.Datatypes.nat", 1), depth=1, node_id=1, children=[]),
    ExprTree(
      label = LApp,
      depth = 1,
      node_id = 2,
      children = [
        ExprTree(label=LConstruct("Coq.Init.Datatypes.nat", 1), depth=2, node_id=3, children=[]),
        ExprTree(label=LConstruct("Coq.Init.Datatypes.nat", 0), depth=2, node_id=4, children=[]),
      ]
    ),
  ]
)
```

Node count: 5. Symbol set: `["Coq.Init.Datatypes.nat"]`. Constructor index 0 = `O`, index 1 = `S`.

---

## Language-Specific Notes: Python

### Node Labels

Represent the `NodeLabel` tagged union as a sealed class hierarchy using frozen dataclasses:

```python
from dataclasses import dataclass, field
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

Using `frozen=True` gives immutability and automatic `__hash__` — required since labels are used as dict keys in WL computation.

### Tree Node

```python
@dataclass
class ExprTree:
    label: NodeLabel
    children: list["ExprTree"] = field(default_factory=list)
    depth: int = 0
    node_id: int = 0
```

### Type Aliases

```python
WlHistogram = dict[str, int]
Symbol = str
SymbolSet = list[Symbol]
```

### Scored Result

```python
@dataclass
class ScoredResult:
    decl_id: int
    channel: str
    rank: int
    raw_score: float
```
