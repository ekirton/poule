# Implementation Plan: FTS5 Full-Text Search Channel

**Specification:** [specification/channel-fts.md](../specification/channel-fts.md)
**Architecture:** [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
**Feedback:** [specification/feedback/channel-fts.md](../specification/feedback/channel-fts.md)

**Spec dependencies:**
- [storage.md](../specification/storage.md) — `declarations_fts` virtual table DDL, `declarations` table schema, FTS5 rebuild command
- [pipeline.md](../specification/pipeline.md) — `search_by_name` (Section 6) and `search_by_type` (Section 4) orchestration
- [fusion.md](../specification/fusion.md) — RRF fusion consumes FTS ranked list for `search_by_type`
- [data-structures.md](../specification/data-structures.md) — `ScoredResult` type for return values

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ScoredResult` type for returning ranked results from the channel.
2. **Storage schema** (from storage.md tasks) must be implemented: `declarations` table and `declarations_fts` virtual table with the `porter unicode61 remove_diacritics 2` tokenizer. The FTS channel reads from these tables; it does not create them.
3. **Extraction pipeline** (from extraction.md tasks) must be able to populate the `declarations` table and run the FTS5 `rebuild` command, so that the FTS index contains searchable content at query time.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **Query preprocessing is a separate module (T2) from query execution (T4).** The spec describes preprocessing and execution together across Sections 4 and 5, but separating them improves testability — preprocessing is pure string transformation with no database dependency.
- **The underscore-splitting rule (Rule 2) is included despite being absent from the spec.** The architecture doc (`retrieval-pipeline.md`, FTS5 section) explicitly defines a three-rule classification priority: Rule 1 (contains `.`) > Rule 2 (contains `_`, no spaces) > Rule 3 (everything else). The spec only describes Rules 1 and 3. Omitting Rule 2 would produce incorrect behavior for common identifier-style queries like `add_comm`. See feedback Issue 1.
- **The 20-token safety limit is included despite being absent from the spec.** The architecture doc specifies this limit. See feedback Issue 2.
- **The FTS channel exposes a single public function** (`fts_search`) rather than a class, since it is stateless — it takes a database connection and query string, returns scored results. The pipeline orchestrator calls this function directly.
- **BM25 scores are negated before returning** so that higher values indicate better matches for downstream consumers (RRF fusion, pipeline). FTS5's `bm25()` natively returns negative values where more negative = better match.

---

## Tasks

### Phase A: Package and Error Types

- [ ] **T1: FTS package scaffolding** — Create the FTS subpackage structure
  - **Traces to:** Project structure
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/retrieval/fts/__init__.py`, `tests/retrieval/fts/__init__.py`
  - **Done when:** `from coq_search.retrieval.fts import fts_search` works (once T4 is complete); `pytest` discovers tests under `tests/retrieval/fts/`; `__init__.py` exports: `fts_search`, `preprocess_fts_query`, `classify_query`

- [ ] **T2: FTS error types** — Define error types for the FTS channel
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 6
  - **Depends on:** T1
  - **Produces:** `src/coq_search/retrieval/fts/errors.py`
  - **Done when:** `FtsParseError` exception defined with attributes: `original_query` (the user's input), `preprocessed_query` (the FTS5 MATCH expression that failed), `fts_message` (the SQLite/FTS5 error string); both inherit from a project-level base exception if one exists, otherwise from `Exception`; unit test verifies instantiation and attribute access

### Phase B: Query Preprocessing

- [ ] **T3: Query classifier** — Classify input queries by type to determine preprocessing strategy
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 5; [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) FTS5 query classification priority
  - **Depends on:** T1
  - **Produces:** `src/coq_search/retrieval/fts/query_classifier.py`
  - **Done when:** `classify_query(query: str) -> QueryType` returns one of three enum variants: `QUALIFIED_NAME` (input contains `.`), `IDENTIFIER` (input contains `_` and no spaces and no `.`), or `NATURAL_LANGUAGE` (everything else); classification priority is Rule 1 > Rule 2 > Rule 3 per architecture doc; unit tests cover: `"Nat.add_comm"` -> `QUALIFIED_NAME`, `"add_comm"` -> `IDENTIFIER`, `"commutativity of addition"` -> `NATURAL_LANGUAGE`, `"List.rev_*"` -> `QUALIFIED_NAME`, `"Coq.Init.Nat.big_sum"` -> `QUALIFIED_NAME` (dot takes precedence over underscore), `"nat_add some lemma"` -> `NATURAL_LANGUAGE` (spaces disqualify IDENTIFIER), `"hello"` -> `NATURAL_LANGUAGE`, empty string -> `NATURAL_LANGUAGE`

- [ ] **T4: Query preprocessor** — Transform raw query strings into FTS5 MATCH expressions
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 5; [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) FTS5 token limit
  - **Depends on:** T2, T3
  - **Produces:** `src/coq_search/retrieval/fts/query_preprocessor.py`
  - **Done when:** `preprocess_fts_query(query: str) -> str | None` transforms a raw query string into an FTS5 MATCH expression or returns `None` for empty/whitespace-only queries; for `QUALIFIED_NAME` queries: split on `.` and `_`, filter empty tokens, quote each token with double quotes, join with ` AND `; a trailing `*` on the last token is preserved as an FTS5 prefix wildcard (placed outside the closing quote); for `IDENTIFIER` queries: split on `_`, filter empty tokens, quote each token, join with ` AND `; trailing `*` preserved as for qualified names; for `NATURAL_LANGUAGE` queries: pass through as-is (FTS5 handles implicit OR); FTS5 special characters (`*`, `"`, `(`, `)`) are escaped by removal except for a trailing `*` on the final token which is treated as an intentional FTS5 prefix wildcard; after tokenization, if the token count exceeds 20, truncate to the first 20 tokens; if all tokens are empty after filtering, return `None`; unit tests cover all three spec examples: `"Nat.add_comm"` -> `"Nat" AND "add" AND "comm"`, `"commutativity of addition"` -> `"commutativity of addition"`, `"List.rev_*"` -> `"List" AND "rev" AND *`; additional tests: empty string -> `None`, whitespace-only -> `None`, underscore identifier `"add_comm"` -> `"add" AND "comm"`, 25-token input truncated to 20, `"___"` -> `None`, special character removal

### Phase C: FTS5 Query Execution

- [ ] **T5: FTS5 search function** — Execute FTS5 MATCH queries with BM25 ranking and return scored results
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 4; [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name); [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target)
  - **Depends on:** T2, T4, storage tasks (declarations_fts table), data-structures tasks (ScoredResult)
  - **Produces:** `src/coq_search/retrieval/fts/fts_search.py`
  - **Done when:** `fts_search(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[ScoredResult]` executes the full FTS pipeline: (1) call `preprocess_fts_query(query)` — return empty list if `None`, (2) execute the FTS5 SQL query joining `declarations_fts` with `declarations` on `rowid = id`, using `bm25(declarations_fts, 10.0, 1.0, 5.0)` for scoring, `ORDER BY score ASC` (FTS5 bm25 returns negative values; ascending order = most relevant first), `LIMIT ?` parameterized, (3) map result rows to `ScoredResult` objects with fields: `id`, `name`, `statement`, `module`, `kind`, `score` (BM25 value negated so higher = better for downstream consumers), (4) on `sqlite3.OperationalError` from MATCH: catch and raise `FtsParseError` with original query, preprocessed query, and SQLite error detail, (5) on database locked: propagate to caller as-is; uses parameterized queries (no string interpolation of the MATCH expression); unit tests use an in-memory SQLite database with `declarations` and `declarations_fts` tables

- [ ] **T6: FTS5 index health check** — Detect empty FTS index at startup and log a warning
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 6, row "FTS5 table not populated"
  - **Depends on:** T1
  - **Produces:** `check_fts_populated()` in `src/coq_search/retrieval/fts/fts_search.py`
  - **Done when:** `check_fts_populated(conn: sqlite3.Connection) -> bool` queries `SELECT count(*) FROM declarations_fts LIMIT 1` and returns `False` if zero rows; the caller (MCP server startup) invokes this and logs a warning if `False`; does not raise an exception — FTS queries will simply return empty results; unit test verifies `True` on populated database and `False` on empty database

### Phase D: Module Exports

- [ ] **T7: Module exports** — Configure package exports
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Sections 4, 6 (consumers of this module)
  - **Depends on:** T2, T3, T4, T5, T6
  - **Produces:** Updated `src/coq_search/retrieval/fts/__init__.py`
  - **Done when:** `from coq_search.retrieval.fts import fts_search, preprocess_fts_query, classify_query, check_fts_populated, FtsParseError` all work; `__all__` is set

### Phase E: Unit Tests

- [ ] **T8: Unit tests — query classifier** — Test all classification rules and edge cases
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 5
  - **Depends on:** T3
  - **Produces:** `tests/retrieval/fts/test_query_classifier.py`
  - **Done when:** Tests cover: dot-containing inputs classified as `QUALIFIED_NAME`; underscore-containing inputs without dots or spaces classified as `IDENTIFIER`; natural language inputs classified as `NATURAL_LANGUAGE`; inputs with dots AND underscores classified as `QUALIFIED_NAME` (dot takes priority); single word without dots or underscores classified as `NATURAL_LANGUAGE`; empty string classified as `NATURAL_LANGUAGE`; inputs with spaces and underscores classified as `NATURAL_LANGUAGE` (spaces disqualify IDENTIFIER)

- [ ] **T9: Unit tests — query preprocessor** — Test FTS5 query generation for all query types and spec examples
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Sections 5, 7
  - **Depends on:** T4
  - **Produces:** `tests/retrieval/fts/test_query_preprocessor.py`
  - **Done when:** Tests cover all three spec Section 7 examples: (1) `"Nat.add_comm"` -> `"Nat" AND "add" AND "comm"`, (2) `"commutativity of addition"` -> passthrough, (3) `"List.rev_*"` -> `"List" AND "rev" AND *`; additional tests: empty string -> `None`; whitespace-only -> `None`; `"___"` -> `None`; `"..."` -> `None`; underscore identifier `"add_comm"` -> `"add" AND "comm"`; trailing wildcard on identifier `"add_*"` -> `"add" AND *`; special character escaping (embedded `"`, `(`, `)` removed from tokens); 20-token limit applied (25-token qualified name input produces 20-token AND expression); single-segment qualified name edge case

- [ ] **T10: Unit tests — FTS5 search function** — Test end-to-end search with in-memory SQLite
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Sections 4, 6, 7; [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name)
  - **Depends on:** T5
  - **Produces:** `tests/retrieval/fts/test_fts_search.py`
  - **Done when:** Test fixture creates an in-memory SQLite database with `declarations` and `declarations_fts` tables populated with ~10 representative declarations (including `Coq.Arith.PeanoNat.Nat.add_comm`, `Coq.NArith.BinNat.N.add_comm`, `Coq.Arith.PeanoNat.Nat.add_assoc` from spec Section 7 Example 1); FTS index rebuilt via `INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')`; tests verify: (1) qualified name query `"Nat.add_comm"` returns results with name-matched declarations ranked highest, (2) natural language query `"commutativity"` returns results via Porter stemming, (3) empty query returns empty list (not an error), (4) limit parameter respected, (5) scores are positive floats (negated BM25), (6) results contain all required `ScoredResult` fields (id, name, statement, module, kind, score), (7) query matching zero documents returns empty list

- [ ] **T11: Unit tests — error handling** — Test all error conditions from spec Section 6
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 6
  - **Depends on:** T5
  - **Produces:** `tests/retrieval/fts/test_fts_errors.py`
  - **Done when:** Tests verify: (1) empty query string returns empty list without sending MATCH to FTS5, (2) malformed FTS5 syntax after preprocessing raises `FtsParseError` with original query, preprocessed query, and FTS5 error message attributes accessible, (3) query containing only stop words returns empty list (FTS5 returns 0 results natively), (4) `check_fts_populated` returns `False` on empty FTS table and `True` on populated FTS table

- [ ] **T12: Unit tests — BM25 column weighting** — Verify that the `(10.0, 1.0, 5.0)` weight configuration biases toward name matches
  - **Traces to:** [channel-fts.md](../specification/channel-fts.md) Section 4, BM25 weight specification
  - **Depends on:** T5
  - **Produces:** Test within `tests/retrieval/fts/test_fts_search.py`
  - **Done when:** Test inserts declaration A with search term in `name` column only, declaration B with same term in `statement` column only, declaration C with term in `module` column only; after FTS rebuild, search for the term and assert ranking order is A > C > B, confirming the `(10.0, 1.0, 5.0)` weight configuration (name=10, module=5, statement=1) is effective

### Phase F: Integration and Performance Tests

- [ ] **T13: Integration test — FTS channel in search_by_name pipeline** — End-to-end test of FTS as the sole channel for name search
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 6; [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name)
  - **Depends on:** T5, pipeline tasks
  - **Produces:** `tests/retrieval/fts/test_fts_integration.py`
  - **Done when:** Test uses a SQLite database populated with representative declarations; the pipeline's `search_by_name` function invokes FTS search and returns results; `search_by_name("Nat.add_comm")` returns results with `Nat.add_comm` in top results; `search_by_name("commutativity of addition")` returns results matching stemmed terms; `search_by_name("")` returns empty list; default limit of 50 applied when no limit specified; caller-specified limit respected

- [ ] **T14: Integration test — FTS channel contribution to search_by_type** — Verify FTS produces a ranked list compatible with RRF fusion
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 4; [fusion.md](../specification/fusion.md) Section 3; [Story 2.3](../doc/requirements/stories/tree-search-mcp.md#23-search-by-type)
  - **Depends on:** T5, fusion tasks
  - **Produces:** Test within `tests/retrieval/fts/test_fts_integration.py`
  - **Done when:** Test verifies that `fts_search` returns a list of `ScoredResult` objects compatible with the `rrf_fuse` interface (declaration IDs and scores); test verifies FTS receives the original user-provided type expression string (not the normalized tree representation); test verifies the FTS ranked list can be passed alongside structural and MePo ranked lists to `rrf_fuse`

- [ ] **T15: Performance test — FTS query latency** — Validate sub-10ms query latency target
  - **Traces to:** [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) FTS5 section (runtime: <10ms); [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target)
  - **Depends on:** T5
  - **Produces:** `tests/retrieval/fts/test_fts_performance.py`
  - **Done when:** Test (marked `@pytest.mark.performance`, skipped in CI by default) creates an on-disk SQLite database with 10K synthetic declarations, rebuilds the FTS index, and measures wall-clock time for `fts_search` calls; mean query latency is under 10ms; preprocessing overhead is under 1ms; test is repeatable (not flaky)

---

## Dependency Graph

```
T1 (package scaffolding)
├── T2 (error types)
├── T3 (query classifier)
│
├── T4 (query preprocessor) ← T2, T3
│
├── T5 (FTS search function) ← T2, T4
├── T6 (FTS health check)
│
└── T7 (module exports) ← T2-T6

Tests:
  T8  (test classifier)     ← T3
  T9  (test preprocessor)   ← T4
  T10 (test FTS search)     ← T5
  T11 (test errors)         ← T5
  T12 (test BM25 weights)   ← T5
  T13 (integration: name)   ← T5, pipeline tasks
  T14 (integration: type)   ← T5, fusion tasks
  T15 (perf test)           ← T5
```
