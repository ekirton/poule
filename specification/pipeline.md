# Query Processing Pipeline

End-to-end flow for each MCP search tool. Ties together all components.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
Components: [coq-normalization.md](coq-normalization.md), [cse-normalization.md](cse-normalization.md), [channel-wl-kernel.md](channel-wl-kernel.md), [channel-mepo.md](channel-mepo.md), [channel-fts.md](channel-fts.md), [channel-ted.md](channel-ted.md), [channel-const-jaccard.md](channel-const-jaccard.md), [fusion.md](fusion.md)

---

## 1. Purpose

Define the end-to-end orchestration for each of the four search tools. Each tool invokes a specific combination of retrieval channels and fusion strategies. This spec describes the sequencing and data flow — individual channel algorithms are specified in their own documents.

---

## 2. Scope

Covers the query processing flow for `search_by_structure`, `search_by_type`, `search_by_symbols`, and `search_by_name`. Does not cover input validation (see [mcp-server.md](mcp-server.md)), individual channel internals, or response formatting.

---

## 3. `search_by_structure`

For a query Coq expression:

```
1. Parse the query expression (via coq-lsp or the Coq parser)
2. coq_normalize(constr_t)              → normalized expr_tree
3. cse_normalize(tree)                   → CSE-reduced tree
4. wl_histogram(tree, h=3)              → query histogram
5. wl_screen(histogram, library, N=500) → top-500 WL candidates
6. For candidates with node_count ≤ 50:
     compute ted_similarity(query, candidate)
     compute collapse_match(query, candidate)
     compute const_jaccard(query, candidate)
     combine with weighted sum (see fusion.md)
7. For candidates with node_count > 50:
     compute collapse_match(query, candidate)
     compute const_jaccard(query, candidate)
     combine with weighted sum (see fusion.md)
8. Rank by structural_score
9. Return top-N results (default N=50)
```

---

## 4. `search_by_type`

For a query type expression (multi-channel):

```
1. Parse the type expression
2. Run WL screening pipeline (steps 2-8 above)     → structural ranked list
3. Extract symbols, run MePo                        → symbol ranked list
4. Run FTS5 query on the pretty-printed type        → lexical ranked list
5. rrf_fuse([structural, symbol, lexical], k=60)    → final ranked list
6. Return top-N results
```

---

## 5. `search_by_symbols`

```
1. Extract symbols from the query (or accept a symbol list directly)
2. Run MePo iterative selection
3. Optionally compute Const Jaccard for top MePo results
4. Return ranked results
```

---

## 6. `search_by_name`

```
1. Preprocess query for FTS5 (qualified name splitting, escaping)
2. Run FTS5 MATCH query with BM25 weights
3. Return results ordered by BM25 score
```

---

## 7. Error Specification

Errors at the pipeline level propagate upward to the MCP server, which formats them as structured error responses.

| Error Condition | Source | Outcome |
|-----------------|--------|---------|
| Query expression fails to parse | Coq parser | Return `PARSE_ERROR` with parser message |
| Normalization produces empty tree | `coq_normalize` or `cse_normalize` | Return empty result list (not an error) |
| WL screening returns 0 candidates | `wl_screen` | Return empty result list |
| All channels return 0 results in `search_by_type` | Fusion | Return empty result list |
| Individual channel raises exception | Any channel | Log warning, exclude that channel's results from fusion, continue with remaining channels |
| Database read failure during channel execution | SQLite | Propagate as dependency error to MCP server |

**Design rule**: An empty result list is a valid outcome, not an error. Errors are reserved for conditions that prevent execution (parse failures, database unavailability).

---

## 8. Examples

### Example: `search_by_structure` for `forall n : nat, n + 0 = n`

**Given**: Index contains Coq stdlib with ~15K declarations loaded.

**When**: `search_by_structure(expression="forall n : nat, n + 0 = n")`.

**Then**:
1. Parser produces a `Constr.t` for this type
2. `coq_normalize` yields an `ExprTree` with ~12 nodes (LProd at root, LApp nodes for `eq`, `Nat.add`, etc.)
3. `cse_normalize` may reduce repeated `nat` subtrees
4. WL screening (h=3) produces ~500 candidates sorted by cosine similarity
5. Candidates with ≤50 nodes get TED + collapse-match + const_jaccard scoring
6. Top results include `Nat.add_0_r` (`n + 0 = n`), `Nat.add_comm` (`n + m = m + n`), and similar arithmetic lemmas
7. Returns top-50 as `ScoredResult` list

### Example: `search_by_name` for `"Nat.add_comm"`

**Given**: Index contains Coq stdlib.

**When**: `search_by_name(pattern="Nat.add_comm")`.

**Then**:
1. Query is preprocessed: `"Nat.add_comm"` → FTS5 query `"Nat" AND "add" AND "comm"`
2. FTS5 MATCH returns BM25-ranked results
3. Top results: `Coq.Arith.PeanoNat.Nat.add_comm`, `Coq.NArith.BinNat.N.add_comm`, `Coq.ZArith.BinInt.Z.add_comm`, etc.

### Example: Channel failure in `search_by_type`

**Given**: FTS5 channel raises an unexpected exception during a `search_by_type` call.

**When**: Pipeline catches the exception.

**Then**: Warning logged for FTS5 failure. WL and MePo results are still fused via RRF (2 channels instead of 3). Results are returned normally, possibly with slightly lower quality.
