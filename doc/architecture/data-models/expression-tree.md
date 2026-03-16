# Expression Tree

The normalized expression tree is the canonical structural representation of a Coq/Rocq declaration, used for structural similarity computation across WL histograms, tree edit distance, and collapse matching.

**Architecture docs**: [coq-normalization.md](../coq-normalization.md), [coq-extraction.md](../coq-extraction.md), [retrieval-pipeline.md](../retrieval-pipeline.md)

---

## Expression Tree (entity)

A rooted, ordered tree representing the normalized structure of a single Coq declaration's kernel term.

| Field | Type | Constraints |
|-------|------|-------------|
| `root` | tree node | Required; the top-level node of the tree |
| `node_count` | positive integer | Required; total number of nodes; must equal `declarations.node_count` for the owning declaration |

### Relationships

- **Belongs to** one declaration (1:1, serialized in `declarations.constr_tree`; owned by `declarations`).

---

## Tree Node (entity)

A single node in an expression tree, representing one syntactic element of a normalized Coq term.

| Field | Type | Constraints |
|-------|------|-------------|
| `label` | node label | Required; abstract base type — must not be instantiated directly; all concrete label subtypes are equality-comparable and hashable; the label's concrete subtype determines whether the node is a leaf or interior node |
| `children` | ordered list of tree nodes | Required; count constrained by node type (see below); empty for leaf nodes |
| `depth` | non-negative integer | Derived metadata; distance from root; set by `recompute_depths()` |
| `node_id` | non-negative integer | Derived metadata; unique within a tree; set by `assign_node_ids()` |

### Node type enumeration

**Leaf types** (children: none):

| Node type | Label payload | Label constraint |
|-----------|---------------|-----------------|
| `LConst` | text (fully qualified name) | Must be a fully qualified canonical constant name |
| `LInd` | text (fully qualified name) | Must be a fully qualified canonical inductive type name |
| `LConstruct` | text (parent inductive FQN) + integer (constructor index) | The text must be the fully qualified canonical name of the parent inductive type (not the constructor's own name); the integer is the zero-based constructor index within that inductive type |
| `LCseVar` | non-negative integer | CSE variable identifier; must be >= 0 |
| `LRel` | non-negative integer | De Bruijn index; preserved as-is from Coq's `Rel(n)` |
| `LSort` | sort kind | One of: `PROP`, `SET`, `TYPE_UNIV` (see coq-normalization for sort mapping) |
| `LPrimitive` | numeric value | Primitive integer or float literal from Coq's `Int` or `Float` |

**Interior types** (children: one or more):

| Node type | Label payload | Children constraint |
|-----------|--------------|---------------------|
| `LApp` | none | Exactly 2: `func`, `arg` (binary application after currification) |
| `LAbs` | none | Exactly 1: `body` (binder name discarded during normalization) |
| `LLet` | none | Exactly 2: `value`, `body` (binder name and type discarded during normalization) |
| `LProj` | text (projection name) | Exactly 1: `struct` |
| `LCase` | text (inductive type name) | At least 1: `scrutinee`, followed by zero or more `branch` nodes (0-branch cases are valid for empty types like `False`) |
| `LProd` | none | Exactly 2: `type`, `body` (binder name discarded; represents dependent products / function types) |
| `LFix` | non-negative integer (mutual index) | At least 1: one child per body in the mutual fixpoint block |
| `LCoFix` | non-negative integer (mutual index) | At least 1: one child per body in the mutual co-fixpoint block |

### Relationships

- **Belongs to** one expression tree.
- **Owns** zero or more child tree nodes (1:*, recursive; ordered).

---

## Invariants

These constraints hold for all trees stored in `declarations.constr_tree` and for all query trees produced by the normalization pipeline.

| Invariant | Applies to | Constraint |
|-----------|-----------|------------|
| Binary application | `LApp` | All applications are binary. N-ary `App(f, [a1, a2, ...])` is currified to nested `LApp(LApp(f, a1), a2)`. |
| No cast nodes | All nodes | Cast nodes are stripped during normalization. No node in a stored tree represents a cast. |
| No `Var` nodes | All nodes | `Var` does not occur in closed kernel terms from `.vo` files. Encountering `Var` during normalization is an error. |
| No universe annotations | `LConst`, `LInd`, `LConstruct` | Universe parameters are erased. Two references at different universe levels have identical labels. |
| Canonical names only | `LConst`, `LInd`, `LConstruct` | All names are fully qualified kernel-canonical names, not user-facing short names. `LConstruct` carries the parent inductive type's FQN, not the constructor's own name. |
| Closed forms only | All nodes | Section-local free variables are absent. Only post-section closed definitions from `.vo` files are represented. |
| Constants preserved by CSE | `LConst`, `LInd`, `LConstruct` | These node types are never replaced by `LCseVar`, regardless of repetition frequency. They carry semantic identity essential for symbol-based retrieval. |

---

## Utility Functions

The following operations maintain tree invariants and are called during the normalization pipeline:

| Function | Contract |
|----------|----------|
| `recompute_depths(tree)` | REQUIRES: valid tree. ENSURES: `depth` on all nodes is set; root gets 0, each child gets parent.depth + 1. Modifies in place. |
| `assign_node_ids(tree)` | REQUIRES: valid tree. ENSURES: `node_id` on all nodes is set; **pre-order** traversal (depth-first, parent before children); sequential from 0. Modifies in place. |
| `node_count(tree)` | REQUIRES: valid tree. ENSURES: returns total node count (interior + leaf). |

These functions are called between `constr_to_tree()` and `cse_normalize()` in the normalization pipeline. Downstream specs (WL kernel, TED) call `node_count(tree)` as a named function.

---

## CSE Normalization

Common Subexpression Elimination reduces tree size by replacing repeated non-constant subexpressions with `LCseVar` references.

### Algorithm (three passes)

1. **Hash**: traverse the tree, computing a structural hash for each subexpression
2. **Count**: count frequency of each hash — subexpressions with frequency ≥ 2 are candidates
3. **Replace**: substitute repeated non-constant subexpressions with fresh `LCseVar(id)` nodes

Typical effect: 2–10× node reduction on expressions with heavy type annotation repetition.

**Non-idempotent**: CSE normalization must be applied exactly once per tree. Running it again would cause existing `LCseVar` nodes to participate in hashing and frequency counting, producing incorrect results.

---

## Normalization Pipeline

The full pipeline from Coq kernel term to stored tree:

```
Constr.t
  → constr_to_tree()      Adaptations applied inline:
                             • Currify n-ary applications
                             • Strip Cast nodes
                             • Reject Var nodes (error)
                             • Erase universe annotations
                             • Fully qualify all names
                             • Discard binder names (LAbs, LLet, LProd)
                             • Destructure Fix/CoFix tuples
                             • Keep Proj as interior node
                             • Map Sort values to SortKind
                             • Map Int/Float to LPrimitive
  → recompute_depths()    Update depth fields on all nodes
  → assign_node_ids()     Assign unique IDs for reference
  → cse_normalize()       CSE replacement (three passes above)
  → recompute_depths()    Re-set depth after CSE structural changes
  → assign_node_ids()     Re-set node IDs after CSE structural changes
  → serialized BLOB       Stored in declarations.constr_tree
```

Query expressions undergo the identical pipeline to ensure correct similarity computation.

---

## Serialization

The tree is serialized to a BLOB for storage in `declarations.constr_tree`. The specific serialization format is an implementation choice. Requirements:

- Must round-trip without data loss
- Must preserve all node types, labels, children ordering, and tree structure
- Must be deserializable at query time for TED computation and collapse matching
