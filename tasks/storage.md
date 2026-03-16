# Implementation Plan: SQLite Storage Layer

**Specification:** [specification/storage.md](../specification/storage.md)
**Architecture:** [doc/architecture/storage.md](../doc/architecture/storage.md)
**Data Structures:** [specification/data-structures.md](../specification/data-structures.md)
**Data Model:** [doc/architecture/data-models/index-entities.md](../doc/architecture/data-models/index-entities.md)
**Feedback:** [specification/feedback/storage.md](../specification/feedback/storage.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, NodeLabel, WlHistogram, SymbolSet types
- [extraction.md](../specification/extraction.md) — Consumer of IndexWriter (sole write path)
- [pipeline.md](../specification/pipeline.md) — Consumer of IndexReader (query serving)

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, `NodeLabel` hierarchy (all concrete subtypes), `WlHistogram`, `SymbolSet` type aliases.
2. The `coq_search` package root (`src/coq_search/__init__.py`) must exist.
3. Python >= 3.8 (required for pickle protocol 5).
4. SQLite >= 3.27.0 preferred (for `remove_diacritics 2`); the implementation must handle fallback to older SQLite with `remove_diacritics 1`.
5. SQLite must be compiled with FTS5 extension (verified at runtime by T5).

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **IndexWriter and IndexReader as separate classes** with distinct state machines. The spec describes read/write "contracts" but does not name the classes or define their interfaces. This plan follows the architecture doc's implied `IndexWriter` / `IndexReader` split (see feedback Issue 6).
- **Write-path PRAGMAs** follow the architecture doc (`PRAGMA synchronous = OFF`, `PRAGMA journal_mode = MEMORY`) rather than the spec, which omits them entirely. The spec's silence is treated as an oversight (see feedback Issue 3).
- **`node_count` and `symbol_set` are treated as NOT NULL** per the architecture doc and data model, despite the spec DDL omitting these constraints (see feedback Issue 1).
- **`AUTOINCREMENT` is omitted** from the `declarations.id` definition, following the architecture doc over the spec (see feedback Issue 2). SQLite's `INTEGER PRIMARY KEY` already auto-assigns rowids.
- **BM25 column weights** (`name=10.0, statement=1.0, module=5.0`) are taken from the data model, which the spec does not specify (see feedback Issue 4).
- **Batch insert fallback** uses row-by-row insertion on IntegrityError, following the architecture doc's "Batch commits" section. The spec's error table says "Abort transaction, log, continue with remaining declarations" for FK violations, which this plan interprets as skipping the violating row, not aborting the entire batch.

---

## Tasks

### Phase A: Foundation (errors, types, schema)

- [ ] **T1: Create storage subpackage skeleton** — Create the `storage` subpackage directory and `__init__.py`
  - **Traces to:** [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library) AC4 (database contains all required data)
  - **Depends on:** None
  - **Produces:** `src/coq_search/storage/__init__.py`
  - **Done when:** `from coq_search.storage` imports without error; the `__init__.py` exists and contains a module docstring

- [ ] **T2: Define storage error types** — Implement the error class hierarchy for all storage failure modes
  - **Traces to:** [storage.md](../specification/storage.md) Section 7 (Error Specification); [Story 6.1](../doc/requirements/stories/tree-search-mcp.md#61-missing-index) (missing index error)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/storage/errors.py`
  - **Done when:** Module exports `StorageError` (base), `IndexMissingError`, `IndexVersionMismatchError`, `IndexCorruptError`, `FtsParseError`; all inherit from `StorageError`; `IndexVersionMismatchError` accepts `key`, `expected`, `actual` arguments and includes them in its string representation; `FtsParseError` accepts `query` and `detail` arguments; each error type is importable by name

- [ ] **T3: Define row data types** — Implement typed data classes for database rows exchanged across the storage API boundary
  - **Traces to:** [storage.md](../specification/storage.md) Section 3 (Schema Definition)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/storage/types.py` (re-exported from `__init__.py`)
  - **Done when:** `DeclarationRow` is a dataclass with fields matching the `declarations` table: `id` (int | None for inserts), `name` (str), `module` (str), `kind` (str), `statement` (str), `type_expr` (str | None), `constr_tree` (bytes | None), `node_count` (int), `symbol_set` (str — JSON array); `DependencyRow` is a NamedTuple with fields: `src` (int), `dst` (int), `relation` (str); `WlVectorRow` is a NamedTuple with fields: `decl_id` (int), `h` (int), `histogram` (str — JSON object); all types are importable from `coq_search.storage`

- [ ] **T4: Implement schema DDL module** — Define all SQL CREATE statements, indexes, FTS5 virtual table, schema version constant, and a `create_all_tables` function
  - **Traces to:** [storage.md](../specification/storage.md) Section 3 (Schema Definition); [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library) AC5 (recorded schema version); [Story 1.5](../doc/requirements/stories/tree-search-mcp.md#15-index-version-compatibility) (index version compatibility)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/storage/schema.py`
  - **Done when:** Module defines `SCHEMA_VERSION = 1`; `REQUIRED_META_KEYS` frozenset contains `schema_version`, `coq_version`, `mathcomp_version`, `created_at`; `create_all_tables(conn)` executes all DDL with the following verified properties: `declarations` table has `id INTEGER PRIMARY KEY` (no AUTOINCREMENT), CHECK constraint on `kind` for the 7 Phase 1 values (`Lemma`, `Theorem`, `Definition`, `Inductive`, `Constructor`, `Instance`, `Axiom`), `node_count INTEGER NOT NULL`, `symbol_set TEXT NOT NULL`, UNIQUE on `name`, indexes on `module` and `kind`; `dependencies` table has composite PK `(src, dst, relation)`, NOT NULL on `src`/`dst`, foreign keys to `declarations(id)`, and index on `dst`; `wl_vectors` has composite PK `(decl_id, h)`, CHECK on `h IN (1, 3, 5)`, FK to `declarations(id)`; `symbol_freq` has TEXT PK and `freq > 0` CHECK; `index_meta` has TEXT PK; `declarations_fts` FTS5 virtual table uses `content=declarations, content_rowid=id`; tokenizer determined by `get_tokenizer_config()` (see T5); FTS5 virtual table is created after `declarations` table; function enables `PRAGMA foreign_keys = ON` before DDL execution

- [ ] **T5: Implement FTS5 and SQLite version checks** — Runtime verification that FTS5 is available and SQLite version supports required features
  - **Traces to:** [storage.md](../specification/storage.md) Section 3.6 (FTS5 tokenizer configuration); [storage.md](../specification/storage.md) Section 8 (portability)
  - **Depends on:** T2, T4
  - **Produces:** Functions in `src/coq_search/storage/schema.py`: `check_fts5_available(conn)` and `get_tokenizer_config()`
  - **Done when:** `check_fts5_available` creates and drops a temporary FTS5 table; raises `StorageError` with a clear message if FTS5 is not compiled in; `get_tokenizer_config()` returns `'porter unicode61 remove_diacritics 2'` if `sqlite3.sqlite_version_info >= (3, 27, 0)`, otherwise returns `'porter unicode61 remove_diacritics 1'` and logs a warning; `create_all_tables` uses `get_tokenizer_config()` for the FTS5 tokenizer

### Phase B: Serialization

- [ ] **T6: Implement ExprTree serialization** — Serialize and deserialize `ExprTree` objects using pickle protocol 5
  - **Traces to:** [storage.md](../specification/storage.md) Section 9.1 (ExprTree Serialization)
  - **Depends on:** T1, T2; data structures module (`ExprTree` type)
  - **Produces:** `src/coq_search/storage/serialization.py`
  - **Done when:** `serialize_expr_tree(tree: ExprTree) -> bytes` serializes using `pickle.dumps(tree, protocol=5)`; `deserialize_expr_tree(data: bytes) -> ExprTree` deserializes and validates result is an `ExprTree` instance, raising `StorageError` with a descriptive message if not; round-trip preserves all labels, children structure, depths, node_ids, and node_count; the serialization format is internal (not a public API)

### Phase C: Write path

- [ ] **T7: Implement IndexWriter core — create, close, context manager** — Create the `IndexWriter` class with lifecycle management
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.1 (Write Path); [doc/architecture/storage.md](../doc/architecture/storage.md) (Write Path, write-path pragmas); [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library) AC1
  - **Depends on:** T2, T4, T5
  - **Produces:** `src/coq_search/storage/writer.py`
  - **Done when:** `IndexWriter(db_path)` stores the path without opening a connection (Initialized state); `create()` deletes any existing file at the path, opens a new connection, sets write-path PRAGMAs (`PRAGMA foreign_keys = ON`, `PRAGMA synchronous = OFF`, `PRAGMA journal_mode = MEMORY` per architecture doc), calls `check_fts5_available()`, calls `create_all_tables()`, transitions to Open state; `close()` closes the connection, transitions to Closed state; class implements `__enter__` (returns self after `create()`) and `__exit__` (calls `close()`); calling methods in wrong state raises `StorageError`

- [ ] **T8: Implement write path — batch declaration inserts** — Add `insert_declarations` with batched transactions and fallback
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.1 step 3 (batch commits every 1,000 rows); [doc/architecture/storage.md](../doc/architecture/storage.md) (Batch commits); [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library) AC3 (individual failures logged)
  - **Depends on:** T3, T7
  - **Produces:** `insert_declarations` method in `src/coq_search/storage/writer.py`
  - **Done when:** Method accepts `Iterable[DeclarationRow]`; accumulates rows into a buffer of size 1,000; each full buffer is committed using `executemany` within a transaction; on `IntegrityError` for a batch, falls back to row-by-row insertion, logging and skipping individual failures via `logging.warning`; flushes remaining buffer after iteration completes; uses `INSERT INTO declarations (name, module, kind, statement, type_expr, constr_tree, node_count, symbol_set) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`

- [ ] **T9: Implement write path — batch WL vector inserts** — Add `insert_wl_vectors` with same batching pattern
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.1 step 3; [doc/architecture/storage.md](../doc/architecture/storage.md) (Batch commits — co-insert declarations and WL vectors in same batch)
  - **Depends on:** T3, T7
  - **Produces:** `insert_wl_vectors` method in `src/coq_search/storage/writer.py`
  - **Done when:** Method accepts `Iterable[WlVectorRow]`; uses identical batching and fallback pattern as T8 (buffer of 1,000, executemany, row-by-row fallback on IntegrityError); foreign key violations logged and skipped; uses `INSERT INTO wl_vectors (decl_id, h, histogram) VALUES (?, ?, ?)`

- [ ] **T10: Implement write path — batch dependency inserts** — Add `insert_dependencies` with same batching pattern
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.1 step 3; [storage.md](../specification/storage.md) Section 7 (FK violation during write)
  - **Depends on:** T3, T7
  - **Produces:** `insert_dependencies` method in `src/coq_search/storage/writer.py`
  - **Done when:** Method accepts `Iterable[DependencyRow]`; uses identical batching and fallback pattern as T8; foreign key violations (referencing nonexistent declarations) logged and skipped; uses `INSERT INTO dependencies (src, dst, relation) VALUES (?, ?, ?)`

- [ ] **T11: Implement write path — symbol frequency inserts** — Add `insert_symbol_freq` in a single transaction with validation
  - **Traces to:** [storage.md](../specification/storage.md) Section 3.4 (symbol_freq table); [data-structures.md](../specification/data-structures.md) Section 5 (freq >= 1 invariant)
  - **Depends on:** T7
  - **Produces:** `insert_symbol_freq` method in `src/coq_search/storage/writer.py`
  - **Done when:** Method accepts `dict[str, int]`; validates all freq values are > 0 before any insertion, raising `ValueError` if any are not; inserts all rows in a single transaction using `executemany`; uses `INSERT INTO symbol_freq (symbol, freq) VALUES (?, ?)`

- [ ] **T12: Implement write path — FTS rebuild, metadata, finalize** — Add `rebuild_fts`, `set_meta`, and `finalize` methods
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.1 steps 4-6 (FTS rebuild, metadata, integrity check); [storage.md](../specification/storage.md) Section 3.5 (required metadata keys); [doc/architecture/storage.md](../doc/architecture/storage.md) (Integrity check)
  - **Depends on:** T4, T7
  - **Produces:** `rebuild_fts`, `set_meta`, `finalize` methods in `src/coq_search/storage/writer.py`
  - **Done when:** `rebuild_fts()` executes `INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')`; `set_meta(coq_version, mathcomp_version, created_at)` inserts all four required keys including `schema_version` from the `SCHEMA_VERSION` constant, using `INSERT OR REPLACE INTO index_meta`; `finalize()` verifies all `REQUIRED_META_KEYS` exist in `index_meta`, executes `PRAGMA integrity_check` and verifies result is `"ok"`, transitions to Finalized state on success; on failure: closes the connection, deletes the database file, raises `IndexCorruptError` (close-delete-raise ordering per architecture doc)

### Phase D: Read path

- [ ] **T13: Implement IndexReader core — open, validate, close, context manager** — Create the `IndexReader` class with startup validation
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.2 (Read Path); [storage.md](../specification/storage.md) Section 6 (Index Lifecycle); [Story 1.4](../doc/requirements/stories/tree-search-mcp.md#14-detect-and-rebuild-stale-indexes); [Story 1.5](../doc/requirements/stories/tree-search-mcp.md#15-index-version-compatibility); [Story 6.1](../doc/requirements/stories/tree-search-mcp.md#61-missing-index)
  - **Depends on:** T2, T4
  - **Produces:** `src/coq_search/storage/reader.py`
  - **Done when:** `IndexReader(db_path)` stores the path (Initialized state); `open()` checks file existence (raises `IndexMissingError` if not found); opens read-only connection via `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)`; loads all `index_meta` rows into a dict; verifies all `REQUIRED_META_KEYS` present (raises `IndexCorruptError` if not); compares `schema_version` against `SCHEMA_VERSION` constant (raises `IndexVersionMismatchError` with `key="schema_version"`, `expected`, `actual` on mismatch); transitions to Open state; `get_meta(key)` returns stored metadata value for caller-side version comparison (coq_version, mathcomp_version); `close()` closes connection and clears in-memory structures (Closed state); class implements `__enter__` (calls `open()`, returns self) and `__exit__` (calls `close()`)

- [ ] **T14: Implement read path — in-memory WL histogram loading** — Load h=3 WL histograms into memory at startup
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.2 (load all wl_vectors h=3 into memory at startup); [storage.md](../specification/storage.md) Section 8 (startup latency < 2s for 50K)
  - **Depends on:** T13
  - **Produces:** `wl_histograms` property in `src/coq_search/storage/reader.py`
  - **Done when:** During `open()`, executes `SELECT decl_id, histogram FROM wl_vectors WHERE h = 3`; parses each histogram JSON string into `dict[str, int]` via `json.loads`; stores as `dict[int, dict[str, int]]` keyed by `decl_id`; exposed as `wl_histograms` property; memory-resident for the lifetime of the reader

- [ ] **T15: Implement read path — in-memory inverted symbol index** — Build the symbol-to-decl_id inverted index at startup
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.2 (build in-memory inverted index from declarations.symbol_set)
  - **Depends on:** T13
  - **Produces:** `inverted_symbol_index` property in `src/coq_search/storage/reader.py`
  - **Done when:** During `open()`, executes `SELECT id, symbol_set FROM declarations`; for each row, parses `symbol_set` JSON array; for each symbol, adds the declaration `id` to a `dict[str, set[int]]`; exposed as `inverted_symbol_index` property

- [ ] **T16: Implement read path — in-memory symbol frequency loading** — Load the symbol_freq table into memory at startup
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.2 (build in-memory symbol_freq lookup)
  - **Depends on:** T13
  - **Produces:** `symbol_frequencies` property in `src/coq_search/storage/reader.py`
  - **Done when:** During `open()`, executes `SELECT symbol, freq FROM symbol_freq`; stores as `dict[str, int]`; exposed as `symbol_frequencies` property

- [ ] **T17: Implement read path — declaration lookup methods** — Add declaration query methods for use by retrieval pipeline and MCP server
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.2 (SQLite for declaration lookups); [Story 2.6](../doc/requirements/stories/tree-search-mcp.md#26-get-lemma-details) (get lemma details); [Story 2.8](../doc/requirements/stories/tree-search-mcp.md#28-list-modules) (list modules)
  - **Depends on:** T3, T13
  - **Produces:** Query methods in `src/coq_search/storage/reader.py`
  - **Done when:** `get_declaration(decl_id: int) -> DeclarationRow | None` returns a single row by primary key or None; `get_declarations_by_ids(decl_ids: list[int]) -> list[DeclarationRow]` returns rows preserving input order, silently skipping missing IDs; `get_declaration_by_name(name: str) -> DeclarationRow | None` returns a single row by unique name or None; `list_modules() -> list[str]` returns `SELECT DISTINCT module FROM declarations ORDER BY module`; `get_declarations_by_module(module: str) -> list[DeclarationRow]` returns all declarations in the given module

- [ ] **T18: Implement read path — FTS search** — Add `fts_search` method with BM25 ranking and error handling
  - **Traces to:** [storage.md](../specification/storage.md) Section 3.6 (FTS5 virtual table); [doc/architecture/data-models/index-entities.md](../doc/architecture/data-models/index-entities.md) (BM25 column weights); [storage.md](../specification/storage.md) Section 7 (FTS query syntax error); [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name) (search by name)
  - **Depends on:** T2, T13
  - **Produces:** `fts_search` method in `src/coq_search/storage/reader.py`
  - **Done when:** Method executes a BM25-weighted FTS5 query with column weights `name=10.0, statement=1.0, module=5.0` (from data model); returns `list[tuple[int, float]]` of `(decl_id, bm25_score)` pairs; accepts `limit` parameter with default of 20; catches `sqlite3.OperationalError` from invalid FTS5 syntax and wraps in `FtsParseError` with original query and error detail; returns empty list for queries that match nothing

- [ ] **T19: Implement read path — dependency graph queries** — Add `get_dependencies` and `get_reverse_dependencies`
  - **Traces to:** [storage.md](../specification/storage.md) Section 3.2 (dependencies table, idx_dependencies_dst index); [Story 2.7](../doc/requirements/stories/tree-search-mcp.md#27-find-related-declarations) (find related declarations)
  - **Depends on:** T13
  - **Produces:** Dependency query methods in `src/coq_search/storage/reader.py`
  - **Done when:** `get_dependencies(decl_id: int, relation: str | None = None) -> list[tuple[int, str]]` returns `(dst_id, relation)` pairs; `get_reverse_dependencies(decl_id: int, relation: str | None = None) -> list[tuple[int, str]]` returns `(src_id, relation)` pairs; when `relation` is provided, only matching edges are returned; reverse lookups use the `idx_dependencies_dst` index

- [ ] **T20: Implement read path — ExprTree retrieval** — Add `get_constr_tree` method for on-demand tree deserialization
  - **Traces to:** [storage.md](../specification/storage.md) Section 9.1 (ExprTree Serialization); [storage.md](../specification/storage.md) Section 3.1 (constr_tree BLOB column)
  - **Depends on:** T6, T13
  - **Produces:** `get_constr_tree` method in `src/coq_search/storage/reader.py`
  - **Done when:** Method executes `SELECT constr_tree FROM declarations WHERE id = ?`; returns `None` if the row is missing or `constr_tree` is NULL; otherwise calls `deserialize_expr_tree(blob)` and returns the `ExprTree`; corrupted blobs raise `StorageError`

### Phase E: Package wiring

- [ ] **T21: Wire up package exports** — Update `storage/__init__.py` to re-export all public API types and classes
  - **Traces to:** [doc/architecture/component-boundaries.md](../doc/architecture/component-boundaries.md) (Storage component boundary)
  - **Depends on:** T2, T3, T6, T7, T13
  - **Produces:** Updated `src/coq_search/storage/__init__.py`
  - **Done when:** The following are importable from `coq_search.storage`: `IndexWriter`, `IndexReader`, `DeclarationRow`, `DependencyRow`, `WlVectorRow`, `StorageError`, `IndexMissingError`, `IndexVersionMismatchError`, `IndexCorruptError`, `FtsParseError`, `serialize_expr_tree`, `deserialize_expr_tree`, `SCHEMA_VERSION`; `__all__` is defined listing all public names

### Phase F: Tests

- [ ] **T22: Unit tests — error types** — Verify error hierarchy, attributes, and string representations
  - **Traces to:** [storage.md](../specification/storage.md) Section 7 (Error Specification)
  - **Depends on:** T2
  - **Produces:** `test/storage/test_errors.py`
  - **Done when:** Tests verify: all error types inherit from `StorageError`; `IndexVersionMismatchError` stores and displays `key`, `expected`, `actual`; `FtsParseError` stores and displays `query` and `detail`; `StorageError` is catchable as a base for all storage errors

- [ ] **T23: Unit tests — schema** — Test DDL creation, constraint enforcement, FTS5 availability
  - **Traces to:** [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library) AC4, AC5; [storage.md](../specification/storage.md) Section 3 (Schema Definition)
  - **Depends on:** T4, T5
  - **Produces:** `test/storage/test_schema.py`
  - **Done when:** Tests cover: `create_all_tables` produces all 6 tables (verified via `sqlite_master` query); FTS5 availability check passes on a normal Python install; `PRAGMA foreign_keys` is ON after schema creation; inserting a dependency with nonexistent `src` raises `IntegrityError`; `declarations.name` UNIQUE constraint rejects duplicates; NOT NULL constraints on `node_count` and `symbol_set` are enforced; `wl_vectors` composite PK `(decl_id, h)` rejects duplicates; `kind` CHECK constraint rejects invalid values; `symbol_freq.freq` CHECK constraint rejects 0 and negative values; `h` CHECK constraint rejects values outside `{1, 3, 5}`; all tests pass with `pytest`

- [ ] **T24: Unit tests — serialization** — Test ExprTree round-trip and error handling
  - **Traces to:** [storage.md](../specification/storage.md) Section 9.1 (ExprTree Serialization)
  - **Depends on:** T6; data structures module
  - **Produces:** `test/storage/test_serialization.py`
  - **Done when:** Tests cover: round-trip of a tree with leaf nodes (`LConst`, `LInd`, `LConstruct`, `LCseVar`) preserves all labels; round-trip of a tree with interior nodes (`LApp`, `LProd`, `LLambda`, `LLetIn`, `LProj`, `LCase`) preserves children ordering and label payloads; round-trip preserves `depth` and `node_id` values; `deserialize_expr_tree` on arbitrary non-pickle bytes raises `StorageError`; `deserialize_expr_tree` on a pickled non-ExprTree object (e.g., a dict) raises `StorageError`; all tests pass with `pytest`

- [ ] **T25: Unit tests — writer** — Test the full write lifecycle, batching, and error handling
  - **Traces to:** [storage.md](../specification/storage.md) Section 5.1 (Write Path); [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library) AC1, AC3
  - **Depends on:** T7, T8, T9, T10, T11, T12
  - **Produces:** `test/storage/test_writer.py`
  - **Done when:** Tests cover: `create()` produces a file with correct schema; `create()` deletes and replaces an existing database file; write-path PRAGMAs are set (`synchronous = OFF`, `journal_mode = MEMORY`); inserting a single declaration is retrievable via raw SQL; inserting 2,500 declarations (exceeding batch size) stores all 2,500 rows; duplicate declaration names are skipped with a log message (verified via `caplog`); dependency FK violations are logged and skipped; WL vector inserts store correct histograms; `insert_symbol_freq` with freq=0 raises `ValueError`; `insert_symbol_freq` stores all symbols correctly; `rebuild_fts` followed by FTS MATCH query returns results; `set_meta` stores all four required keys including auto-inserted `schema_version`; `finalize()` succeeds on a valid, complete database; `finalize()` raises `IndexCorruptError` and deletes the file when required metadata keys are missing; context manager usage (`with IndexWriter(...) as w:`) works correctly; all tests use `tmp_path` fixture; all tests pass with `pytest`

- [ ] **T26: Unit tests — reader** — Test startup validation, in-memory loading, and all query methods
  - **Traces to:** [storage.md](../specification/storage.md) Sections 5.2, 6; [Story 1.4](../doc/requirements/stories/tree-search-mcp.md#14-detect-and-rebuild-stale-indexes); [Story 1.5](../doc/requirements/stories/tree-search-mcp.md#15-index-version-compatibility); [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name); [Story 2.6](../doc/requirements/stories/tree-search-mcp.md#26-get-lemma-details); [Story 2.7](../doc/requirements/stories/tree-search-mcp.md#27-find-related-declarations); [Story 2.8](../doc/requirements/stories/tree-search-mcp.md#28-list-modules); [Story 6.1](../doc/requirements/stories/tree-search-mcp.md#61-missing-index)
  - **Depends on:** T13, T14, T15, T16, T17, T18, T19, T20
  - **Produces:** `test/storage/test_reader.py`
  - **Done when:** Tests use a shared fixture that creates a populated database via `IndexWriter`; tests cover: `open()` on nonexistent path raises `IndexMissingError`; `open()` with wrong `schema_version` raises `IndexVersionMismatchError` with correct `key`, `expected`, `actual`; `open()` with missing required meta key raises `IndexCorruptError`; `open()` populates `wl_histograms` with h=3 data only (not h=1 or h=5); `open()` populates `inverted_symbol_index` with correct symbol-to-decl_id mappings; `open()` populates `symbol_frequencies`; `get_meta("coq_version")` returns the stored value; `get_declaration` returns correct row for existing ID, None for missing; `get_declarations_by_ids` preserves input order, skips missing IDs; `get_declaration_by_name` returns correct row for existing name, None for missing; `list_modules` returns sorted distinct module names; `get_declarations_by_module` returns all declarations in a module; `fts_search` returns ranked results for a valid query; `fts_search` with invalid syntax raises `FtsParseError`; `fts_search` respects `limit` parameter; `fts_search` on empty index returns empty list; `get_dependencies` returns correct `(dst_id, relation)` pairs; `get_dependencies` with relation filter returns only matching edges; `get_reverse_dependencies` returns correct `(src_id, relation)` pairs; `get_constr_tree` returns deserialized tree for existing declaration, None for missing or NULL blob; context manager usage works correctly; all tests pass with `pytest`

- [ ] **T27: Integration test — full write-read lifecycle** — End-to-end test: write a database with synthetic data, read it back, verify all paths
  - **Traces to:** [storage.md](../specification/storage.md) Section 4 (Cross-Table Relationships); [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library) AC4 (database contains all required data)
  - **Depends on:** T25, T26
  - **Produces:** `test/storage/test_integration.py`
  - **Done when:** Test creates an `IndexWriter`, inserts ~100 synthetic declarations across multiple modules and kinds with varying symbol sets, inserts dependencies (including both `uses` and `instance_of` relations), inserts WL vectors at h=3 with realistic histogram data, inserts symbol frequencies, calls `rebuild_fts`, `set_meta`, `finalize`, `close`; opens an `IndexReader` on the same file; verifies `wl_histograms` has correct cardinality; verifies `inverted_symbol_index` maps symbols to correct declaration sets; verifies `symbol_frequencies` matches inserted data; runs FTS searches and verifies relevant results appear; fetches individual declarations by ID and name, verifying all fields; fetches dependency and reverse-dependency graphs; deserializes at least one `ExprTree` and verifies its structure matches what was inserted; verifies `get_meta` returns correct library versions; closes the reader; all assertions pass with `pytest`

- [ ] **T28: Performance test — startup latency** — Verify IndexReader.open() completes within 2 seconds for 50K declarations
  - **Traces to:** [storage.md](../specification/storage.md) Section 8 (startup latency < 2s for 50K declarations)
  - **Depends on:** T14, T25
  - **Produces:** `test/storage/test_performance.py`
  - **Done when:** Test creates a database with 50,000 declarations, each with a WL histogram at h=3 containing ~200 entries, and realistic symbol sets (~10 symbols each); measures wall-clock time of `IndexReader.open()` including all three in-memory structure loads; asserts total time < 2 seconds; test is marked with `@pytest.mark.slow` so it can be excluded from fast CI runs

- [ ] **T29: Edge case tests** — Cover boundary conditions and error recovery scenarios
  - **Traces to:** [storage.md](../specification/storage.md) Section 7 (Error Specification)
  - **Depends on:** T25, T26
  - **Produces:** `test/storage/test_edge_cases.py`
  - **Done when:** Tests cover: empty database (zero declarations) passes `finalize()` when all metadata keys present; dependency referencing nonexistent declaration is logged and skipped; WL vector for nonexistent declaration is logged and skipped; `get_declarations_by_ids` with a mix of existing and missing IDs returns only found rows in order; `get_constr_tree` for declaration with NULL `constr_tree` returns None; FTS search on empty (zero declarations) index returns empty list; read-only connection rejects write attempts (verifying `sqlite3.OperationalError`); corrupt database file raises `IndexCorruptError` on open; all tests pass with `pytest`
