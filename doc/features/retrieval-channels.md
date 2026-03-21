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

## Design Rationale

### Why multiple channels

No single similarity measure captures all ways mathematical statements can be related. Structural similarity misses name-based connections; symbol overlap misses shape-based relationships; lexical search misses both. Research on Lean retrieval systems consistently shows that combining complementary signals outperforms any single approach.

### Why fusion without learned weights

A simple rank-based fusion avoids the need for training data or manual tuning. Each channel votes independently; items that appear in multiple channels are naturally boosted. This approach is well-validated across information retrieval benchmarks and can be refined later with learned weights if evaluation data becomes available.
