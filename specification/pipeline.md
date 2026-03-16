# Query Processing Pipeline

Orchestrates retrieval channels and fusion for each MCP tool query.

**Architecture**: [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) § Query Processing, [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the pipeline layer that receives validated query parameters from the MCP server, invokes the appropriate retrieval channels, applies fusion, and returns ranked results.

## 2. Scope

**In scope**: Four pipeline functions (`search_by_structure`, `search_by_type`, `search_by_symbols`, `search_by_name`), `PipelineContext` (shared resources), CoqParser lifecycle, structural scoring subroutine, dispatcher.

**Out of scope**: Input validation (owned by mcp-server), individual channel algorithms (owned by channel specs), storage access (owned by storage), fusion formulas (owned by fusion).

## 3. Definitions

| Term | Definition |
|------|-----------|
| PipelineContext | A shared resource container holding the `IndexReader`, in-memory data structures (WL histograms, inverted index, symbol frequencies), and the CoqParser reference |
| CoqParser | An interface to coq-lsp (or SerAPI) for parsing Coq expressions into `ConstrNode` at query time |
| Structural scoring | The subroutine that computes fine-ranking metrics (TED, collapse match, const Jaccard) and combines them with WL cosine via the weighted sum |

## 4. Behavioral Requirements

### 4.1 PipelineContext

The system shall define a `PipelineContext` that holds:

| Field | Type | Loaded when |
|-------|------|------------|
| `reader` | `IndexReader` | At context creation |
| `wl_histograms` | `dict[int, dict[str, int]]` | At context creation (from `reader.load_wl_histograms()`) |
| `inverted_index` | `dict[str, set[int]]` | At context creation (from `reader.load_inverted_index()`) |
| `symbol_frequencies` | `dict[str, int]` | At context creation (from `reader.load_symbol_frequencies()`) |
| `declaration_symbols` | `dict[int, set[str]]` | At context creation (derived from inverted index) |
| `declaration_node_counts` | `dict[int, int]` | At context creation (from declarations table) |
| `parser` | `CoqParser` | Lazily on first structural/type query |

#### create_context(db_path)

- REQUIRES: `db_path` points to a valid index database.
- ENSURES: Opens `IndexReader`, loads all in-memory data, returns a ready `PipelineContext`. Parser is not started until needed.

### 4.2 CoqParser Protocol

The pipeline shall define a `CoqParser` protocol (interface):

#### parse(expression)

- REQUIRES: `expression` is a Coq expression or type string.
- ENSURES: Returns a `ConstrNode` (the intermediate representation with pre-resolved FQNs).
- On failure: raises `ParseError`.

The parser is started lazily on the first structural or type query and kept alive for the server's lifetime.

### 4.3 search_by_structure

#### search_by_structure(ctx, expression, limit)

- REQUIRES: `ctx` is a valid `PipelineContext`. `expression` is a non-empty Coq expression string. `limit` is in [1, 200].
- ENSURES: Returns up to `limit` `SearchResult` items ranked by structural score.

Algorithm:
1. Parse `expression` via `ctx.parser.parse()` → `ConstrNode`
2. `coq_normalize(constr_node)` → normalized `ExprTree`
3. `cse_normalize(tree)` → CSE-reduced tree (with `recompute_depths`, `assign_node_ids`, updated `node_count`)
4. `wl_histogram(tree, h=3)` → query histogram
5. `wl_screen(histogram, query_node_count, ctx.wl_histograms, ctx.declaration_node_counts, n=500)` → candidates with WL scores
6. Structural scoring subroutine (§4.6) on candidates → final scores
7. Sort by score descending, take top `limit`
8. Construct `SearchResult` objects from declaration data

### 4.4 search_by_type

#### search_by_type(ctx, type_expr, limit)

- REQUIRES: `ctx` is a valid `PipelineContext`. `type_expr` is a non-empty Coq type expression string. `limit` is in [1, 200].
- ENSURES: Returns up to `limit` `SearchResult` items ranked by RRF-fused score.

Algorithm:
1. Parse and normalize `type_expr` (same as steps 1–4 of `search_by_structure`) → normalized tree, query histogram
2. Run WL screening + structural scoring → structural ranked list
3. `extract_consts(tree)` → query symbols; run `mepo_select(symbols, ...)` → symbol ranked list
4. `fts_query(type_expr)` → FTS5 query; `fts_search(query, limit=limit, reader)` → lexical ranked list
5. `rrf_fuse([structural, symbol, lexical], k=60)` → final ranked list
6. Take top `limit`, construct `SearchResult` objects

Note: `extract_consts` at query time is equivalent to the MePo channel's `extract_symbols`. Reuse the same function.

### 4.5 search_by_symbols

#### search_by_symbols(ctx, symbols, limit)

- REQUIRES: `ctx` is a valid `PipelineContext`. `symbols` is a non-empty list of fully qualified symbol names. `limit` is in [1, 200].
- ENSURES: Returns up to `limit` `SearchResult` items ranked by MePo relevance.

Algorithm:
1. `mepo_select(set(symbols), ctx.inverted_index, ctx.symbol_frequencies, ctx.declaration_symbols, p=0.6, c=2.4, max_rounds=5)` → ranked results
2. Take top `limit`, construct `SearchResult` objects

### 4.6 search_by_name

#### search_by_name(ctx, pattern, limit)

- REQUIRES: `ctx` is a valid `PipelineContext`. `pattern` is a non-empty search string. `limit` is in [1, 200].
- ENSURES: Returns up to `limit` `SearchResult` items ranked by BM25.

Algorithm:
1. `fts_query(pattern)` → preprocessed FTS5 query
2. `fts_search(query, limit, ctx.reader)` → ranked results
3. Construct `SearchResult` objects

### 4.7 Structural Scoring Subroutine

#### score_candidates(query_tree, candidates_with_wl, ctx)

- REQUIRES: `query_tree` is a normalized `ExprTree`. `candidates_with_wl` is a list of `(decl_id, wl_cosine_score)` pairs.
- ENSURES: Returns `(decl_id, structural_score)` pairs.

Steps:
1. Extract query constants: `extract_consts(query_tree)`
2. Fetch candidate trees: `ctx.reader.get_constr_trees(candidate_ids)` (batched)
3. For each candidate:
   a. Compute `const_jaccard` via `jaccard_similarity`
   b. Compute `collapse_match` via `collapse_match(query_tree, candidate_tree)`
   c. If both `query_tree.node_count ≤ 50` and `candidate.node_count ≤ 50`: compute `ted_similarity`
   d. Compute `structural_score` using the appropriate weighted sum
4. Return scored candidates

### 4.8 Query Normalization Failure

When `coq_normalize`, `cse_normalize`, `recompute_depths`, or `assign_node_ids` fails on a query expression:
- Return an empty candidate list
- Log a warning with the expression and error details
- Do not propagate as a user-facing error (this is a degraded-quality outcome, not a fatal error)

Parse failures (`ParseError` from the CoqParser) are distinct — they are propagated to the MCP server as `PARSE_ERROR`.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Coq expression parse failure | `ParseError` | Propagated to MCP server → `PARSE_ERROR` response |
| Query normalization failure | `NormalizationError` | Empty results, warning logged |
| Index reader error | `StorageError` | Propagated to MCP server |
| Parser backend crash | `ParseError` | Propagated; parser may need restart |

## 6. Non-Functional Requirements

- WL screening: sub-second on 100K declarations.
- End-to-end query latency target: < 2s for `search_by_structure`, < 3s for `search_by_type` (three channels + fusion).

## 7. Examples

### search_by_structure flow

Given: `expression = "forall n : nat, n + 0 = n"`

When: `search_by_structure(ctx, expression, limit=10)`

Then:
1. Parser produces `ConstrNode` for the expression
2. Normalization yields an `ExprTree` with ~15 nodes
3. WL screening returns 500 candidates
4. Structural scoring computes TED (trees ≤ 50 nodes), collapse match, const Jaccard for each
5. Returns top 10 by structural score

### search_by_type multi-channel flow

Given: `type_expr = "nat -> nat -> nat"`

When: `search_by_type(ctx, type_expr, limit=20)`

Then:
1. Structural channel: WL screen + fine-rank → ranked list
2. Symbol channel: MePo on `{Coq.Init.Datatypes.nat}` → ranked list
3. Lexical channel: FTS on `"nat AND nat AND nat"` → ranked list
4. RRF fuses all three → final top 20

## 8. Language-Specific Notes (Python)

- `PipelineContext` as a dataclass or plain class.
- `CoqParser` as a `Protocol` (structural subtyping) or ABC.
- Use `subprocess` or a library to manage coq-lsp process lifecycle.
- Package location: `src/wily_rooster/pipeline/`.
