# Task: Implement SQLite Storage Layer

**Specification**: [specification/storage.md](../../specification/storage.md)
**Architecture**: [doc/architecture/storage.md](../architecture/storage.md)
**Data Model**: [doc/architecture/data-models/index-entities.md](../architecture/data-models/index-entities.md)
**Data Structures**: [specification/data-structures.md](../../specification/data-structures.md)

---

## 1. Overview

Implement the SQLite storage layer as a Python module providing two access modes: a write interface for the extraction pipeline (offline, exclusive access) and a read interface for the retrieval pipeline and MCP server (online, read-only). The storage layer is the sole persistence mechanism for the entire system. It stores all indexed Coq declarations, precomputed WL histograms, dependency edges, symbol frequencies, FTS5 search index, and index lifecycle metadata.

This task produces the foundational persistence layer that all other components depend on. The extraction pipeline writes to it; the retrieval pipeline and MCP server read from it.

---

## 2. Dependencies

### Must Be Implemented Before This Task

- **`specification/data-structures.md`**: Defines `ExprTree`, `NodeLabel`, `WlHistogram`, `SymbolSet`, and `ScoredResult` types. The storage layer serializes and deserializes `ExprTree` and consumes/produces `WlHistogram` and `SymbolSet` types.

### Must Be Implemented Before This Task Can Be Fully Tested

- None. The storage layer can be tested independently with synthetic data.

### Components That Depend On This Task

- **Extraction pipeline** (`specification/extraction.md`): Calls the write interface.
- **Retrieval pipeline** (`specification/pipeline.md`): Calls the read interface and uses in-memory structures loaded at startup.
- **MCP server** (`specification/mcp-server.md`): Calls index lifecycle validation at startup.

---

## 3. Module Structure

```
src/coq_search/
    __init__.py
    storage/
        __init__.py          # Re-exports public API
        schema.py            # Schema DDL, version constants, table creation
        writer.py            # IndexWriter class (write path)
        reader.py            # IndexReader class (read path)
        serialization.py     # ExprTree pickle serialization/deserialization
        errors.py            # Storage-specific error types
```

---

## 4. Implementation Steps

### Step 1: Define Error Types (`src/coq_search/storage/errors.py`)

Define storage-specific exceptions that map to the error specification in storage.md Section 7.

```python
class StorageError(Exception):
    """Base class for storage errors."""
    pass

class IndexMissingError(StorageError):
    """Database file does not exist."""
    pass

class IndexVersionMismatchError(StorageError):
    """Schema version or library version does not match."""
    def __init__(self, key: str, expected: str, actual: str):
        ...

class IndexCorruptError(StorageError):
    """Database fails integrity check."""
    pass

class FtsParseError(StorageError):
    """FTS5 query syntax error."""
    def __init__(self, query: str, detail: str):
        ...
```

### Step 2: Define Schema Constants and DDL (`src/coq_search/storage/schema.py`)

This module owns all SQL DDL and the current schema version constant.

```python
SCHEMA_VERSION = 1

# Table creation order matters for foreign keys
_CREATE_DECLARATIONS = """
CREATE TABLE declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    module TEXT NOT NULL,
    kind TEXT NOT NULL,
    statement TEXT NOT NULL,
    type_expr TEXT,
    constr_tree BLOB,
    node_count INTEGER,
    symbol_set TEXT
)
"""

_CREATE_DECLARATIONS_IDX_MODULE = """
CREATE INDEX idx_declarations_module ON declarations(module)
"""

_CREATE_DECLARATIONS_IDX_KIND = """
CREATE INDEX idx_declarations_kind ON declarations(kind)
"""

_CREATE_DEPENDENCIES = """
CREATE TABLE dependencies (
    src INTEGER NOT NULL REFERENCES declarations(id),
    dst INTEGER NOT NULL REFERENCES declarations(id),
    relation TEXT NOT NULL,
    PRIMARY KEY (src, dst, relation)
)
"""

_CREATE_DEPENDENCIES_IDX_DST = """
CREATE INDEX idx_dependencies_dst ON dependencies(dst)
"""

_CREATE_WL_VECTORS = """
CREATE TABLE wl_vectors (
    decl_id INTEGER NOT NULL REFERENCES declarations(id),
    h INTEGER NOT NULL,
    histogram TEXT NOT NULL,
    PRIMARY KEY (decl_id, h)
)
"""

_CREATE_SYMBOL_FREQ = """
CREATE TABLE symbol_freq (
    symbol TEXT PRIMARY KEY,
    freq INTEGER NOT NULL
)
"""

_CREATE_INDEX_META = """
CREATE TABLE index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE declarations_fts USING fts5(
    name,
    statement,
    module,
    content=declarations,
    content_rowid=id,
    tokenize='porter unicode61 remove_diacritics 2'
)
"""

_ALL_DDL = [
    _CREATE_DECLARATIONS,
    _CREATE_DECLARATIONS_IDX_MODULE,
    _CREATE_DECLARATIONS_IDX_KIND,
    _CREATE_DEPENDENCIES,
    _CREATE_DEPENDENCIES_IDX_DST,
    _CREATE_WL_VECTORS,
    _CREATE_SYMBOL_FREQ,
    _CREATE_INDEX_META,
    _CREATE_FTS,
]

REQUIRED_META_KEYS = frozenset({
    "schema_version",
    "coq_version",
    "mathcomp_version",
    "created_at",
})


def create_all_tables(conn: sqlite3.Connection) -> None:
    """Execute all DDL statements in a single transaction.

    REQUIRES: conn is a writable connection to an empty database.
    ENSURES: All tables, indexes, and the FTS5 virtual table exist.
    """
    ...
```

**Implementation notes**:
- Execute all DDL within a single transaction via `conn.execute()` calls inside a `with conn:` block.
- The FTS5 virtual table must be created after `declarations` since it references it via `content=declarations`.
- Enable foreign keys: `PRAGMA foreign_keys = ON` immediately after connection.

### Step 3: Implement ExprTree Serialization (`src/coq_search/storage/serialization.py`)

```python
import pickle

def serialize_expr_tree(tree: ExprTree) -> bytes:
    """Serialize an ExprTree to bytes for storage in declarations.constr_tree.

    REQUIRES: tree is a valid ExprTree with all invariants satisfied.
    ENSURES: Output bytes, when deserialized, produce an identical tree.
    """
    return pickle.dumps(tree, protocol=5)

def deserialize_expr_tree(data: bytes) -> ExprTree:
    """Deserialize bytes from declarations.constr_tree to an ExprTree.

    REQUIRES: data was produced by serialize_expr_tree.
    ENSURES: Returned tree has identical labels, children, depths, and node_ids.
    """
    tree = pickle.loads(data)
    # Validate type
    if not isinstance(tree, ExprTree):
        raise StorageError(f"Deserialized object is {type(tree)}, expected ExprTree")
    return tree
```

**Implementation notes**:
- Pickle protocol 5 (Python 3.8+) supports out-of-band data and is efficient for nested objects.
- The `ExprTree` and all `NodeLabel` subclasses from `data-structures.md` must be importable. This creates a dependency on the data structures module.
- Add a type check on deserialization as a safety guard against corrupt data.

### Step 4: Implement the Write Path (`src/coq_search/storage/writer.py`)

The `IndexWriter` class manages the entire write lifecycle: create database, insert data in batches, finalize.

```python
class IndexWriter:
    """Exclusive-access writer for building a fresh search index.

    Usage:
        writer = IndexWriter(db_path)
        writer.create()
        writer.insert_declarations(declarations_iter)
        writer.insert_dependencies(dependencies_iter)
        writer.insert_wl_vectors(vectors_iter)
        writer.insert_symbol_freq(freq_map)
        writer.rebuild_fts()
        writer.set_meta(coq_version=..., mathcomp_version=..., created_at=...)
        writer.finalize()
        writer.close()
    """

    BATCH_SIZE = 1000

    def __init__(self, db_path: str | Path):
        """Store the path. Do not open the database yet."""
        ...

    def create(self) -> None:
        """Create a fresh database file, replacing any existing file.

        REQUIRES: No other process has the database open.
        ENSURES: Empty database with all tables created.
        """
        ...

    def insert_declarations(
        self,
        declarations: Iterable[DeclarationRow],
    ) -> None:
        """Insert declaration rows in batches of BATCH_SIZE.

        REQUIRES: Database is open and tables exist.
        ENSURES: All valid declarations are inserted. Foreign key violations
                 are logged and skipped.

        DeclarationRow is a dataclass or NamedTuple:
            name: str
            module: str
            kind: str
            statement: str
            type_expr: str | None
            constr_tree: bytes | None  (pre-serialized)
            node_count: int | None
            symbol_set: str  (JSON array)
        """
        ...

    def insert_dependencies(
        self,
        dependencies: Iterable[DependencyRow],
    ) -> None:
        """Insert dependency edges in batches of BATCH_SIZE.

        DependencyRow:
            src_id: int
            dst_id: int
            relation: str  ("uses" | "instance_of")

        Foreign key violations are logged and skipped.
        """
        ...

    def insert_wl_vectors(
        self,
        vectors: Iterable[WlVectorRow],
    ) -> None:
        """Insert WL histogram vectors in batches of BATCH_SIZE.

        WlVectorRow:
            decl_id: int
            h: int
            histogram: str  (JSON object)
        """
        ...

    def insert_symbol_freq(
        self,
        freq: dict[str, int],
    ) -> None:
        """Insert the global symbol frequency table.

        REQUIRES: freq values are all >= 1.
        ENSURES: All symbols are present in symbol_freq table.
        """
        ...

    def rebuild_fts(self) -> None:
        """Rebuild the FTS5 index from declarations table content.

        REQUIRES: All declarations have been inserted.
        ENSURES: FTS5 index is consistent with declarations content.
        """
        ...

    def set_meta(
        self,
        coq_version: str,
        mathcomp_version: str,
        created_at: str,
    ) -> None:
        """Write all required index_meta keys.

        ENSURES: All four required keys are present in index_meta.
        """
        ...

    def finalize(self) -> None:
        """Run integrity check and verify all required meta keys.

        ENSURES: Database passes PRAGMA integrity_check.
        Raises IndexCorruptError if check fails.
        """
        ...

    def close(self) -> None:
        """Close the database connection."""
        ...
```

**Implementation details for each method**:

#### `create()`
1. If `db_path` exists, delete it (`os.remove`).
2. Open connection: `sqlite3.connect(str(db_path))`.
3. `PRAGMA foreign_keys = ON`.
4. `PRAGMA journal_mode = DELETE` (not WAL; spec Section 8 says no WAL needed).
5. Call `schema.create_all_tables(conn)`.

#### `insert_declarations()`
1. Accumulate rows into a buffer list.
2. When buffer reaches `BATCH_SIZE`, execute `INSERT INTO declarations (name, module, kind, statement, type_expr, constr_tree, node_count, symbol_set) VALUES (?, ?, ?, ?, ?, ?, ?, ?)` via `cursor.executemany()` inside `with self._conn:` (transaction).
3. Clear buffer.
4. After iteration ends, flush remaining buffer.
5. Catch `sqlite3.IntegrityError` per-batch. On failure, fall back to row-by-row insertion for that batch, logging and skipping individual failures.

#### `insert_dependencies()`
Same batching pattern. Use `INSERT OR IGNORE` to handle duplicate edges gracefully, or catch IntegrityError per-row. Log foreign key violations.

#### `insert_wl_vectors()`
Same batching pattern as declarations.

#### `insert_symbol_freq()`
Single transaction insert. The freq table is typically 5K-20K rows, so one batch is sufficient.

#### `rebuild_fts()`
Execute: `INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')`. This must happen after all declarations are inserted.

#### `set_meta()`
Insert four rows into `index_meta`:
- `("schema_version", str(SCHEMA_VERSION))`
- `("coq_version", coq_version)`
- `("mathcomp_version", mathcomp_version)`
- `("created_at", created_at)`

Use `INSERT OR REPLACE` to be idempotent.

#### `finalize()`
1. Execute `PRAGMA integrity_check`. Parse result — it returns `"ok"` on success.
2. Verify all `REQUIRED_META_KEYS` are present in `index_meta`.
3. Raise `IndexCorruptError` if integrity check fails.

### Step 5: Implement the Read Path (`src/coq_search/storage/reader.py`)

The `IndexReader` class handles startup validation, in-memory data loading, and query-time lookups.

```python
class IndexReader:
    """Read-only access to a search index for query serving.

    Usage:
        reader = IndexReader(db_path)
        reader.open()  # validates, loads in-memory structures
        results = reader.fts_search("nat add", limit=20)
        decl = reader.get_declaration(42)
        reader.close()
    """

    def __init__(self, db_path: str | Path):
        ...

    def open(self) -> None:
        """Open database read-only, validate index, load in-memory structures.

        REQUIRES: Database file exists.
        ENSURES: In-memory WL histograms, inverted symbol index, and
                 symbol_freq lookup are populated. Database is read-only.

        Raises:
            IndexMissingError: if db_path does not exist.
            IndexVersionMismatchError: if schema_version, coq_version,
                or mathcomp_version do not match expected values.
            IndexCorruptError: if required meta keys are missing.
        """
        ...

    def close(self) -> None:
        """Close the database connection and release in-memory structures."""
        ...

    # --- In-memory structures (populated by open()) ---

    @property
    def wl_histograms(self) -> dict[int, dict[str, int]]:
        """Mapping from decl_id to WL histogram at h=3.

        Loaded into memory at startup for fast WL screening.
        """
        ...

    @property
    def inverted_symbol_index(self) -> dict[str, set[int]]:
        """Mapping from symbol name to set of decl_ids containing it.

        Built at startup from declarations.symbol_set for MePo channel.
        """
        ...

    @property
    def symbol_frequencies(self) -> dict[str, int]:
        """Mapping from symbol name to global frequency count.

        Loaded at startup from symbol_freq table.
        """
        ...

    # --- Query-time methods ---

    def get_declaration(self, decl_id: int) -> DeclarationRow | None:
        """Fetch a single declaration by ID.

        Returns None if not found.
        """
        ...

    def get_declarations_by_ids(self, decl_ids: list[int]) -> list[DeclarationRow]:
        """Fetch multiple declarations by ID. Preserves input order."""
        ...

    def get_declaration_by_name(self, name: str) -> DeclarationRow | None:
        """Fetch a declaration by fully qualified name."""
        ...

    def fts_search(self, query: str, *, limit: int = 20) -> list[tuple[int, float]]:
        """Run FTS5 search, returning (decl_id, bm25_score) pairs.

        REQUIRES: query is a non-empty string.
        ENSURES: Results ordered by BM25 score (lower is better in SQLite).

        Raises FtsParseError if query has invalid FTS5 syntax.
        """
        ...

    def get_dependencies(self, decl_id: int, relation: str | None = None) -> list[tuple[int, str]]:
        """Get outgoing dependencies for a declaration.

        Returns list of (dst_id, relation) pairs.
        """
        ...

    def get_reverse_dependencies(self, decl_id: int, relation: str | None = None) -> list[tuple[int, str]]:
        """Get incoming dependencies for a declaration.

        Returns list of (src_id, relation) pairs.
        """
        ...

    def get_constr_tree(self, decl_id: int) -> ExprTree | None:
        """Fetch and deserialize the expression tree for a declaration.

        Returns None if constr_tree is NULL or declaration not found.
        """
        ...

    def list_modules(self) -> list[str]:
        """Return sorted list of distinct module names."""
        ...

    def get_declarations_by_module(self, module: str) -> list[DeclarationRow]:
        """Fetch all declarations in a module."""
        ...
```

**Implementation details**:

#### `open()` — Startup sequence

1. Check file existence. Raise `IndexMissingError` if missing.
2. Open connection with read-only URI: `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)`.
3. Load `index_meta` into a dict. Verify all `REQUIRED_META_KEYS` are present.
4. Compare `schema_version` against `SCHEMA_VERSION`. Raise `IndexVersionMismatchError` on mismatch.
5. The `coq_version` and `mathcomp_version` checks are performed by the caller (MCP server), since the storage layer does not know what versions are installed. The reader exposes the stored values via a `get_meta()` method; the MCP server compares them.
6. Load WL histograms (h=3): `SELECT decl_id, histogram FROM wl_vectors WHERE h = 3`. Parse each histogram JSON string into `dict[str, int]`. Store in `self._wl_histograms: dict[int, dict[str, int]]`.
7. Build inverted symbol index: `SELECT id, symbol_set FROM declarations WHERE symbol_set IS NOT NULL`. For each row, parse the JSON array. For each symbol, add `decl_id` to `self._inverted_index[symbol]`.
8. Load symbol frequencies: `SELECT symbol, freq FROM symbol_freq`. Store in `self._symbol_freq: dict[str, int]`.

#### `fts_search()`

```sql
SELECT rowid, bm25(declarations_fts, 10.0, 1.0, 5.0)
FROM declarations_fts
WHERE declarations_fts MATCH ?
ORDER BY bm25(declarations_fts, 10.0, 1.0, 5.0)
LIMIT ?
```

Wrap in try/except for `sqlite3.OperationalError` — FTS5 syntax errors surface as OperationalError. Convert to `FtsParseError`.

BM25 weights (10.0, 1.0, 5.0) correspond to columns (name, statement, module) as specified in the data model doc. Note: SQLite's `bm25()` returns negative values where more negative = better match.

#### `get_constr_tree()`

1. `SELECT constr_tree FROM declarations WHERE id = ?`
2. If NULL, return None.
3. Call `deserialize_expr_tree(blob)` from `serialization.py`.

### Step 6: Define Row Types (`src/coq_search/storage/__init__.py`)

Export public types and re-export the main classes.

```python
from dataclasses import dataclass
from typing import NamedTuple

@dataclass
class DeclarationRow:
    id: int
    name: str
    module: str
    kind: str
    statement: str
    type_expr: str | None
    constr_tree: bytes | None
    node_count: int | None
    symbol_set: str | None  # JSON array

class DependencyRow(NamedTuple):
    src_id: int
    dst_id: int
    relation: str

class WlVectorRow(NamedTuple):
    decl_id: int
    h: int
    histogram: str  # JSON object

# Re-exports
from .writer import IndexWriter
from .reader import IndexReader
from .errors import (
    StorageError,
    IndexMissingError,
    IndexVersionMismatchError,
    IndexCorruptError,
    FtsParseError,
)
```

### Step 7: Package Init (`src/coq_search/__init__.py`)

Minimal init file.

```python
"""Coq/Rocq semantic search system."""
```

---

## 5. Testing Plan

All tests go in `test/storage/`. Use `pytest` as the test runner. Tests use in-memory SQLite (`:memory:`) where possible, and `tmp_path` fixtures for file-based tests.

### 5.1 Schema Tests (`test/storage/test_schema.py`)

| Test Case | Description |
|-----------|-------------|
| `test_create_all_tables` | Call `create_all_tables` on an empty database. Verify all 6 tables exist via `sqlite_master`. |
| `test_create_tables_idempotent_on_fresh_db` | Verify `create_all_tables` succeeds on a fresh connection (not that it is idempotent — it should fail on an existing schema). |
| `test_fts5_available` | Verify FTS5 is compiled into the SQLite build. If not, the test should skip with a clear message. |
| `test_foreign_keys_enabled` | After schema creation, insert a dependency referencing a nonexistent declaration. Verify it raises IntegrityError when foreign_keys is ON. |
| `test_declarations_name_uniqueness` | Insert two declarations with the same name. Verify IntegrityError. |
| `test_declarations_required_columns` | Insert a declaration with NULL name, module, kind, or statement. Verify IntegrityError for each. |
| `test_wl_vectors_composite_key` | Insert two WL vectors with same (decl_id, h). Verify IntegrityError. |
| `test_index_meta_key_uniqueness` | Insert two meta rows with the same key. Verify the second overwrites (when using INSERT OR REPLACE). |

### 5.2 Writer Tests (`test/storage/test_writer.py`)

| Test Case | Description |
|-----------|-------------|
| `test_create_fresh_database` | Create a writer, call `create()`, verify file exists and schema is present. |
| `test_create_replaces_existing` | Create a database, insert data, then create again. Verify old data is gone. |
| `test_insert_declarations_single` | Insert one declaration. Verify it is retrievable. |
| `test_insert_declarations_batch` | Insert 2,500 declarations (exceeding BATCH_SIZE). Verify all are present. |
| `test_insert_declarations_duplicate_name` | Insert two declarations with duplicate names. Verify one is skipped and logged. |
| `test_insert_dependencies` | Insert declarations, then dependencies. Verify edges are stored. |
| `test_insert_dependencies_fk_violation` | Insert a dependency referencing a nonexistent declaration. Verify it is skipped and logged. |
| `test_insert_wl_vectors` | Insert WL vectors for multiple declarations at multiple h values. Verify retrieval. |
| `test_insert_symbol_freq` | Insert symbol frequencies. Verify all are stored correctly. |
| `test_rebuild_fts` | Insert declarations, rebuild FTS. Run a MATCH query. Verify results. |
| `test_set_meta` | Set all meta keys. Verify all four required keys are present. |
| `test_finalize_passes` | Write a complete database, call finalize. Verify no errors. |
| `test_finalize_detects_missing_meta` | Write data but skip `set_meta`. Call finalize. Verify error. |
| `test_full_write_lifecycle` | End-to-end: create, insert all data types, rebuild FTS, set meta, finalize, close. Open with reader and verify. |

### 5.3 Reader Tests (`test/storage/test_reader.py`)

| Test Case | Description |
|-----------|-------------|
| `test_open_missing_file` | Open a nonexistent path. Verify `IndexMissingError`. |
| `test_open_version_mismatch` | Create a database with `schema_version = "999"`. Verify `IndexVersionMismatchError`. |
| `test_open_missing_meta_keys` | Create a database without all required meta keys. Verify appropriate error. |
| `test_open_loads_wl_histograms` | Create database with WL vectors (h=3). Open reader. Verify `wl_histograms` is populated with correct data. |
| `test_open_loads_inverted_index` | Create database with declarations and symbol sets. Open reader. Verify `inverted_symbol_index` maps symbols to correct decl_ids. |
| `test_open_loads_symbol_freq` | Create database with symbol_freq data. Open reader. Verify `symbol_frequencies` dict. |
| `test_get_declaration` | Fetch an existing declaration by ID. Verify all fields. |
| `test_get_declaration_missing` | Fetch a nonexistent ID. Verify returns None. |
| `test_get_declarations_by_ids` | Fetch multiple IDs. Verify order preservation and completeness. |
| `test_get_declaration_by_name` | Fetch by fully qualified name. Verify correct row returned. |
| `test_fts_search_basic` | Search for "nat add". Verify results include relevant declarations. |
| `test_fts_search_empty_results` | Search for a term not present. Verify empty list. |
| `test_fts_search_syntax_error` | Search with invalid FTS5 syntax (unbalanced quotes). Verify `FtsParseError`. |
| `test_fts_search_limit` | Insert many declarations. Search with limit=5. Verify at most 5 results. |
| `test_get_dependencies` | Fetch outgoing dependencies. Verify correct edges and relations. |
| `test_get_reverse_dependencies` | Fetch incoming dependencies. Verify correct edges. |
| `test_get_constr_tree` | Insert a declaration with a serialized ExprTree. Fetch and deserialize. Verify tree structure is preserved. |
| `test_get_constr_tree_null` | Fetch a declaration with NULL constr_tree. Verify returns None. |
| `test_list_modules` | Insert declarations in multiple modules. Verify distinct sorted module list. |
| `test_read_only_enforcement` | Open reader. Attempt an INSERT. Verify it fails. |
| `test_startup_latency` | Insert 50K WL histogram rows. Measure time to `open()`. Assert < 2 seconds. |

### 5.4 Serialization Tests (`test/storage/test_serialization.py`)

| Test Case | Description |
|-----------|-------------|
| `test_roundtrip_simple_tree` | Serialize and deserialize a simple ExprTree (LProd with two LInd children). Verify equality. |
| `test_roundtrip_complex_tree` | Serialize a tree with all 16 NodeLabel types. Verify all labels, children, depths, node_ids survive. |
| `test_roundtrip_cse_var` | Serialize a tree containing LCseVar nodes. Verify var_ids are preserved. |
| `test_deserialize_invalid_data` | Pass garbage bytes to deserialize. Verify StorageError or appropriate exception. |
| `test_deserialize_wrong_type` | Pickle a non-ExprTree object. Pass to deserialize. Verify StorageError. |

### 5.5 Integration Test (`test/storage/test_integration.py`)

One end-to-end test that simulates the full lifecycle:

1. Create an IndexWriter, build a database with ~100 synthetic declarations (varied kinds, modules, symbol sets), their dependencies, WL vectors, and symbol frequencies.
2. Finalize and close the writer.
3. Open an IndexReader on the same file.
4. Verify all in-memory structures are correctly loaded.
5. Run FTS searches and verify results are consistent.
6. Fetch individual declarations and verify data integrity.
7. Fetch dependency graphs and verify edges.
8. Close the reader.

---

## 6. Acceptance Criteria

The implementation is complete when all of the following are true:

1. **Schema creation**: `IndexWriter.create()` produces a database with all 6 tables, 3 indexes, and the FTS5 virtual table matching the DDL in `specification/storage.md` Section 3.
2. **Write lifecycle**: A complete write sequence (create, insert all data types, rebuild FTS, set meta, finalize) succeeds without errors for a dataset of 1,000+ synthetic declarations.
3. **Batch commits**: Declarations are committed in batches of 1,000 rows. Inserting 5,000 declarations results in 5 batch commits (observable via transaction count or timing).
4. **FTS5 search**: After rebuild, FTS queries return relevant declarations ranked by BM25. The tokenizer uses Porter stemming (searching "adding" matches "add").
5. **Read-only enforcement**: The `IndexReader` opens the database in read-only mode. Any write attempt raises an error.
6. **In-memory loading**: `IndexReader.open()` populates `wl_histograms`, `inverted_symbol_index`, and `symbol_frequencies` from the database. These structures are used for all subsequent lookups (no additional SQL queries for WL or symbol data).
7. **Index lifecycle validation**: `IndexReader.open()` detects missing databases, schema version mismatches, and missing meta keys, raising the appropriate error type.
8. **ExprTree serialization**: Round-trip serialization preserves all node labels, children ordering, depths, and node_ids.
9. **Error handling**: Foreign key violations during insertion are logged and skipped, not fatal. FTS syntax errors are caught and wrapped in `FtsParseError`.
10. **All tests pass**: All test cases defined in the testing plan pass.

---

## 7. Risks and Mitigations

### 7.1 FTS5 Availability

**Risk**: Python's bundled SQLite may not include FTS5. This depends on the system's SQLite build flags. Most modern distributions include FTS5, but it is not guaranteed.

**Mitigation**: Add a check at import time or in `create_all_tables()` that tests FTS5 availability by executing `CREATE VIRTUAL TABLE _fts5_test USING fts5(x)` and then dropping it. If FTS5 is unavailable, raise a clear error with instructions (e.g., "Install a SQLite build with FTS5 enabled, or install the `pysqlite3` package compiled with FTS5").

### 7.2 `remove_diacritics 2` Requires SQLite 3.27.0+

**Risk**: The tokenizer option `remove_diacritics 2` was added in SQLite 3.27.0. Older SQLite builds will reject the CREATE VIRTUAL TABLE statement.

**Mitigation**: Check `sqlite3.sqlite_version_info` at startup. If below 3.27.0, fall back to `remove_diacritics 1` and log a warning.

### 7.3 Pickle Security

**Risk**: Pickle deserialization can execute arbitrary code. If a malicious actor can replace the database file, they could inject code via the `constr_tree` BLOB.

**Mitigation**: This is acceptable for the current threat model (the database is a local derived artifact written and read by the same tool). Document in code comments that the database file must be trusted. If the threat model changes, switch to a custom binary format or `msgpack` with a whitelist of allowed types.

### 7.4 Memory Usage for Large Libraries

**Risk**: Loading all WL histograms (h=3) for 50K declarations into memory. Each histogram is ~50-500 entries. At 200 entries average, this is 50K * 200 * ~100 bytes per entry = ~1 GB worst case.

**Mitigation**: The spec states <2s startup for 50K declarations, implying the data fits in memory. In practice, MD5 hex keys (32 chars) + int values at 200 entries per histogram is closer to 50K * 200 * 40 bytes = ~400 MB. Monitor actual memory usage during integration testing. If excessive, consider loading histograms lazily or using a more compact representation (e.g., integer keys instead of hex strings).

### 7.5 Concurrent Access During Development

**Risk**: During development, a reader and writer might accidentally be open simultaneously, causing database lock errors.

**Mitigation**: The writer deletes the database file before creating a new one. The reader opens in read-only mode. Document in the module docstring that these modes are mutually exclusive. The spec explicitly states no concurrent access is needed.

### 7.6 JSON Parsing Performance

**Risk**: Parsing JSON for 50K symbol_set values and 50K histogram values during startup could be slow.

**Mitigation**: Python's `json.loads` is C-accelerated in CPython and handles these sizes well. If profiling shows it is a bottleneck, consider `orjson` as a drop-in replacement. The spec's 2-second startup target is the benchmark.

### 7.7 Transaction Scope for Batch Inserts

**Risk**: If a batch of 1,000 rows fails mid-transaction (e.g., one row has a constraint violation), the entire batch is rolled back.

**Mitigation**: On batch failure, fall back to row-by-row insertion for that batch, logging and skipping individual failures. This preserves the throughput benefit of batching for the common case while handling edge cases gracefully.
