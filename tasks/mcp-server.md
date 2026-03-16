# Implementation Plan: MCP Server

**Specification:** [specification/mcp-server.md](../specification/mcp-server.md)
**Architecture:** [doc/architecture/mcp-server.md](../doc/architecture/mcp-server.md)
**Feedback:** [specification/feedback/mcp-server.md](../specification/feedback/mcp-server.md)

**Spec dependencies:**
- [pipeline.md](../specification/pipeline.md) — query processing flows dispatched by the MCP server
- [storage.md](../specification/storage.md) — SQLite schema, index_meta validation, read path contracts
- [data-structures.md](../specification/data-structures.md) — ExprTree, WlHistogram types loaded at startup

---

## Prerequisites

Before implementation of this component can begin:

1. **Storage read path** (from storage.md tasks) must be implemented: database opening, `index_meta` reading, WL histogram loading, symbol index construction, symbol_freq loading.
2. **Pipeline query flows** (from pipeline.md tasks) must be implemented: `search_by_structure`, `search_by_type`, `search_by_symbols`, `search_by_name` orchestration functions.
3. **Response types** must be defined as Python dataclasses: `SearchResult`, `LemmaDetail`, `Module`.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **Response types are implemented as a shared module (T1)** rather than inline in the server. The spec defines them in Section 5 as dataclasses. This plan places them in a standalone module since both the pipeline layer and the MCP server reference them.
- **Input validation is a separate module (T5)** rather than inline in each tool handler. The spec prescribes validation rules in Section 6 but does not specify where validation logic lives. Centralizing validation improves testability and ensures consistent error formatting.
- **Index state management is a dedicated class (T3)** encapsulating the startup validation sequence from Section 8.1. The spec describes a linear startup sequence, but the resulting state (healthy, missing, version mismatch) must be checked on every tool call. A state holder simplifies this.
- **Tool handlers are organized as one module (T6-T12)** with one function per tool. The spec defines 7 tools; grouping them keeps the handler surface cohesive and co-locatable. Each handler delegates to the pipeline or database layer after validation.
- **The `same_typeclass` relation for `find_related`** is implemented as a two-hop query over `instance_of` edges in the `dependencies` table (see feedback Issue 7). This is inferred from the storage schema since the spec does not prescribe the query strategy.
- **`proof_sketch` in `LemmaDetail`** is always returned as an empty string in this implementation phase (see feedback Issue 6). No storage column or extraction step currently produces this data.
- **`INDEX_REBUILDING` is deferred.** The spec defines this error code but does not describe when the server triggers re-indexing (see feedback Issue 5). Phase 1 treats version mismatches as terminal `INDEX_VERSION_MISMATCH` errors; the user must re-index manually.
- **Pipeline interface abstraction**: Tool handlers call the pipeline through a `PipelineInterface` protocol (`typing.Protocol`), allowing the MCP server to be tested with a mock pipeline that does not require a Coq backend.

---

## Tasks

### Phase A: Package Structure and Foundation

- [ ] **T1: Server package scaffolding** — Create the server subpackage and test directories
  - **Traces to:** [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server)
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/server/__init__.py`, `tests/server/__init__.py`
  - **Done when:** `from coq_search.server` imports without error; `pytest` discovers tests under `tests/server/`; `__init__.py` contains a module docstring describing the MCP server layer

- [ ] **T2: Response type dataclasses** — Define `SearchResult`, `LemmaDetail`, and `Module` dataclasses
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 5; [response-types.md](../doc/architecture/data-models/response-types.md); [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/server/response_types.py`
  - **Done when:** `SearchResult` dataclass has fields: `name: str`, `statement: str`, `type: str`, `module: str`, `kind: str`, `score: float`; `LemmaDetail` dataclass has all `SearchResult` fields plus: `dependencies: list[str]`, `dependents: list[str]`, `proof_sketch: str`, `symbols: list[str]`, `node_count: int`; `Module` dataclass has fields: `name: str`, `decl_count: int`; all dataclasses have a `to_dict() -> dict` method returning a JSON-serializable dictionary; `kind` constrained to the seven values from the spec (`lemma`, `theorem`, `definition`, `inductive`, `constructor`, `instance`, `axiom`); unit tests verify field presence and dict serialization

- [ ] **T3: Error types and error response formatter** — Define MCP error codes and a formatter for structured error responses
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 7; [Story 6.1](../doc/requirements/stories/tree-search-mcp.md#61-missing-index)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/server/errors.py`
  - **Done when:** `ErrorCode` enum with values `INDEX_MISSING`, `INDEX_VERSION_MISMATCH`, `NOT_FOUND`, `PARSE_ERROR`; `format_error(code: str, message: str) -> dict` returns the MCP error response structure `{"content": [{"type": "text", "text": "{\"error\": {\"code\": ..., \"message\": ...}}"}], "isError": true}` matching the architecture doc's error format; message template constants for `INDEX_MISSING` (with path placeholder), `INDEX_VERSION_MISMATCH` (with found/expected placeholders), `NOT_FOUND` (with name placeholder); a `ServerError` exception class carries `code` and `message` for use in tool handlers; unit tests verify each error code produces correctly structured responses with parseable JSON in the `text` field

### Phase B: Index State and Data Loading

- [ ] **T4: Index state manager** — Implement startup index validation and state tracking
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 8.1; [storage.md](../specification/storage.md) Section 6; [Story 1.4](../doc/requirements/stories/tree-search-mcp.md#14-detect-and-rebuild-stale-indexes), [Story 1.5](../doc/requirements/stories/tree-search-mcp.md#15-index-version-compatibility), [Story 6.1](../doc/requirements/stories/tree-search-mcp.md#61-missing-index)
  - **Depends on:** T3
  - **Produces:** `src/coq_search/server/index_state.py`
  - **Done when:** `IndexState` class encapsulates index validation; `validate(db_path: Path) -> IndexStatus` performs the startup check sequence from spec Section 8.1: (1) check database file exists — missing sets status to `INDEX_MISSING`, (2) open database read-only, (3) read `index_meta` table, (4) compare `schema_version` to current tool version — mismatch sets status to `INDEX_VERSION_MISMATCH`, (5) compare `coq_version` to installed version — mismatch sets status to `INDEX_VERSION_MISMATCH`, (6) compare `mathcomp_version` to installed version — mismatch sets status to `INDEX_VERSION_MISMATCH`; `IndexStatus` is an enum with values `HEALTHY`, `INDEX_MISSING`, `INDEX_VERSION_MISMATCH`; `check_ready()` raises `ServerError` with the appropriate error code and message if status is not `HEALTHY`; unit tests mock the database file and `index_meta` contents to verify all status transitions

- [ ] **T5: In-memory data loader** — Load WL histograms, symbol inverted index, and symbol frequencies into memory at startup
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 8.1 steps 5-7; [storage.md](../specification/storage.md) Section 5.2
  - **Depends on:** T4
  - **Produces:** `src/coq_search/server/data_loader.py`
  - **Done when:** `load_wl_histograms(conn) -> dict[int, dict[str, int]]` loads all `wl_vectors` rows where `h=3`, parsing the JSON histogram column, keyed by `decl_id`; `load_symbol_index(conn) -> dict[str, set[int]]` builds an inverted index from `declarations.symbol_set` JSON arrays, mapping each symbol to the set of `decl_id` values containing it; `load_symbol_freq(conn) -> dict[str, int]` loads the `symbol_freq` table into a dict; `ServerData` dataclass bundles all three in-memory structures plus the database connection; unit tests use an in-memory SQLite database with synthetic data to verify correct loading, structure, and that empty tables produce empty structures without errors

### Phase C: Input Validation

- [ ] **T6: Input validators** — Implement per-tool input validation functions
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 6; [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name) through [Story 2.8](../doc/requirements/stories/tree-search-mcp.md#28-list-modules)
  - **Depends on:** T3
  - **Produces:** `src/coq_search/server/validators.py`
  - **Done when:** `validate_search_by_name(params: dict) -> tuple[str, int]` validates `pattern` is a non-empty string and `limit` is clamped to [1, 200] (default 50), raises `ServerError(PARSE_ERROR)` on missing/empty pattern; `validate_search_by_type(params: dict) -> tuple[str, int]` validates `type_expr` is a non-empty string and clamps `limit`; `validate_search_by_structure(params: dict) -> tuple[str, int]` validates `expression` is a non-empty string and clamps `limit`; `validate_search_by_symbols(params: dict) -> tuple[list[str], int]` validates `symbols` is a non-empty list of non-empty strings and clamps `limit`; `validate_get_lemma(params: dict) -> str` validates `name` is a non-empty string; `validate_find_related(params: dict) -> tuple[str, str, int]` validates `name` is non-empty, `relation` is one of `uses`, `used_by`, `same_module`, `same_typeclass` (raises PARSE_ERROR listing valid values on mismatch), and clamps `limit` (default 50 per spec, pending resolution of feedback Issue 1); `validate_list_modules(params: dict) -> str` extracts optional `prefix` (default empty string); `limit` clamping is silent — no error returned for out-of-range values per spec Section 6 design choice; unit tests cover: missing required params, empty strings, whitespace-only strings, out-of-range limits clamped correctly, invalid relation values, empty symbol lists, valid inputs for each tool

### Phase D: Pipeline Interface and Response Formatting

- [ ] **T7: Pipeline interface protocol** — Define abstract interface the tool handlers call into
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 2 (scope boundary); [pipeline.md](../specification/pipeline.md)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/server/pipeline_interface.py`
  - **Done when:** `PipelineInterface` (`typing.Protocol`) defines methods: `search_by_name(pattern: str, limit: int) -> list[tuple[int, float]]`, `search_by_type(type_expr: str, limit: int) -> list[tuple[int, float]]`, `search_by_structure(expression: str, limit: int) -> list[tuple[int, float]]`, `search_by_symbols(symbols: list[str], limit: int) -> list[tuple[int, float]]`; each method returns a list of `(decl_id, score)` pairs ordered by score descending; `PipelineParseError` exception class with `detail: str` attribute for invalid Coq expression errors; each method may raise `PipelineParseError`

- [ ] **T8: Response formatters** — Convert internal storage/pipeline types to MCP response types and JSON
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Sections 5, response envelope format
  - **Depends on:** T2
  - **Produces:** `src/coq_search/server/formatters.py`
  - **Done when:** `format_search_result(row, score: float) -> SearchResult` maps declaration row fields to `SearchResult`; `type` field set to empty string if source `type_expr` is None; `format_lemma_detail(row, dependencies: list[str], dependents: list[str]) -> LemmaDetail` sets `score=1.0`, `proof_sketch=""` (Phase 1), parses `symbol_set` JSON (empty list for `"[]"` or None), reads `node_count` from row; `format_module(name: str, decl_count: int) -> Module` constructs Module; `wrap_success_response(data: dict | list[dict]) -> dict` wraps in MCP success envelope `{"content": [{"type": "text", "text": "<JSON>"}]}`; unit tests verify correct field mapping, None handling, and valid JSON output

### Phase E: Tool Handlers

- [ ] **T9: `search_by_name` handler** — Implement the search-by-name tool handler
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4.1; [pipeline.md](../specification/pipeline.md) Section 6; [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name)
  - **Depends on:** T2, T3, T5, T6, T7, T8, pipeline tasks (search_by_name flow)
  - **Produces:** `handle_search_by_name` in `src/coq_search/server/tools.py`
  - **Done when:** Handler validates input via `validate_search_by_name`, checks index state via `check_ready()`, dispatches to pipeline `search_by_name` function, fetches declaration rows for returned decl_ids, converts to `SearchResult` dicts via formatters, returns MCP success response; pipeline `PipelineParseError` caught and translated to `PARSE_ERROR` response; empty result list is a valid (non-error) response; unit tests with mock pipeline verify: valid request returns formatted results, empty pattern raises PARSE_ERROR, pipeline error becomes PARSE_ERROR response, index-missing state returns INDEX_MISSING error

- [ ] **T10: `search_by_type` handler** — Implement the search-by-type tool handler
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4.2; [pipeline.md](../specification/pipeline.md) Section 4; [Story 2.3](../doc/requirements/stories/tree-search-mcp.md#23-search-by-type)
  - **Depends on:** T2, T3, T5, T6, T7, T8, pipeline tasks (search_by_type flow)
  - **Produces:** `handle_search_by_type` in `src/coq_search/server/tools.py`
  - **Done when:** Handler validates input, checks index state, dispatches to pipeline `search_by_type` (multi-channel: WL + MePo + FTS5 fused via RRF), converts results to `SearchResult` dicts; Coq expression parse errors from pipeline caught and returned as `PARSE_ERROR`; unit tests with mock pipeline verify valid request, parse error propagation, and result formatting

- [ ] **T11: `search_by_structure` handler** — Implement the search-by-structure tool handler
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4.3; [pipeline.md](../specification/pipeline.md) Section 3; [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T2, T3, T5, T6, T7, T8, pipeline tasks (search_by_structure flow)
  - **Produces:** `handle_search_by_structure` in `src/coq_search/server/tools.py`
  - **Done when:** Handler validates input, checks index state, dispatches to pipeline `search_by_structure` (WL screening + fine-ranking), converts results to `SearchResult` dicts; Coq expression parse errors caught and returned as `PARSE_ERROR`; unit tests with mock pipeline verify valid request, parse error, and structural scoring result formatting

- [ ] **T12: `search_by_symbols` handler** — Implement the search-by-symbols tool handler
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4.4; [pipeline.md](../specification/pipeline.md) Section 5; [Story 2.5](../doc/requirements/stories/tree-search-mcp.md#25-search-by-symbols)
  - **Depends on:** T2, T3, T5, T6, T7, T8, pipeline tasks (search_by_symbols flow)
  - **Produces:** `handle_search_by_symbols` in `src/coq_search/server/tools.py`
  - **Done when:** Handler validates input, checks index state, dispatches to pipeline `search_by_symbols` (MePo channel), converts results to `SearchResult` dicts; unit tests with mock pipeline verify valid request, empty symbol list raises PARSE_ERROR, and MePo-ranked result formatting

- [ ] **T13: `get_lemma` handler** — Implement the get-lemma tool handler
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4.5; [Story 2.6](../doc/requirements/stories/tree-search-mcp.md#26-get-lemma-details)
  - **Depends on:** T2, T3, T5, T6, T8
  - **Produces:** `handle_get_lemma` in `src/coq_search/server/tools.py`
  - **Done when:** Handler validates `name` via `validate_get_lemma`, checks index state, performs direct database lookup on `declarations` table by `name`; if not found, returns `NOT_FOUND` error with message `"Declaration '<name>' not found in index."`; if found, queries `dependencies` table for forward `uses` edges (this declaration as `src`) to populate `dependencies` list, and reverse `uses` edges (this declaration as `dst`) to populate `dependents` list; parses `symbol_set` JSON from declaration row; constructs `LemmaDetail` with `score=1.0`, `proof_sketch=""` (see feedback Issue 6), `symbols` from parsed JSON, `node_count` from declaration row; returns wrapped MCP success response; handles NULL `type_expr` (empty string) and empty `symbol_set` (`"[]"` -> empty list); unit tests with in-memory database verify: found declaration returns full LemmaDetail, missing declaration returns NOT_FOUND, dependencies and dependents correctly populated

- [ ] **T14: `find_related` handler** — Implement the find-related tool handler
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4.6; [Story 2.7](../doc/requirements/stories/tree-search-mcp.md#27-find-related-declarations)
  - **Depends on:** T2, T3, T5, T6, T8
  - **Produces:** `handle_find_related` in `src/coq_search/server/tools.py`
  - **Done when:** Handler validates input via `validate_find_related`, checks index state, looks up source declaration by name (returns `NOT_FOUND` if absent); dispatches by relation type: `uses` — queries `dependencies` where `src=decl_id` and `relation='uses'`, joins to `declarations` for result fields; `used_by` — queries `dependencies` where `dst=decl_id` and `relation='uses'`, joins to `declarations`; `same_module` — queries `declarations` where `module` matches the source declaration's module, excludes self; `same_typeclass` — two-hop query: finds typeclasses the source is `instance_of` via `dependencies`, then finds other declarations that are `instance_of` the same typeclasses (see feedback Issue 7); all results formatted as `SearchResult` with `score=1.0` (graph traversal, no relevance ranking); results limited by validated `limit` parameter; returns empty array (not error) when relation has no matching edges; unit tests with in-memory database verify all four relation types, NOT_FOUND for missing declaration, limit enforcement, empty result for no-match cases

- [ ] **T15: `list_modules` handler** — Implement the list-modules tool handler
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4.7; [Story 2.8](../doc/requirements/stories/tree-search-mcp.md#28-list-modules)
  - **Depends on:** T2, T3, T5, T8
  - **Produces:** `handle_list_modules` in `src/coq_search/server/tools.py`
  - **Done when:** Handler validates input via `validate_list_modules`, checks index state, executes aggregation query: `SELECT module, COUNT(*) FROM declarations GROUP BY module ORDER BY module`; when prefix is non-empty, adds `WHERE module LIKE ? || '%'` filter; converts results to `Module` dicts; returns empty array for empty index; unit tests with in-memory database verify: no prefix returns all modules, prefix filters correctly, alphabetical ordering, declaration counts accurate

### Phase F: MCP Server Core

- [ ] **T16: MCP tool schema definitions** — Define JSON Schema for each tool's input parameters
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4; [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server)
  - **Depends on:** None
  - **Produces:** `src/coq_search/server/tool_schemas.py`
  - **Done when:** Each of the 7 tools has a JSON Schema definition specifying: tool name, human-readable description, required and optional parameters with types; `search_by_name`: `pattern` (string, required), `limit` (integer, optional); `search_by_type`: `type_expr` (string, required), `limit` (integer, optional); `search_by_structure`: `expression` (string, required), `limit` (integer, optional); `search_by_symbols`: `symbols` (array of strings, required), `limit` (integer, optional); `get_lemma`: `name` (string, required); `find_related`: `name` (string, required), `relation` (string, required, enum of `uses`, `used_by`, `same_module`, `same_typeclass`), `limit` (integer, optional); `list_modules`: `prefix` (string, optional); schemas exportable as dicts for MCP tool registration; unit tests verify each schema is valid JSON Schema and contains correct required/optional fields

- [ ] **T17: MCP server entry point and tool registration** — Implement the stdio MCP server with tool registration and lifecycle
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Sections 3, 8; [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server)
  - **Depends on:** T4, T5, T7, T8, T9, T10, T11, T12, T13, T14, T15, T16
  - **Produces:** `src/coq_search/server/__main__.py`, `src/coq_search/server/app.py`
  - **Done when:** `python -m coq_search.server` starts an MCP server over stdio; server accepts `--db-path` command-line argument for the database file location (default: platform-appropriate data directory); server accepts `--log-level` argument (default: `INFO`); on startup: runs index validation (T4), loads in-memory data (T5) if index is healthy, registers all 7 tool handlers with their MCP tool definitions from T16; enters stdio message loop reading JSON-RPC from stdin, writing responses to stdout; all diagnostic logging goes to stderr (never stdout); on stdin EOF or SIGTERM: closes database connection, exits with code 0; MCP configuration compatible with `~/.claude/mcp_servers.json` format: `{"coq-search": {"command": "python", "args": ["-m", "coq_search.server"], "env": {}}}`; each tool handler first calls `check_ready()` to verify index state before dispatch; on unexpected exception: logs traceback to stderr, returns PARSE_ERROR with generic message; single-threaded event loop per spec Section 9; unit tests verify: tool registration produces exactly 7 tools, `--help` is informative, startup with missing database sets INDEX_MISSING state

- [ ] **T18: Add `mcp` SDK dependency** — Declare the `mcp` Python package as a runtime dependency
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 3 (MCP protocol)
  - **Depends on:** None
  - **Produces:** Updated `pyproject.toml` (or equivalent dependency file)
  - **Done when:** `mcp` appears in runtime dependencies; `pip install -e .` installs the `mcp` package; version pin or compatible range is documented

- [ ] **T19: Wire up server package exports** — Update `server/__init__.py` to re-export public API
  - **Traces to:** [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server)
  - **Depends on:** T2, T3, T4, T7
  - **Produces:** Updated `src/coq_search/server/__init__.py`
  - **Done when:** Module re-exports: `SearchResult`, `LemmaDetail`, `Module`, `ErrorCode`, `ServerError`, `PipelineInterface`, `PipelineParseError`; `from coq_search.server import SearchResult` works

### Phase G: Unit Tests

- [ ] **T20: Unit tests — response types** — Test serialization and field completeness of response dataclasses
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 5
  - **Depends on:** T2
  - **Produces:** `tests/server/test_response_types.py`
  - **Done when:** Tests verify: `SearchResult.to_dict()` returns all 6 fields with correct keys; `LemmaDetail.to_dict()` returns all 11 fields; `LemmaDetail` includes all `SearchResult` fields; `Module.to_dict()` returns both fields; score values within [0.0, 1.0] range accepted; kind field accepts all 7 valid kind values

- [ ] **T21: Unit tests — error formatting** — Test structured error response formatting
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 7
  - **Depends on:** T3
  - **Produces:** `tests/server/test_errors.py`
  - **Done when:** Tests verify: each of the 4 error codes (INDEX_MISSING, INDEX_VERSION_MISMATCH, NOT_FOUND, PARSE_ERROR) produces a valid MCP error response with `isError: true`; `format_error` output `text` field contains valid parseable JSON; error code string values match spec exactly; `ServerError` exception carries code and message; message template formatting produces correct strings with placeholder substitution

- [ ] **T22: Unit tests — input validation** — Test all validation rules from spec Section 6
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 6
  - **Depends on:** T6
  - **Produces:** `tests/server/test_validators.py`
  - **Done when:** Tests cover every row in the spec validation table: missing required parameter raises `PARSE_ERROR` for each tool; empty string for required string parameters raises `PARSE_ERROR`; whitespace-only string raises `PARSE_ERROR`; `limit=0` clamped to 1; `limit=999` clamped to 200; `limit=-5` clamped to 1; default limit is 50 when omitted; invalid `relation` value raises `PARSE_ERROR` listing valid values; `symbols` as empty list raises `PARSE_ERROR`; `symbols` with empty string element raises `PARSE_ERROR`; valid inputs for each tool return correctly typed tuples; limit clamping produces no error (silent)

- [ ] **T23: Unit tests — index state** — Test startup validation logic
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 8.1; [storage.md](../specification/storage.md) Section 6
  - **Depends on:** T4
  - **Produces:** `tests/server/test_index_state.py`
  - **Done when:** Tests use `tmp_path` with mock database files; missing database file returns `INDEX_MISSING` status; valid database with matching versions returns `HEALTHY` status; `schema_version` mismatch returns `INDEX_VERSION_MISMATCH`; `coq_version` mismatch returns `INDEX_VERSION_MISMATCH`; `mathcomp_version` mismatch returns `INDEX_VERSION_MISMATCH`; `check_ready()` raises `ServerError` with correct error code for non-HEALTHY states; `check_ready()` succeeds silently for HEALTHY state

- [ ] **T24: Unit tests — data loader** — Test in-memory data loading from SQLite
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 8.1 steps 5-7
  - **Depends on:** T5
  - **Produces:** `tests/server/test_data_loader.py`
  - **Done when:** Tests use in-memory SQLite with the full schema and synthetic data; `load_wl_histograms` returns correct dict structure keyed by decl_id with parsed histogram dicts; only h=3 rows are loaded (not h=1 or h=5); `load_symbol_index` builds correct inverted index from symbol_set JSON; shared symbols map to multiple decl_ids; `load_symbol_freq` returns correct symbol-to-count mapping; `ServerData` bundles all structures correctly; empty tables produce empty structures without errors

- [ ] **T25: Unit tests — response formatters** — Test conversion from storage types to response types
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 5
  - **Depends on:** T8
  - **Produces:** `tests/server/test_formatters.py`
  - **Done when:** Tests verify: `format_search_result` maps row fields correctly; `type_expr=None` becomes `type=""` in output; `format_lemma_detail` sets `score=1.0` and `proof_sketch=""` and parses `symbol_set` JSON correctly; `format_module` produces correct field mapping; `wrap_success_response` produces valid MCP envelope; output is valid JSON when serialized

- [ ] **T26: Unit tests — tool handlers** — Test each tool handler with mock dependencies
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Sections 4, 10
  - **Depends on:** T9, T10, T11, T12, T13, T14, T15
  - **Produces:** `tests/server/test_tools.py`
  - **Done when:** Tests mock the pipeline layer and use in-memory SQLite for database-backed tools; search tools: valid input returns list of `SearchResult` dicts, index-missing state returns structured error, pipeline parse errors translated correctly to PARSE_ERROR; `get_lemma`: found returns `LemmaDetail` with `score=1.0` and `proof_sketch=""`, not found returns `NOT_FOUND`; `find_related`: all 4 relation types return correct results, invalid relation returns PARSE_ERROR, NOT_FOUND for missing name; `list_modules`: prefix filtering and alphabetical ordering verified; all responses are well-formed MCP tool responses (valid JSON in content field)

- [ ] **T27: Unit tests — MCP tool registration** — Verify tool definitions match the spec
  - **Traces to:** [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server) AC2 (7 tools)
  - **Depends on:** T17
  - **Produces:** `tests/server/test_tool_registration.py`
  - **Done when:** Tests create a server instance without entering the message loop; exactly 7 tools are registered; tool names match spec: `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules`; each tool has a non-empty description; required parameters match spec (e.g., `find_related` requires `name` and `relation`); `find_related`'s `relation` parameter has enum with exactly four values; `list_modules` has no required parameters

### Phase H: Integration Tests

- [ ] **T28: Integration test — tool call round-trip** — End-to-end test from tool call args to MCP response
  - **Traces to:** [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server) AC3; [mcp-server.md](../specification/mcp-server.md) Section 10
  - **Depends on:** T17
  - **Produces:** `tests/server/test_integration.py`
  - **Done when:** Test creates a temporary SQLite database with ~20 synthetic declarations across 3 modules, with dependencies, `instance_of` edges, WL vectors, symbols, and varied kinds; populates `index_meta` with matching versions; uses mock `PipelineInterface`; exercises: `search_by_name` returns results formatted as MCP response; `get_lemma` with known name returns `LemmaDetail` with all 11 fields; `get_lemma` with unknown name returns NOT_FOUND matching spec Section 10 example format; `find_related` with each relation type returns correct results; `list_modules` returns all modules with correct counts; any tool called when index is missing returns INDEX_MISSING error; all responses conform to the MCP envelope format; all error responses have `isError: true`

- [ ] **T29: Integration test — stdio transport** — Full server process via subprocess stdin/stdout
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 3; [Story 2.1](../doc/requirements/stories/tree-search-mcp.md#21-start-the-mcp-server) AC1
  - **Depends on:** T17
  - **Produces:** `tests/server/test_stdio.py`
  - **Done when:** Test starts `python -m coq_search.server --db-path <tmp_db>` as a subprocess; sends MCP `initialize` request via stdin and receives valid response via stdout; sends `tools/list` request and response lists 7 tools; sends `tools/call` for `list_modules` and receives valid tool result; sends stdin EOF and process exits cleanly with code 0; no non-protocol data appears on stdout; test is marked `@pytest.mark.slow`

- [ ] **T30: Integration test — error scenarios** — End-to-end error handling through the MCP server
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Sections 6, 7; [Story 6.1](../doc/requirements/stories/tree-search-mcp.md#61-missing-index)
  - **Depends on:** T17
  - **Produces:** `tests/server/test_error_integration.py`
  - **Done when:** Server started with no database file returns `INDEX_MISSING` for every tool call; server started with wrong `schema_version` returns `INDEX_VERSION_MISMATCH` for every tool call; `get_lemma` with nonexistent name returns `NOT_FOUND`; `search_by_type` with invalid expression returns `PARSE_ERROR` (with mock pipeline raising parse error); `find_related` with invalid relation returns `PARSE_ERROR` listing valid values; all error responses have `isError: true` and the correct error code

### Phase I: Performance Tests

- [ ] **T31: Performance test — startup latency** — Verify server startup completes within NFR target
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 9 (memory < 500 MB); [storage.md](../specification/storage.md) Section 8 (startup < 2s)
  - **Depends on:** T17
  - **Produces:** `tests/server/test_performance.py`
  - **Done when:** Test (marked `@pytest.mark.performance`, skipped in CI by default) creates a database with representative WL histograms and symbol data for 50K synthetic declarations; measures wall-clock time for full startup sequence (index validation + data loading); asserts startup completes in < 3 seconds; memory usage of `ServerData` measured and reported; WL histogram memory fits within ~200 MB estimate from spec Section 9

- [ ] **T32: Performance test — tool call overhead** — Verify validation and formatting overhead is within NFR target
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 9 (response time < 1s)
  - **Depends on:** T17
  - **Produces:** Additional tests in `tests/server/test_performance.py`
  - **Done when:** Test measures time spent in validation and formatting (excluding pipeline/storage execution) for each tool type; mock pipeline returns immediately; asserts each handler completes validation + formatting in < 10ms; test is marked `@pytest.mark.performance`
