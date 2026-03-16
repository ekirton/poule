# Channel 5: Const Name Jaccard

A lightweight channel that measures overlap between the sets of constant names in two expressions, ignoring structural shape.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
Data structures: [data-structures.md](data-structures.md)
Used by: [fusion.md](fusion.md)

---

## 1. Purpose

Provide a fast, structure-independent similarity signal based on shared constant names. This complements WL (which captures shape) and TED (which captures edit distance) by measuring whether two expressions reference the same mathematical objects, regardless of how those objects are combined.

---

## 2. Scope

Covers constant extraction from expression trees and Jaccard similarity computation. Does not cover how this score is combined with other metrics (see [fusion.md](fusion.md)) or how expression trees are constructed (see [coq-normalization.md](coq-normalization.md)).

---

## 3. Constant Extraction

```
function extract_consts(tree):
    consts = set()
    for node in tree (recursive):
        match node.label:
            LConst name  -> consts.add(name)
            LInd name    -> consts.add(name)
            LConstruct(name, _) -> consts.add(name)
            _ -> ()
    return consts
```

---

## 4. Jaccard Similarity

```
function const_jaccard(tree1, tree2):
    c1 = extract_consts(tree1)
    c2 = extract_consts(tree2)
    if |c1 ∪ c2| == 0:
        return 0.0
    return |c1 ∩ c2| / |c1 ∪ c2|
```

---

## 5. Usage

This channel is computed alongside TED or as a standalone lightweight signal. During fine ranking of WL candidates:

```
function const_jaccard_rank(query_tree, candidates):
    q_consts = extract_consts(query_tree)
    results = []
    for (id, tree) in candidates:
        c_consts = extract_consts(tree)
        score = jaccard(q_consts, c_consts)
        results.append((id, score))
    return results
```

See [fusion.md](fusion.md) for how this score is combined with WL, TED, and collapse-match in the fine-ranking weighted sum.

---

## 6. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Query tree has no constants (empty const set) | Edge case | Union is candidate's const set; intersection is empty. Jaccard = 0.0 for all candidates |
| Candidate tree has no constants | Edge case | Jaccard = 0.0 for that candidate |
| Both trees have no constants | Edge case | Union is empty; return 0.0 (guarded by the `|c1 ∪ c2| == 0` check) |
| Tree deserialization fails for a candidate | Dependency error | Skip candidate; log warning |

---

## 7. Examples

### Example: Identical constant sets

**Given**: Query tree contains constants `{Nat.add, Nat.S, Nat.O}`. Candidate tree contains the same set `{Nat.add, Nat.S, Nat.O}`.

**When**: `const_jaccard(query, candidate)` is computed.

**Then**: Intersection = 3, union = 3. Jaccard = 3/3 = **1.0**.

### Example: Partial overlap

**Given**: Query constants: `{Nat.add, Nat.S}`. Candidate constants: `{Nat.add, Nat.mul, Nat.S, Nat.O}`.

**When**: `const_jaccard(query, candidate)` is computed.

**Then**: Intersection = `{Nat.add, Nat.S}` = 2. Union = `{Nat.add, Nat.mul, Nat.S, Nat.O}` = 4. Jaccard = 2/4 = **0.5**.

### Example: No overlap

**Given**: Query constants: `{List.map, List.cons}`. Candidate constants: `{Nat.add, Nat.S}`.

**When**: `const_jaccard(query, candidate)` is computed.

**Then**: Intersection = 0, union = 4. Jaccard = 0/4 = **0.0**.
