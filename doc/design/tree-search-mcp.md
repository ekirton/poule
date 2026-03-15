# Tree-Based Semantic Search for Coq/Rocq via MCP

A design summary for a training-free structural search system over Coq/Rocq libraries, exposed as an MCP server for LLM-mediated retrieval.

Background:
- [doc/background/tree-based-retrieval.md](../background/tree-based-retrieval.md) — Algorithms and prior art
- [doc/background/semantic-search.md](../background/semantic-search.md) — Architecture options and state of the art
- [doc/background/coq-ecosystem-gaps.md](../background/coq-ecosystem-gaps.md) — Gap 1 (Semantic Lemma Search)
- [doc/background/coq-premise-retrieval.md](../background/coq-premise-retrieval.md) — Premise selection landscape

---

## 1. Motivation

Coq/Rocq has no semantic search for its libraries. Users are limited to the built-in `Search` command, which requires knowing the approximate syntactic shape of what they seek. Lean has six search tools; Coq has zero.

We start with a **tree-based structural method** as the first-pass retrieval engine because:

1. **No training data required.** Coq lacks the premise annotation datasets that neural methods need. Tree-based methods work on the raw expression structure, deployable immediately on any Coq library.

2. **High recall as a design goal.** The first pass should cast a wide net. The LLM reasoning layer (via MCP) provides the sophistication to filter and rank results. We optimize for recall/sensitivity at the retrieval stage, not precision.

3. **Baseline for comparison.** Before investing in embeddings, fine-tuned models, or graph neural networks, we need a training-free baseline to measure against. If tree-based retrieval + LLM filtering proves sufficient for the target use cases, more complex methods may be unnecessary.

4. **Complementary to future methods.** Tree-based retrieval captures structural similarity that embedding models miss. LeanHammer's 21% improvement from neural+symbolic union shows that structural methods remain valuable even when neural methods are added later.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────┐
│                   Claude Code                    │
│                                                  │
│  User: "find a lemma about commutativity of      │
│         addition on natural numbers"             │
│                                                  │
│  LLM reasons about intent, formulates searches,  │
│  filters results, explains relevance             │
└──────────────────┬──────────────────────────────┘
                   │ MCP tool calls
                   ▼
┌─────────────────────────────────────────────────┐
│              MCP Server (thin adapter)           │
│                                                  │
│  Tools:                                          │
│    search_by_name(pattern)                       │
│    search_by_type(type_pattern)                  │
│    search_by_structure(expr, limit)              │
│    search_by_symbols(symbols[], limit)           │
│    get_lemma(name) → details + dependencies      │
│    find_related(name, relation)                  │
│    list_modules(prefix)                          │
└──────────────────┬──────────────────────────────┘
                   │ HTTP / stdio
                   ▼
┌─────────────────────────────────────────────────┐
│              Search Backend                      │
│                                                  │
│  Index:                                          │
│    SQLite DB with:                               │
│      - declarations table (name, module, type,   │
│        statement, kind, node_count)              │
│      - dependencies table (src, dst, relation)   │
│      - symbols table (decl, symbol, freq)        │
│      - wl_vectors table (decl, h, histogram)     │
│      - FTS5 index on names + statements          │
│                                                  │
│  Retrieval channels:                             │
│    1. WL kernel screening (structural)           │
│    2. MePo/SInE symbol overlap (syntactic)       │
│    3. FTS5 full-text search (lexical)            │
│    4. TED fine ranking (structural, small exprs) │
│    5. Const name Jaccard (lightweight)           │
│                                                  │
│  Fusion: reciprocal rank fusion across channels  │
└──────────────────┬──────────────────────────────┘
                   │ offline indexing
                   ▼
┌─────────────────────────────────────────────────┐
│           Coq Library Extraction                 │
│                                                  │
│  Via coq-lsp or SerAPI:                          │
│    - Extract all declarations with Constr.t      │
│    - Serialize to tree representation            │
│    - Compute CSE-normalized forms                │
│    - Extract dependency edges                    │
│    - Extract symbol sets                         │
│    - Compute WL encodings at h=1,3,5            │
│    - Pretty-print for FTS indexing               │
│                                                  │
│  Targets: stdlib, MathComp, user project         │
└─────────────────────────────────────────────────┘
```

---

## 3. Why MCP + LLM

The key architectural insight: **the LLM is the ranking and reasoning layer, not just a reranker.**

In offline testing, Claude (Opus) demonstrated the ability to:
- Read a Coq lemma statement and explain what it does in natural language
- Answer questions about a lemma's applicability to a given goal
- Identify when two lemmas are semantically related despite syntactic dissimilarity
- Reformulate a vague user query into precise structural or symbolic searches

This means the retrieval engine does not need to be precise — it needs **high recall**. The LLM handles:

- **Query formulation**: User says "something about lists being equal when reversed twice." The LLM translates this into multiple search tool calls: `search_by_symbols(["rev", "app", "list"])`, `search_by_name("*rev*inv*")`, `search_by_type("forall l, rev (rev l) = l")`.
- **Result filtering**: Of 50 candidates from structural search, the LLM reads the statements and selects the 3-5 actually relevant ones.
- **Explanation**: The LLM explains *why* each result is relevant, in the context of what the user is trying to do.
- **Iterative refinement**: If the first search doesn't find it, the LLM reformulates — follows dependency links, broadens symbol sets, tries different structural patterns.

This is qualitatively different from LLM-as-reranker (where the LLM just scores relevance). Research shows specialized rerankers beat LLMs at scoring. But no reranker can do intent interpretation, query reformulation, or conversational explanation.

---

## 4. Retrieval Channels

### 4.1 WL Kernel Screening (Primary Structural Channel)

Precompute WL histogram vectors for all declarations at h=3 (matching tbps). On query:
1. Extract the query expression (from a proof state, a type pattern, or an example term)
2. Apply CSE normalization
3. Compute WL histogram at h=3
4. Cosine similarity against all precomputed vectors
5. Return top-N candidates (N=200-500, tunable for recall)

This is the main structural retrieval channel. Sub-second on 100K items.

### 4.2 MePo Symbol Overlap (Syntactic Channel)

Extract constant/inductive/constructor symbols from the query and the library. Apply iterative MePo with inverse-frequency weighting (p=0.6, c=2.4). Return top-N by relevance score.

Strong baseline (R@32=42.1% on Lean Mathlib). Catches cases where structural shape differs but the same symbols appear. Complementary to WL.

### 4.3 FTS5 Full-Text Search (Lexical Channel)

SQLite FTS5 index on:
- Declaration names (e.g., `Nat.add_comm`)
- Pretty-printed statements
- Module paths

Handles the common case where users search by name fragment. BM25 ranking. Cheapest channel.

### 4.4 TED Fine Ranking (Optional, Small Expressions Only)

For the top candidates from WL screening, compute TED similarity for expressions ≤50 nodes (or higher if implemented in OCaml/Rust). Improves precision on small lemmas where structural similarity at the tree level is most discriminating.

### 4.5 Fusion

Reciprocal Rank Fusion (RRF) across channels:

```
RRF_score(d) = Σ_c  1 / (k + rank_c(d))
```

where k=60 (standard) and c ranges over channels that returned d. Simple, effective, requires no learned weights. Each channel votes independently; items appearing in multiple channels are boosted.

---

## 5. Coq-Specific Adaptations

Adapting tree-based methods from Lean4 to Coq requires handling structural differences:

| Concern | Approach |
|---------|----------|
| N-ary `App(f, args)` | Currify to binary `App(App(f, a1), a2)` for uniform tree structure |
| `Cast` nodes | Strip before comparison (computationally irrelevant) |
| Universe annotations | Erase `'univs` parameters (structural noise for retrieval) |
| `Proj` vs `Case` | Normalize: convert `Proj(p, t)` to the equivalent `Case` elimination, or treat `Proj` as a special interior node |
| Notation | Index the notation-expanded kernel term, not the surface syntax |
| Sections/modules | Fully qualify all names; record module membership |
| MathComp conventions | No special handling initially; the LLM layer can interpret SSReflect-style naming conventions |

---

## 6. MCP Tool Surface

```typescript
// Structural search: find declarations with similar expression structure
search_by_structure(
  expr: string,        // Coq expression or type (parsed by backend)
  limit: number = 50   // candidates to return (bias toward high recall)
) → SearchResult[]

// Symbol search: find declarations sharing symbols with the query
search_by_symbols(
  symbols: string[],   // constant/inductive names
  limit: number = 50
) → SearchResult[]

// Name search: find declarations by name pattern
search_by_name(
  pattern: string,     // glob or regex on qualified names
  limit: number = 50
) → SearchResult[]

// Type search: find declarations whose type matches a pattern
search_by_type(
  type_pattern: string, // Coq type expression
  limit: number = 50
) → SearchResult[]

// Get full details for a specific declaration
get_lemma(
  name: string         // fully qualified name
) → LemmaDetail

// Navigate the dependency graph
find_related(
  name: string,
  relation: "uses" | "used_by" | "same_module" | "same_typeclass",
  limit: number = 20
) → SearchResult[]

// Browse module structure
list_modules(
  prefix: string = ""  // e.g., "Coq.Arith" or "mathcomp.algebra"
) → Module[]

// ─── Response types ───

SearchResult = {
  name: string,          // fully qualified name
  statement: string,     // pretty-printed statement
  type: string,          // pretty-printed type
  module: string,        // containing module
  kind: string,          // "lemma" | "theorem" | "definition" | "instance" | ...
  score: number          // relevance score (0-1)
}

LemmaDetail = SearchResult & {
  dependencies: string[],  // names this declaration uses
  dependents: string[],    // names that use this declaration
  proof_sketch: string,    // tactic script or proof term (if available)
  symbols: string[],       // constant symbols appearing in the statement
  node_count: number       // expression tree size (for diagnostics)
}
```

The tool surface is intentionally broad (7 tools) to give the LLM flexibility in how it searches. The LLM can combine multiple tools in a single reasoning turn: name search to orient, structural search to find similar types, dependency traversal to explore neighborhoods.

---

## 7. Index Scope and Extraction

### Phase 1 (MVP)
- Coq standard library
- Single SQLite database, offline extraction

### Phase 2
- MathComp
- User's current project (incremental re-indexing on file save)

### Phase 3
- Any opam-installed Coq library
- Configurable scope per project

Extraction via coq-lsp (preferred — actively maintained, incremental) or SerAPI (fallback — deeper serialization, version-locked).

---

## 8. Storage

SQLite with the following schema (sketch):

```sql
-- Core declarations
CREATE TABLE declarations (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,          -- fully qualified
  module TEXT NOT NULL,
  kind TEXT NOT NULL,                 -- lemma, theorem, definition, ...
  statement TEXT NOT NULL,            -- pretty-printed
  type_expr TEXT NOT NULL,            -- pretty-printed type
  constr_tree BLOB,                   -- serialized CSE-normalized tree
  node_count INTEGER NOT NULL,
  symbol_set TEXT NOT NULL            -- JSON array of symbol names
);

-- Dependency edges
CREATE TABLE dependencies (
  src INTEGER REFERENCES declarations(id),
  dst INTEGER REFERENCES declarations(id),
  relation TEXT NOT NULL,             -- uses, instance_of, ...
  PRIMARY KEY (src, dst, relation)
);

-- Precomputed WL vectors (sparse histograms as JSON)
CREATE TABLE wl_vectors (
  decl_id INTEGER REFERENCES declarations(id),
  h INTEGER NOT NULL,                 -- WL iteration count
  histogram TEXT NOT NULL,            -- JSON {label: count}
  PRIMARY KEY (decl_id, h)
);

-- Symbol frequency table
CREATE TABLE symbol_freq (
  symbol TEXT PRIMARY KEY,
  freq INTEGER NOT NULL
);

-- Full-text search
CREATE VIRTUAL TABLE declarations_fts USING fts5(
  name, statement, module,
  content=declarations, content_rowid=id
);
```

Single file. No external services. Portable.

---

## 9. What This Is Not

This system is **not**:

- **A premise selection tool** (though it could become one). Premise selection operates on proof states and feeds into automated proving. This system operates on user queries and feeds into human understanding.
- **A neural retrieval system**. No embeddings, no training. The tree-based methods are the retrieval engine; the LLM is the intelligence layer.
- **A replacement for `Search`**. Coq's `Search` command does exact syntactic matching, which remains useful. This system provides the *semantic* search that `Search` cannot do.

---

## 10. Success Criteria

1. **Recall**: On a hand-curated set of (query, relevant lemma) pairs from common Coq workflows, the retrieval stage (before LLM filtering) should surface the relevant lemma in the top-50 at least 70% of the time.
2. **Latency**: First-pass retrieval completes in <1 second for a library of 50K declarations.
3. **Usability**: A user in Claude Code can describe what they need in natural language and get a useful, explained result within one conversational turn.
4. **Zero-config deployment**: Index the standard library with a single command. No GPU, no external services, no API keys (beyond Claude Code itself).
