# Storage

SQLite storage layer for the Coq/Rocq search index.

**Architecture**: [storage.md](../doc/architecture/storage.md), [index-entities.md](../doc/architecture/data-models/index-entities.md)

---

## 1. Purpose

Define the read and write interfaces for the SQLite search index database, including schema creation, bulk loading during indexing, and query-time data access for the retrieval pipeline.

## 2. Scope

**In scope**: Schema DDL, `IndexWriter` (write path), `IndexReader` (read path), version validation, in-memory data loading (WL histograms, inverted index, symbol frequencies, declaration node counts), declaration and dependency queries.

**Out of scope**: Extraction logic (owned by extraction), retrieval algorithms (owned by pipeline and channels), MCP protocol handling (owned by mcp-server).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Index database | A single SQLite file containing all search index tables |
| Write path | The `IndexWriter` interface used during offline indexing to populate the database |
| Read path | The `IndexReader` interface used during online queries |
| Content-synced FTS5 | FTS5 virtual table that reads from `declarations` rather than maintaining a separate copy |

## 4. Behavioral Requirements

### 4.1 Schema

The database shall contain 7 tables as defined in the architecture:

- `declarations` — core indexing unit
- `dependencies` — directed relationship edges
- `wl_vectors` — precomputed WL histograms (JSON)
- `symbol_freq` — global symbol frequency counts
- `re_export_aliases` — re-export path → canonical FQN mapping
- `index_meta` — key-value metadata
- `declarations_fts` — FTS5 virtual table (content-synced with `declarations`)
- `embeddings` — neural premise embedding vectors (optional, populated when neural model is available)

FTS5 configuration: The stemming tokenizer shall wrap the base tokenizer (Porter around Unicode61). BM25 column weights: `name=10.0`, `statement=1.0`, `module=5.0`.

Language-specific note (SQLite FTS5): `tokenize='porter unicode61'`.

### 4.2 IndexWriter

The `IndexWriter` manages the write path during offline indexing.

#### create(path)

- REQUIRES: `path` is a writable filesystem path. No database exists at `path` (or caller accepts overwrite).
- ENSURES: A new SQLite database is created with all 6 tables. Write-path pragmas are set: `synchronous = OFF`, `journal_mode = MEMORY`. Foreign keys are enabled.

#### insert_declarations(batch)

- REQUIRES: `batch` is a list of declaration row data (up to 1000 items). Each item contains all required fields from the `declarations` entity, including `has_proof_body` (integer 0 or 1).
- ENSURES: All declarations in the batch are inserted. Corresponding `declarations_fts` entries are synced. Returns the mapping of declaration name → assigned id.

#### insert_wl_vectors(batch)

- REQUIRES: `batch` is a list of WL vector row data. Each item references a valid `decl_id`.
- ENSURES: All vectors are inserted.

Declarations and their WL vectors shall be co-inserted in the same batch transaction.

#### insert_dependencies(batch)

- REQUIRES: `batch` is a list of dependency edge row data. Both `src` and `dst` reference existing declarations.
- ENSURES: All edges are inserted. Self-loops (`src == dst`) are rejected.

#### insert_embeddings(batch)

- REQUIRES: `batch` is a list of `(decl_id, vector_blob)` pairs. Each `decl_id` references an existing declaration. Each `vector_blob` is exactly 3,072 bytes (768 × float32).
- ENSURES: All embeddings are inserted into the `embeddings` table.

#### insert_re_export_aliases(aliases)

- REQUIRES: `aliases` is a map of `alias_fqn → canonical_fqn`. Each `alias_fqn` is a fully qualified re-export path. Each `canonical_fqn` is a canonical definition FQN present in the inverted index.
- ENSURES: All entries are inserted into `re_export_aliases`. Duplicate `alias_fqn` keys are silently ignored (first write wins, matching deduplication order).

#### insert_symbol_freq(entries)

- REQUIRES: `entries` is a map of symbol → frequency.
- ENSURES: All entries are inserted into `symbol_freq`.

#### write_meta(key, value)

- REQUIRES: `key` is a recognized metadata key (see [index-entities.md](../doc/architecture/data-models/index-entities.md) § index_meta for per-library and merged key sets).
- ENSURES: The key-value pair is written to `index_meta`.

#### finalize()

- REQUIRES: All data has been inserted.
- ENSURES: FTS5 `rebuild` command is executed. `PRAGMA integrity_check` passes. Connection is closed.
- On integrity check failure: close connection, delete database file, raise `StorageError`.

#### Batch transaction protocol

Pass 1 co-inserts declarations and WL vectors in batches of 1000 declarations + their WL vectors. Pass 2 inserts dependency edges in separate batches. This ordering guarantees all foreign key targets exist before dependency edges reference them.

### 4.3 IndexReader

The `IndexReader` manages the read path during online queries.

#### open(path)

- REQUIRES: `path` points to an existing SQLite database.
- ENSURES: Connection is opened in read-only mode. `schema_version` from `index_meta` is validated against the expected version. On mismatch: raise `IndexVersionError`. Library metadata (`coq_version`, `library`, `library_version`, `mathcomp_version`) are exposed via the `get_meta(key)` method for the caller to check.

#### load_wl_histograms()

- REQUIRES: Database is open and valid.
- ENSURES: Returns all WL histograms as an in-memory map of `decl_id → {h → histogram}`. Histograms are deserialized from JSON to `dict[str, int]`.

#### load_inverted_index()

- REQUIRES: Database is open and valid.
- ENSURES: Returns an inverted index mapping `symbol → set[decl_id]`, built from `declarations.symbol_set` JSON arrays.

#### load_symbol_frequencies()

- REQUIRES: Database is open and valid.
- ENSURES: Returns a map of `symbol → freq` from the `symbol_freq` table.

#### load_declaration_node_counts()

- REQUIRES: Database is open and valid.
- ENSURES: Returns a map of `decl_id → node_count` from the `declarations` table for all declarations with a non-null `node_count`.

#### load_re_export_aliases()

- REQUIRES: Database is open and valid.
- ENSURES: Returns a map of `alias_fqn → canonical_fqn` from the `re_export_aliases` table. Returns an empty map if the table does not exist (backward compatibility with older indexes).

#### get_declaration(name)

- REQUIRES: `name` is a fully qualified declaration name.
- ENSURES: Returns the full declaration row, or `None` if not found.

#### get_declarations_by_ids(ids)

- REQUIRES: `ids` is a list of declaration IDs.
- ENSURES: Returns declaration rows for all found IDs. Missing IDs are silently omitted.

#### get_constr_trees(ids)

- REQUIRES: `ids` is a list of declaration IDs.
- ENSURES: Returns a map of `id → deserialized ExprTree` for all IDs with non-null `constr_tree`. Uses batched `SELECT ... WHERE id IN (...)`.

#### search_fts(query, limit)

- REQUIRES: `query` is a preprocessed FTS5 query string. `limit` is a positive integer.
- ENSURES: Returns up to `limit` declaration rows ranked by BM25, with scores normalized to [0, 1].

#### get_dependencies(decl_id, direction, relation)

- REQUIRES: `decl_id` is a valid declaration ID. `direction` is `"outgoing"` or `"incoming"`. `relation` is a valid relation type or `None` (all relations).
- ENSURES: Returns matching dependency edges with resolved declaration names.

#### get_declarations_by_module(module, exclude_id)

- REQUIRES: `module` is a module path. `exclude_id` is an optional declaration ID to exclude.
- ENSURES: Returns all declarations in the module, optionally excluding one.

#### get_provable_declarations(module_prefix, has_proof_body)

- REQUIRES: Database is open and valid. `module_prefix` is an optional string filter. `has_proof_body` is an optional boolean filter.
- ENSURES: Returns declarations with `kind IN ('lemma', 'theorem', 'instance', 'definition')`, ordered by `(module, name)`. When `module_prefix` is provided, only declarations whose `module` starts with that prefix are returned. When `has_proof_body` is `true`, only declarations with `has_proof_body = 1` are returned. When `has_proof_body` is `false` or omitted, all matching declarations are returned (backward compatible). Each returned row includes the `has_proof_body` field.

> **Given** an index with 3 declarations: lemma A (has_proof_body=1), definition B (has_proof_body=0), theorem C (has_proof_body=1)
> **When** `get_provable_declarations(has_proof_body=true)` is called
> **Then** returns [A, C] ordered by (module, name)

> **Given** an index built without has_proof_body annotations (all values are 0)
> **When** `get_provable_declarations(has_proof_body=true)` is called
> **Then** returns an empty list (caller should retry without the filter for backward compatibility)

#### list_modules(prefix)

- REQUIRES: `prefix` is a string (may be empty).
- ENSURES: Returns `Module` entries for all modules whose name starts with `prefix`, with declaration counts.

#### load_embeddings()

- REQUIRES: Database is open and valid.
- ENSURES: If the `embeddings` table exists and contains rows, returns a tuple `(embedding_matrix, decl_id_map)` where `embedding_matrix` is a contiguous float32 array of shape `[N, 768]` and `decl_id_map` is an integer array of length N mapping row indices to declaration IDs. If the table does not exist or is empty, returns `(None, None)`.

#### get_meta(key)

- REQUIRES: Database is open. `key` is a string.
- ENSURES: Returns the value for the given key from `index_meta`, or `None` if the key does not exist.

#### close()

- REQUIRES: Database is open.
- ENSURES: Connection is closed. Subsequent query calls raise `StorageError`.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Database file not found (read path) | `IndexNotFoundError` | Caller translates to `INDEX_MISSING` |
| Schema version mismatch | `IndexVersionError` | Caller translates to `INDEX_VERSION_MISMATCH` |
| `PRAGMA integrity_check` fails | `StorageError` | Connection closed, database file deleted, error propagated |
| SQLite operational error | `StorageError` | Propagated with context |
| FTS5 or SQLite version too old | `StorageError` | Checked at `create()` time; requires FTS5 support |
| Self-loop in dependency edge | `ValueError` | Edge rejected |

Error hierarchy:
- `StorageError` — base class for all storage errors
  - `IndexNotFoundError` — database file missing
  - `IndexVersionError` — schema version mismatch (carries `found` and `expected` versions)

## 6. Non-Functional Requirements

- Write-path pragmas (`synchronous = OFF`, `journal_mode = MEMORY`) for bulk loading throughput. The database is disposable until `finalize()` succeeds.
- Read-path connections use default SQLite pragmas (no reduced durability).
- WL histogram loading: ~100MB for 100K declarations. Loaded once at startup.
- FTS5 queries: < 10ms typical.

## 7. Examples

### Write path sequence

```
writer = IndexWriter.create("/path/to/index.db")
for batch in declaration_batches:
    ids = writer.insert_declarations(batch.declarations)
    writer.insert_wl_vectors(batch.wl_vectors)
writer.insert_dependencies(all_dependency_edges)
writer.insert_symbol_freq(symbol_frequencies)
writer.write_meta("schema_version", "1")
writer.write_meta("coq_version", "9.1.1")
writer.write_meta("library", "stdlib")
writer.write_meta("library_version", "9.1.1")
writer.write_meta("declarations", "31035")
writer.write_meta("created_at", "2026-03-16T12:00:00Z")
writer.finalize()
```

### Read path startup

```
reader = IndexReader.open("/path/to/index.db")  # validates schema_version
histograms = reader.load_wl_histograms()         # into memory
inv_index = reader.load_inverted_index()          # into memory
sym_freq = reader.load_symbol_frequencies()       # into memory
node_counts = reader.load_declaration_node_counts()  # into memory
```

## 8. Language-Specific Notes (Python)

- Use `sqlite3` from the standard library.
- Use context managers for connection lifecycle.
- Use `executemany` for batch inserts.
- JSON serialization/deserialization for `symbol_set`, `histogram` fields via `json.dumps`/`json.loads`.
- Tree serialization format for `constr_tree` BLOB: use `pickle` or `msgpack` — must round-trip without data loss.
- Package location: `src/poule/storage/`.
