# CSE Normalization

Common Subexpression Elimination for expression trees — reduces tree size by replacing repeated non-constant subexpressions with `LCseVar` references.

**Architecture**: [expression-tree.md](../doc/architecture/data-models/expression-tree.md) § CSE Normalization, [coq-normalization.md](../doc/architecture/coq-normalization.md)

---

## 1. Purpose

Define the three-pass CSE algorithm that compresses expression trees by identifying and replacing repeated structural subexpressions, reducing the cost of downstream similarity computations (WL, TED, collapse matching).

## 2. Scope

**In scope**: Structural hashing of subexpressions, frequency counting, replacement with `LCseVar` nodes, and integration with the normalization pipeline.

**Out of scope**: The initial Coq-specific normalization (`constr_to_tree`) — see [coq-normalization.md](coq-normalization.md). Tree utility functions — see [data-structures.md](data-structures.md).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Structural hash | A hash computed from a subexpression's shape — label type, payload, and children's hashes — identifying structurally identical subtrees |
| Candidate | A subexpression whose structural hash appears ≥ 2 times and whose root is not a constant label (`LConst`, `LInd`, `LConstruct`) |
| Constant label | `LConst`, `LInd`, or `LConstruct` — labels carrying semantic identity that must never be replaced by CSE |

## 4. Behavioral Requirements

### 4.1 cse_normalize

The `cse_normalize` function applies three-pass CSE to an `ExprTree`.

- REQUIRES: Input is a valid, fully-normalized `ExprTree` (post `constr_to_tree`, `recompute_depths`, `assign_node_ids`). Must not contain `LCseVar` nodes (CSE must be applied exactly once).
- ENSURES: All non-constant subexpressions with frequency ≥ 2 are replaced by `LCseVar(id)` nodes. After replacement: `recompute_depths` and `assign_node_ids` are called, and `node_count` is updated.
- MAINTAINS: Constant labels (`LConst`, `LInd`, `LConstruct`) are never replaced, regardless of frequency. Tree structure is otherwise preserved.

### 4.2 Pass 1 — Structural Hashing

The system shall compute a structural hash for every node in the tree via post-order traversal (children before parent).

**Hash computation**: For each node, produce an MD5 hex digest of a string composed of:
- A tag identifying the label type and its payload
- The hashes of all children, in order

The tag string format is an implementation choice, but shall be deterministic and distinguish all 15 label types and their payloads.

ENSURES: Two subtrees have the same hash if and only if they are structurally identical (same label types, same payloads, same children structure).

### 4.3 Pass 2 — Frequency Counting

The system shall count how many times each structural hash occurs in the tree.

ENSURES: A map from hash → frequency, where frequency is the number of nodes with that hash.

### 4.4 Pass 3 — Replacement

The system shall traverse the tree and replace candidate subexpressions:

1. A subexpression is a candidate when its hash has frequency ≥ 2 AND its root label is NOT a constant label (`LConst`, `LInd`, `LConstruct`).
2. The first occurrence of each candidate hash (in pre-order) is preserved as-is.
3. All subsequent occurrences are replaced with `LCseVar(id)`, where each unique candidate hash receives a distinct `id` assigned sequentially starting from 0.
4. When a node is replaced by `LCseVar`, its entire subtree is removed (the `LCseVar` is a leaf).

MAINTAINS: Replacement traversal order is deterministic (pre-order). The "first occurrence" is determined by pre-order position.

### 4.5 Pipeline Integration

After `cse_normalize` completes replacement, the pipeline shall:
1. Call `recompute_depths(tree)` — re-set depths after structural changes
2. Call `assign_node_ids(tree)` — re-set IDs after structural changes
3. Update `tree.node_count` to reflect the reduced tree

The full normalization pipeline sequence:
```
constr_to_tree → recompute_depths → assign_node_ids → cse_normalize → recompute_depths → assign_node_ids
```

### 4.6 Non-Idempotency

CSE normalization must be applied exactly once per tree. The system shall NOT guard against double application — it is a caller obligation. Running CSE on a tree that already contains `LCseVar` nodes produces incorrect results because existing `LCseVar` nodes participate in hashing.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Recursion depth exceeded during hashing | `NormalizationError` | Abort CSE; the pre-CSE tree remains valid |
| Empty tree (node_count = 0) | — | No-op; return tree unchanged |

## 6. Non-Functional Requirements

- Typical effect: 2–10× node reduction on expressions with heavy type annotation repetition.
- MD5 is sufficient for structural hashing (collision resistance is not security-critical; performance matters).
- All MD5 calls produce lowercase 32-character hex strings from UTF-8 encoded input.

## 7. Examples

### Basic CSE replacement

Given a tree where the subtree `LProd(LSort(PROP), LRel(0))` appears 3 times:

When: `cse_normalize` is called

Then:
- Pass 1 computes identical hashes for all 3 subtrees
- Pass 2 records frequency = 3 for that hash
- Pass 3 keeps the first occurrence (pre-order), replaces the 2nd and 3rd with `LCseVar(0)`
- All replacements of the same hash share the same CSE variable id

### Constants preserved

Given a tree containing `LConst("Coq.Init.Nat.add")` appearing 5 times:

When: `cse_normalize` is called

Then: All 5 occurrences remain as `LConst`. Constant labels are never replaced by CSE.

## 8. Language-Specific Notes (Python)

- Use `hashlib.md5` for structural hashing.
- Recursive traversal with Python's default recursion limit (1000). Catch `RecursionError` and raise `NormalizationError`.
- Package location: `src/wily_rooster/normalization/`.
