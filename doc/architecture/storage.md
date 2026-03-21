# Storage

SQLite database schema for the search index. Single file, no external services.

**Feature**: [Library Indexing](../features/library-indexing.md)

---

## Schema

```sql
-- Core declarations
CREATE TABLE declarations (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,          -- fully qualified
  module TEXT NOT NULL,
  kind TEXT NOT NULL,                 -- lemma, theorem, definition, ...
  statement TEXT NOT NULL,            -- pretty-printed
  type_expr TEXT,                     -- pretty-printed type (nullable)
  constr_tree BLOB,                   -- serialized CSE-normalized tree
  node_count INTEGER NOT NULL,
  symbol_set TEXT NOT NULL            -- JSON array of symbol names
);

-- Dependency edges
CREATE TABLE dependencies (
  src INTEGER REFERENCES declarations(id) ON DELETE CASCADE,
  dst INTEGER REFERENCES declarations(id) ON DELETE CASCADE,
  relation TEXT NOT NULL,             -- uses, instance_of, ...
  PRIMARY KEY (src, dst, relation)
);

-- Precomputed WL vectors (sparse histograms as JSON)
CREATE TABLE wl_vectors (
  decl_id INTEGER REFERENCES declarations(id) ON DELETE CASCADE,
  h INTEGER NOT NULL,                 -- WL iteration count
  histogram TEXT NOT NULL,            -- JSON {label: count}
  PRIMARY KEY (decl_id, h)
);

-- Symbol frequency table
CREATE TABLE symbol_freq (
  symbol TEXT PRIMARY KEY,
  freq INTEGER NOT NULL
);

-- Index metadata (schema version, library versions)
CREATE TABLE index_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- Required keys:
--   'schema_version'  → tool's index schema version (e.g., '1')
--   'coq_version'     → Coq/Rocq version used during indexing
--   'libraries' → JSON array of indexed library identifiers (e.g., '["stdlib", "mathcomp"]')
--   'library_versions' → JSON object mapping library identifier to version string (e.g., '{"stdlib": "8.19.2", "mathcomp": "2.2.0"}')
--   'created_at'      → ISO 8601 timestamp of index creation
-- Optional keys (Neural Premise Selection):
--   'neural_model_hash' → SHA-256 hash of the model checkpoint used to compute embeddings

-- Neural premise embeddings (added by Neural Premise Selection)
CREATE TABLE embeddings (
  decl_id INTEGER PRIMARY KEY REFERENCES declarations(id) ON DELETE CASCADE,
  vector BLOB NOT NULL              -- 768 × 4 bytes = 3,072 bytes, raw float32
);

-- Full-text search
CREATE VIRTUAL TABLE declarations_fts USING fts5(
  name, statement, module,
  content=declarations, content_rowid=id
);
```

## Design Decisions

**Single database file**: The entire index — declarations, dependencies, WL vectors, symbol frequencies, and FTS5 index — lives in one SQLite file. This makes the index portable (copy one file) and eliminates external service dependencies.

**JSON for sparse data**: WL histograms and symbol sets are stored as JSON text. This keeps the schema simple and avoids a separate table per histogram entry. At query time, histograms are loaded into memory as hash maps.

**Content-synced FTS5**: The `content=declarations` parameter makes FTS5 a content-synced index — it reads from the declarations table rather than storing a copy. The `content_rowid=id` maps FTS5 rowids to declaration IDs.

**WL vectors at multiple h values**: The schema supports histograms at h=1, 3, 5 to allow experimentation with different WL iteration depths without re-extracting. Phase 1 computes h=3 only; h∈{1, 5} are reserved for future use.

**Index metadata table**: The `index_meta` table stores key-value pairs for the index schema version and the versions of indexed libraries. On server startup, the schema version is compared against the tool's expected version; a mismatch returns an error directing the user to re-index. Library versions are compared against the currently installed versions; a mismatch likewise returns an error. This table is the mechanism behind the index versioning behavior described in [library-indexing.md](../features/library-indexing.md).

**Phase 1 kind values**: The `kind` column covers Phase 1 declaration kinds only (`lemma`, `theorem`, `definition`, `instance`, `inductive`, `constructor`, `axiom`). This set will expand in Phase 2 when additional Coq declaration forms (e.g., `record`, `class`) are supported.

**Embeddings table**: The `embeddings` table stores dense vector embeddings for neural premise retrieval. Each embedding is a 768-dimensional float32 vector stored as a raw BLOB (3,072 bytes per row). The table is populated during an optional embedding pass after standard indexing, only when a neural model checkpoint is available. When no model is available, the table is empty or absent — the retrieval pipeline treats this as "neural channel unavailable." The `neural_model_hash` key in `index_meta` tracks which model produced the embeddings; a mismatch between the current model and the stored hash invalidates the embeddings. See [neural-retrieval.md](neural-retrieval.md) for the embedding computation pipeline.

**Content-synced FTS5 constraints**: With `content=declarations`, the FTS5 index reads from the declarations table and does not independently track deletions or updates. The index is consistent only after the explicit `rebuild` command. Since the database is always built from scratch (no incremental updates), this is not a problem. Any future update/delete path would require manual trigger management for FTS5 consistency.

## Write Path

The database is built from scratch during each indexing run. There is no incremental update path.

**Batch commits**: Pass 1 co-inserts declarations and their corresponding WL vectors in the same batch transaction (batches of 1,000 declarations + their WL vectors). This ensures no orphaned WL vectors exist after any commit. Pass 2 inserts dependency edges in separate batches. Foreign keys remain valid because all declarations are inserted in pass 1 before any dependency edges reference them in pass 2.

**Integrity check**: After all writes are complete, run `PRAGMA integrity_check`. If the check fails: close the connection first, then delete the database file, then propagate the error to the caller. This ordering ensures the file is actually removed on all platforms.

**Write-path pragmas**: The database is disposable until finalize succeeds, so write-path connections should use `PRAGMA synchronous = OFF` and `PRAGMA journal_mode = MEMORY` for bulk loading throughput. Read-path connections do not use these pragmas.

## Read Path

**Version check responsibility**: The storage module (`IndexReader`) validates `schema_version` against the tool's expected version and exposes the stored `coq_version` and `library_versions` values. The caller (MCP server or extraction CLI) is responsible for comparing library versions against the currently installed versions. This keeps version detection logic outside the storage module's scope.
