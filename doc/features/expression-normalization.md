# Expression Normalization

Coq expressions are normalized before indexing and at query time so that surface-level syntactic variation does not affect search results.

**Stories**: [Epic 4: Coq-Specific Normalization](../requirements/stories/tree-search-mcp.md#epic-4-coq-specific-normalization)

---

## Problem

Coq's kernel representation of the same mathematical concept can vary in ways that are irrelevant to the user's search intent:

- **Application form**: `f(a, b)` vs. `(f a) b` — same function call, different tree shape
- **Type casts**: Computationally irrelevant annotations that add structural noise
- **Universe annotations**: The same constant at different universe levels should match
- **Projections vs. pattern matching**: Semantically identical, structurally different
- **Name qualification**: `add_comm` vs. `Nat.add_comm` vs. `Coq.Arith.PeanoNat.Nat.add_comm`

Without normalization, structurally identical queries return different results depending on which surface form the user or library author happened to use.

## What Gets Normalized

| Variation | Normalization |
|-----------|---------------|
| N-ary application | Currified to binary form |
| Type casts | Stripped |
| Universe annotations | Erased |
| Name qualification | Fully qualified canonical names |
| Section variables | Only closed (post-section) forms indexed |
| Repeated subexpressions | Replaced with shared variables (CSE) |

Notation is not an issue — extraction from compiled `.vo` files yields kernel terms, which are already notation-free.

## Consistency Invariant

The same normalization pipeline is applied at both indexing time and query time. A query expression and an indexed declaration that are semantically equivalent will produce identical normalized forms, ensuring they match during retrieval.

## Design Rationale

### Why normalize at all

Structural and type-based search compare expression trees. Without normalization, two expressions representing the same mathematical statement can have different tree shapes, causing missed matches. Normalization is the difference between "search works on carefully crafted queries" and "search works on whatever the user types."

### Why CSE (Common Subexpression Elimination)

Coq's kernel terms often contain heavily repeated type annotations. CSE reduces expression size by 2–10x, which directly improves both indexing storage and retrieval performance (smaller trees = faster comparison). The key constraint is that semantically meaningful constants are never replaced — only structural repetition is compressed.
