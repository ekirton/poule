# Multi-Channel Retrieval

The search backend uses multiple independent retrieval channels, each capturing a different notion of similarity, to maximize recall across diverse query types.

---

## Channels

### Structural Channel

Captures the shape of mathematical expressions. Two lemmas about the same property often share tree structure even when they use different names and symbols. This is the primary channel for `search_by_structure` and `search_by_type`.

### Symbol Overlap Channel

Finds declarations that reference the same mathematical objects (constants, inductives, constructors) as the query. Catches cases where structural shape differs but the same definitions appear. Rare symbols are weighted more heavily than common ones to improve discrimination.

The index stores symbols as fully qualified kernel names. At query time, user-provided symbol names are resolved before matching: short names (e.g., `Nat.add`) and partial qualifications (e.g., `Init.Nat.add`) are expanded to their FQNs (e.g., `Coq.Init.Nat.add`) by suffix matching against the indexed symbol vocabulary. Ambiguous short names that match multiple FQNs are expanded to all matches, broadening recall.

### Lexical Channel

Full-text search over declaration names, pretty-printed statements, and module paths. Handles the most common case — the user searches by a name fragment or keyword. Also provides a fallback when structural and symbolic channels miss.

### Fine Structural Channel

Provides precise structural comparison for small expressions by measuring the minimum edit distance between expression trees. Applied only as a refinement of the structural channel's initial results, not to the full library.

### Constant Name Channel

A lightweight similarity measure based on the overlap of constant names between two expressions. Two expressions mentioning the same specific constants are likely related, regardless of how differently they are structured.

## Fusion

Results from applicable channels are combined so that items appearing across multiple channels are ranked higher than items from a single channel. This parameter-free fusion approach ensures robust recall without requiring learned weights.

## Channel Usage by Tool

| Search Operation | Channels Used |
|------------------|--------------|
| `search_by_structure` | Structural + Fine Structural + Constant Name |
| `search_by_symbols` | Symbol Overlap, optionally Constant Name |
| `search_by_name` | Lexical only |
| `search_by_type` | Structural + Symbol Overlap + Lexical |

Channel usage is identical whether the query arrives via MCP tool call or CLI command.

## Query-Time Type Normalization

Traces to: R-P0-24

Users write type queries as patterns — the body of a type with free variables standing in for universally quantified parameters and short constant names instead of fully qualified kernel names. The index stores complete types from Coq's kernel with bound variables, FQNs, and full quantifier structure.

`search_by_type` normalizes user queries before channel processing to bridge this representation gap:

1. **FQN resolution**: Short constant names in the query (e.g., `List.map`) are resolved to their fully qualified kernel names (e.g., `Coq.Lists.ListDef.map`) using the same suffix-matching mechanism as `search_by_symbols`. The suffix index is built from inverted index FQN keys plus re-export aliases captured during extraction. Coq re-exports definitions through convenience modules (e.g., `List.map` is a re-export of the canonical definition `ListDef.map`), so the suffix index must include suffixes of both canonical FQNs and re-export paths to resolve user-facing names correctly.

2. **Free variable detection**: Remaining unresolved short lowercase identifiers (no dots, not numeric, not a Coq keyword) are identified as pattern variables rather than constant references.

3. **Forall wrapping**: Detected free variables are wrapped in universal quantifiers, converting them from constant references to bound variables with correct de Bruijn indices. This makes the query's tree structure match the body of indexed fully-quantified types, enabling structural and fine structural channels.

4. **Relaxed size filtering**: Type queries inherently omit type parameters (e.g., `A B C : Type`) that are present in the indexed type. The structural channel uses a wider size tolerance for `search_by_type` to avoid rejecting valid candidates whose indexed types are larger due to these invisible binders.

5. **Body extraction for structural scoring**: Forall-wrapped free variables receive a generic `Type` binder type, while indexed types have concrete binder types (e.g., `A -> B`, `list A`). To prevent binder-type mismatches from penalizing structural scores, the scoring subroutine peels the auto-generated quantifier chain from both query and candidate trees before computing tree edit distance and collapse match. This focuses structural comparison on the body — the part that encodes the user's actual intent. The number of auto-generated binders is tracked from the wrapping step and used to peel exactly that many leading binders.

6. **Sort-leaf binder wildcard**: As a complementary measure, when collapse match encounters a `Prod` node where one side's binder type is a bare `Sort(Type)` leaf (the signature of an auto-generated or fully polymorphic binder), it treats the binder types as perfectly matching. This compensates for cases where the candidate has fewer leading binders than the query, so not all auto-generated wrappers can be peeled.

### Acceptance Criteria

**Priority:** P0
**Stability:** Draft

- GIVEN a type query with short constant names WHEN `search_by_type` executes THEN constant names are resolved to FQNs before channel processing
- GIVEN a type query with a re-exported name like `List.map` WHEN FQN resolution executes THEN the name resolves to the canonical FQN (e.g., `Coq.Lists.ListDef.map`) via re-export alias suffixes in the suffix index
- GIVEN a type query with unbound lowercase identifiers WHEN `search_by_type` executes THEN they are treated as pattern variables and wrapped in universal quantifiers
- GIVEN a type query without explicit quantifiers WHEN structural screening executes THEN candidates with larger quantifier-wrapped types are not rejected by the size filter
- GIVEN a type query with auto-detected free variables WHEN structural scoring executes THEN tree edit distance and collapse match are computed on body subtrees with auto-generated binders peeled, not on full quantifier-wrapped trees
- GIVEN a `Prod` comparison where one side has a bare `Sort(Type)` binder type WHEN collapse match executes THEN the binder types are treated as a perfect match

## Design Rationale

### Why multiple channels

No single similarity measure captures all ways mathematical statements can be related. Structural similarity misses name-based connections; symbol overlap misses shape-based relationships; lexical search misses both. Research on Lean retrieval systems consistently shows that combining complementary signals outperforms any single approach.

### Why fusion without learned weights

A simple rank-based fusion avoids the need for training data or manual tuning. Each channel votes independently; items that appear in multiple channels are naturally boosted. This approach is well-validated across information retrieval benchmarks and can be refined later with learned weights if evaluation data becomes available.
