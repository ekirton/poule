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
| `wl_histograms` | `dict[int, dict[str, int]]` | At context creation (h-selected from `reader.load_wl_histograms()`) |
| `inverted_index` | `dict[str, set[int]]` | At context creation (from `reader.load_inverted_index()`) |
| `symbol_frequencies` | `dict[str, int]` | At context creation (from `reader.load_symbol_frequencies()`) |
| `declaration_symbols` | `dict[int, set[str]]` | At context creation (derived from inverted index) |
| `declaration_node_counts` | `dict[int, int]` | At context creation (from declarations table) |
| `suffix_index` | `dict[str, list[str]]` | At context creation (derived from inverted index keys + re-export aliases) |
| `parser` | `CoqParser` | Lazily on first structural/type query |
| `neural_encoder` | `NeuralEncoder` or null | At context creation (if model checkpoint available) |
| `embedding_index` | `EmbeddingIndex` or null | At context creation (if embeddings available and model hash matches) |

#### create_context(db_path)

- REQUIRES: `db_path` points to a valid index database.
- ENSURES: Opens `IndexReader`, loads all in-memory data, builds the suffix index, returns a ready `PipelineContext`. Parser is not started until needed. Neural channel is initialized if a model checkpoint is available, embeddings exist in the database, and the stored model hash matches the checkpoint — otherwise `neural_encoder` and `embedding_index` are null (neural channel unavailable). See [neural-retrieval.md](neural-retrieval.md) §4.4 for availability conditions.

**WL histogram h-selection**: `reader.load_wl_histograms()` returns `decl_id → {h → histogram}` (see [storage.md](storage.md) §4.3). `create_context` shall select `h=3` from each declaration's nested map to produce the flat `decl_id → histogram` structure required by `wl_screen`. If a declaration has no h=3 entry, it is omitted from `wl_histograms`.

**Suffix index construction**: For each FQN key in `inverted_index`, generate all proper dot-separated suffixes (e.g., `Coq.Init.Nat.add` → `Init.Nat.add`, `Nat.add`, `add`). Additionally, load re-export aliases via `reader.load_re_export_aliases()` and generate proper suffixes from each alias FQN, mapping them to the **canonical** FQN (e.g., alias `Coq.Lists.List.map` → suffixes `Lists.List.map`, `List.map`, `map`, all mapping to `Coq.Lists.ListDef.map`). Map each suffix to the list of FQNs it matches. Ambiguous suffixes (matching multiple FQNs) retain all matches — they are expanded at query time to maximize recall.

### 4.1.1 Prefix Aliasing

Rocq 9.x renamed the Coq standard library namespace from `Coq.*` to `Corelib.*`. The index stores modules under the legacy `Coq.*` canonical prefix, but declaration names in the inverted index may use `Corelib.*`. Users may query with either prefix.

The system shall define a centralized bidirectional alias registry:

```python
_PREFIX_ALIASES: list[tuple[str, str]] = [
    ("Coq.", "Corelib."),
]
```

#### alias_prefix(prefix)

- REQUIRES: `prefix` is a string.
- ENSURES: If `prefix` starts with either side of an alias pair, returns the prefix rewritten to the other side. Otherwise, returns `None`.

> **Given** `prefix = "Corelib.Arith"`,
> **When** `alias_prefix` is called,
> **Then** it returns `"Coq.Arith"`.

> **Given** `prefix = "Coq.Init"`,
> **When** `alias_prefix` is called,
> **Then** it returns `"Corelib.Init"`.

> **Given** `prefix = "mathcomp.algebra"`,
> **When** `alias_prefix` is called,
> **Then** it returns `None` (no alias applies).

This function is used by both `resolve_query_symbols` (§4.5.1) and `list_modules` (see [mcp-server.md](mcp-server.md) §4.2) to ensure both the legacy and modern namespace prefixes are accepted.

### 4.2 CoqParser Protocol

The pipeline shall define a `CoqParser` protocol (interface):

#### parse(expression)

- REQUIRES: `expression` is a Coq expression or type string.
- ENSURES: Returns a `ConstrNode` (the intermediate representation with pre-resolved FQNs).
- On failure: raises `ParseError`.

The default `CoqParser` implementation is `TypeExprParser` (pure Python, no subprocess). It is instantiated lazily on the first structural or type query and kept alive for the server's lifetime. See [type-expr-parser.md](type-expr-parser.md) for the parser specification.

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
1. Parse `type_expr` via `ctx.parser.parse()` → `ConstrNode`
2. `normalize_type_query(ctx, constr_node)` → `(normalized_constr, auto_binder_count)` with FQNs resolved and free variables wrapped (see §4.4.1)
3. `coq_normalize(normalized_constr)` → normalized `ExprTree`; `cse_normalize(tree)` → CSE-reduced tree
4. `wl_histogram(tree, h=3)` → query histogram
5. `wl_screen(histogram, query_node_count, ctx.wl_histograms, ctx.declaration_node_counts, n=500, size_ratio=2.0)` → candidates with WL scores
6. Structural scoring subroutine (§4.7) on candidates, passing `auto_binder_count` → structural ranked list
7. `extract_consts(tree)` → query symbols; run `mepo_select(symbols, ...)` → symbol ranked list
8. `fts_query(type_expr)` → FTS5 query; `fts_search(query, limit=limit, reader)` → lexical ranked list
9. If `ctx.neural_encoder` is not null and `ctx.embedding_index` is not null: `neural_retrieve(ctx, type_expr, limit=50)` → neural ranked list
10. `rrf_fuse([structural, symbol, lexical, neural?], k=60)` → final ranked list (neural omitted if unavailable)
11. Take top `limit`, construct `SearchResult` objects

Note: `extract_consts` at query time is equivalent to the MePo channel's `extract_symbols`. Reuse the same function.

#### 4.4.1 normalize_type_query(ctx, constr_node)

- REQUIRES: `ctx` has a populated `suffix_index` and `inverted_index`. `constr_node` is a valid `ConstrNode` produced by the parser.
- ENSURES: Returns a tuple `(ConstrNode, int)` where the `ConstrNode` has (1) resolvable constant names replaced with FQNs, and (2) detected free variables wrapped in outer `Prod` binders with `Rel` references replacing the original `Const` nodes. The `int` is the count of auto-generated forall binders (0 when no wrapping occurred).
- MAINTAINS: The transformation is deterministic. If the query already contains `forall` binders, only steps 1–2 below are applied (no wrapping, count is 0).

**Step 1 — FQN Resolution.** Walk the `ConstrNode` tree. For each `Const(name)` node:
1. If `name` is an exact key in `ctx.inverted_index`, keep it (already an FQN).
2. Otherwise, look up `name` in `ctx.suffix_index`. If it resolves to exactly one FQN, replace `Const(name)` with `Const(fqn)`.
3. If ambiguous (multiple FQNs) or no match, leave unchanged.

**Step 2 — Free Variable Detection.** After Step 1, collect all remaining `Const(name)` nodes where `name` satisfies ALL of:
- Contains no dot (`.`)
- Is not a numeric literal
- Starts with a lowercase letter or `_`
- Is not a Coq keyword (`forall`, `fun`, `match`, `let`, `in`, `if`, `then`, `else`, `return`, `as`, `with`, `end`, `fix`, `cofix`)

These are classified as free variables. Collect them in order of first occurrence (left-to-right, depth-first traversal).

**Step 3 — Forall Wrapping.** If the outermost node is already a `Prod`, skip this step (the user wrote explicit quantifiers). Otherwise:
1. For each detected free variable name, create a `Prod(name, Sort("Type"), ...)` binder.
2. Replace all `Const(name)` references to that variable with `Rel(n)` where `n` is the correct 1-based de Bruijn index (distance from the binding `Prod` to the reference).
3. Nest binders in order of first occurrence: the first-seen variable is outermost.

> **Given** `type_expr = "List.map f (List.map g l) = List.map (fun x => f (g x)) l"` and the suffix index resolves `List.map` to `Coq.Lists.ListDef.map` (via re-export alias) and `=` to `Coq.Init.Logic.eq`,
> **When** `normalize_type_query` is called,
> **Then** the result is equivalent to `Prod("f", Sort("Type"), Prod("g", Sort("Type"), Prod("l", Sort("Type"), <body>)))` where `<body>` uses `Const("Coq.Lists.ListDef.map")`, `Const("Coq.Init.Logic.eq")`, and `Rel(3)`, `Rel(2)`, `Rel(1)` for `f`, `g`, `l` respectively.

> **Given** `type_expr = "forall n : nat, n + 0 = n"` (already has forall),
> **When** `normalize_type_query` is called,
> **Then** FQN resolution is applied (e.g., `+` → FQN, `=` → FQN) but no forall wrapping occurs because the outermost node is already `Prod`.

### 4.5 search_by_symbols

#### search_by_symbols(ctx, symbols, limit)

- REQUIRES: `ctx` is a valid `PipelineContext`. `symbols` is a non-empty list of symbol name strings (at any qualification level — short, partial, or fully qualified). `limit` is in [1, 200].
- ENSURES: Returns up to `limit` `SearchResult` items ranked by MePo relevance.

Algorithm:
1. Resolve each symbol to FQN(s) via `resolve_query_symbols(ctx, symbols)` (see §4.5.1) → resolved FQN set
2. `mepo_select(resolved_set, ctx.inverted_index, ctx.symbol_frequencies, ctx.declaration_symbols, p=0.6, c=2.4, max_rounds=5)` → ranked results
3. Take top `limit`, construct `SearchResult` objects

#### 4.5.1 resolve_query_symbols(ctx, symbols)

- REQUIRES: `ctx` has a populated `inverted_index` and `suffix_index`. `symbols` is a non-empty list of strings.
- ENSURES: Returns a set of FQN strings suitable for passing to `mepo_select`.

Resolution per symbol:
1. **Exact match**: If the symbol is an exact key in `ctx.inverted_index`, use it directly (it is already an FQN).
2. **Suffix match**: Otherwise, look up the symbol in `ctx.suffix_index`. If found, expand to all matching FQNs.
3. **Prefix alias**: If neither exact nor suffix match succeeds, call `alias_prefix(symbol)` (§4.1.1). If the aliased form matches in the inverted index or suffix index, use those results.
4. **Passthrough**: If the symbol matches none of the above, include it as-is. MePo handles unknown symbols gracefully (they simply match no declarations in the inverted index lookup).

> **Given** `symbols = ["Nat.add", "Nat.mul"]` and the index contains FQNs `Coq.Init.Nat.add` and `Coq.Init.Nat.mul`,
> **When** `resolve_query_symbols` is called,
> **Then** `"Nat.add"` resolves to `"Coq.Init.Nat.add"` and `"Nat.mul"` resolves to `"Coq.Init.Nat.mul"` via suffix match. The resolved set is `{"Coq.Init.Nat.add", "Coq.Init.Nat.mul"}`.

> **Given** `symbols = ["Coq.Init.Nat.add"]` (already fully qualified),
> **When** `resolve_query_symbols` is called,
> **Then** `"Coq.Init.Nat.add"` is an exact key in the inverted index and is used directly.

> **Given** `symbols = ["add"]` where `"add"` matches `Coq.Init.Nat.add`, `Coq.NArith.BinNat.N.add`, and `Coq.ZArith.BinInt.Z.add`,
> **When** `resolve_query_symbols` is called,
> **Then** all three FQNs are included in the resolved set.

### 4.6 search_by_name

#### search_by_name(ctx, pattern, limit)

- REQUIRES: `ctx` is a valid `PipelineContext`. `pattern` is a non-empty search string. `limit` is in [1, 200].
- ENSURES: Returns up to `limit` `SearchResult` items ranked by BM25.

Algorithm:
1. `fts_query(pattern)` → preprocessed FTS5 query
2. `fts_search(query, limit, ctx.reader)` → ranked results
3. Construct `SearchResult` objects

### 4.7 Structural Scoring Subroutine

#### score_candidates(query_tree, candidates_with_wl, ctx, auto_binder_count=0)

- REQUIRES: `query_tree` is a normalized `ExprTree`. `candidates_with_wl` is a list of `(decl_id, wl_cosine_score)` pairs. `auto_binder_count` is a non-negative integer (0 for `search_by_structure`; the count of auto-generated forall binders for `search_by_type`).
- ENSURES: Returns `(decl_id, structural_score)` pairs.

Steps:
1. Extract query constants: `extract_consts(query_tree)` (uses the full tree — unaffected by binder structure)
2. If `auto_binder_count > 0`: peel the query tree by stripping up to `auto_binder_count` leading `LProd` layers, following `children[1]` (body) at each step → `peeled_query`. Recompute depths, node IDs, and node count on the peeled tree. If `auto_binder_count == 0`, `peeled_query = query_tree`.
3. Fetch candidate trees: `ctx.reader.get_constr_trees(candidate_ids)` (batched)
4. For each candidate:
   a. Compute `const_jaccard` via `jaccard_similarity` (uses full trees)
   b. If `auto_binder_count > 0`: peel the candidate tree by the same count → `peeled_candidate`. Otherwise `peeled_candidate = candidate_tree`.
   c. Compute `collapse_match` via `collapse_match(peeled_query, peeled_candidate)`
   d. If both `peeled_query.node_count ≤ 50` and `peeled_candidate.node_count ≤ 50`: compute `ted_similarity` on peeled trees
   e. Compute `structural_score` using the appropriate weighted sum (WL cosine is from the screening step, computed on full trees)
5. Return scored candidates

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
- Package location: `src/poule/pipeline/`.
