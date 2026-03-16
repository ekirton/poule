# Storage Schema

SQLite database serving as the sole persistence layer. Holds all indexed declarations, precomputed retrieval vectors, and index lifecycle metadata.

Parent architecture: [doc/architecture/storage.md](../doc/architecture/storage.md)
Data models: [doc/architecture/data-models/index-entities.md](../doc/architecture/data-models/index-entities.md)
Data structures: [data-structures.md](data-structures.md)

---

## 1. Purpose

Provide a single-file, zero-dependency store for all indexed Coq declarations and their retrieval artifacts. The database is written once during extraction and read during query serving. No external database server is required.

---

## 2. Scope

Covers the SQLite schema definition, table relationships, FTS5 configuration, index metadata lifecycle, and read/write contracts. Does not cover the extraction pipeline that populates the database (see [extraction.md](extraction.md)) or the retrieval logic that queries it (see [pipeline.md](pipeline.md)).

---

## 3. Schema Definition

### 3.1 `declarations`

The core table. One row per extracted Coq declaration.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Internal identifier |
| `name` | TEXT | NOT NULL, UNIQUE | Fully qualified name (e.g., `Coq.Init.Nat.add`) |
| `module` | TEXT | NOT NULL | Module path (e.g., `Coq.Init.Nat`) |
| `kind` | TEXT | NOT NULL | Declaration kind: `Lemma`, `Theorem`, `Definition`, `Inductive`, `Constructor`, `Instance`, `Axiom` |
| `statement` | TEXT | NOT NULL | Pretty-printed statement for display and FTS |
| `type_expr` | TEXT | | Pretty-printed type expression |
| `constr_tree` | BLOB | | Serialized `ExprTree` (post-normalization, post-CSE) |
| `node_count` | INTEGER | | Number of nodes in the normalized tree |
| `symbol_set` | TEXT | | JSON array of fully qualified symbol names |

```sql
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
);

CREATE INDEX idx_declarations_module ON declarations(module);
CREATE INDEX idx_declarations_kind ON declarations(kind);
```

### 3.2 `dependencies`

Directed edges between declarations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `src` | INTEGER | NOT NULL, FK → declarations.id | Source declaration |
| `dst` | INTEGER | NOT NULL, FK → declarations.id | Target declaration |
| `relation` | TEXT | NOT NULL | Edge type: `uses`, `instance_of` |

```sql
CREATE TABLE dependencies (
    src INTEGER NOT NULL REFERENCES declarations(id),
    dst INTEGER NOT NULL REFERENCES declarations(id),
    relation TEXT NOT NULL,
    PRIMARY KEY (src, dst, relation)
);

CREATE INDEX idx_dependencies_dst ON dependencies(dst);
```

### 3.3 `wl_vectors`

Precomputed Weisfeiler-Lehman histograms for each declaration.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `decl_id` | INTEGER | NOT NULL, FK → declarations.id | Owner declaration |
| `h` | INTEGER | NOT NULL | WL iteration depth (1, 3, or 5) |
| `histogram` | TEXT | NOT NULL | JSON object `{"<md5_label>": count, ...}` |

```sql
CREATE TABLE wl_vectors (
    decl_id INTEGER NOT NULL REFERENCES declarations(id),
    h INTEGER NOT NULL,
    histogram TEXT NOT NULL,
    PRIMARY KEY (decl_id, h)
);
```

### 3.4 `symbol_freq`

Global symbol frequency table for MePo weighting.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `symbol` | TEXT | PRIMARY KEY | Fully qualified symbol name |
| `freq` | INTEGER | NOT NULL | Number of declarations containing this symbol |

```sql
CREATE TABLE symbol_freq (
    symbol TEXT PRIMARY KEY,
    freq INTEGER NOT NULL
);
```

### 3.5 `index_meta`

Lifecycle metadata for version management and staleness detection.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `key` | TEXT | PRIMARY KEY | Metadata key |
| `value` | TEXT | NOT NULL | Metadata value |

```sql
CREATE TABLE index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

**Required keys** (must be present after indexing):

| Key | Value | Purpose |
|-----|-------|---------|
| `schema_version` | Integer as string (e.g., `"1"`) | Detect tool upgrades requiring re-index |
| `coq_version` | Version string (e.g., `"8.19.0"`) | Detect library version changes |
| `mathcomp_version` | Version string or `"none"` | Detect MathComp version changes |
| `created_at` | ISO 8601 timestamp | Informational |

### 3.6 `declarations_fts`

FTS5 virtual table for full-text search. Content-synced from `declarations` — it reads data from the `declarations` table rather than maintaining its own copy.

```sql
CREATE VIRTUAL TABLE declarations_fts USING fts5(
    name,
    statement,
    module,
    content=declarations,
    content_rowid=id,
    tokenize='porter unicode61 remove_diacritics 2'
);
```

After all declarations are inserted, rebuild the FTS index:

```sql
INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild');
```

---

## 4. Cross-Table Relationships

```
declarations 1──* dependencies (as src)
declarations 1──* dependencies (as dst)
declarations 1──3 wl_vectors (h ∈ {1, 3, 5})
declarations *──* symbol_freq (via symbol_set JSON contents)
declarations 1──1 declarations_fts (via content sync)
index_meta         (standalone, no FK relationships)
```

---

## 5. Read/Write Contracts

### 5.1 Write Path (Extraction)

**REQUIRES**: Exclusive access to the database file. No concurrent readers during indexing.

**Procedure**:
1. Create or replace the database file
2. Create all tables in a single transaction
3. Insert declarations, dependencies, wl_vectors, symbol_freq within transactions (batch commits every 1,000 rows for throughput)
4. Rebuild the FTS index after all declarations are inserted
5. Insert all `index_meta` required keys
6. Run `PRAGMA integrity_check` before closing

**ENSURES**: All required `index_meta` keys are present. All foreign key references are valid. FTS index is consistent with `declarations` content.

### 5.2 Read Path (Query Serving)

**REQUIRES**: Database file exists and passes version checks (see Section 6).

**Procedure**:
- Open database in read-only mode (`?mode=ro` URI or `PRAGMA query_only = ON`)
- Load all `wl_vectors` (h=3) into memory at startup as `dict[int, WlHistogram]`
- Build in-memory inverted index `symbol → set[decl_id]` from `declarations.symbol_set`
- Build in-memory `symbol_freq` lookup from `symbol_freq` table
- All subsequent queries use in-memory structures plus SQLite for FTS and declaration lookups

**ENSURES**: Database is never modified during query serving.

---

## 6. Index Lifecycle

### 6.1 Startup Validation

When the server starts, it checks the index before serving queries:

| Check | Condition | Action |
|-------|-----------|--------|
| Database exists | File not found | Return `INDEX_MISSING` error |
| Schema version | `index_meta.schema_version` ≠ current tool version | Trigger full re-index |
| Coq version | `index_meta.coq_version` ≠ installed Coq version | Trigger full rebuild |
| MathComp version | `index_meta.mathcomp_version` ≠ installed MathComp version | Trigger full rebuild |

### 6.2 Re-index Strategy

Always full rebuild — never incremental patching of the index. The database is a derived artifact. Drop and recreate the file.

---

## 7. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Database file missing | State error | `INDEX_MISSING`: server cannot start serving queries |
| Schema version mismatch | State error | `INDEX_VERSION_MISMATCH`: re-index required |
| Corrupt database (integrity_check fails) | Invariant violation | Delete and re-index |
| FTS query syntax error | Input error | Return `PARSE_ERROR` with explanation |
| Foreign key violation during write | Invariant violation | Abort transaction, log, continue with remaining declarations |

---

## 8. Non-Functional Requirements

- **Portability**: Single `.db` file, no external services. Python's `sqlite3` module (stdlib) is sufficient.
- **Startup latency**: Loading WL histograms for 50K declarations into memory takes <2s.
- **Database size**: Estimated 50–200 MB for stdlib + MathComp (~50K declarations).
- **Concurrency**: Single writer during extraction, single reader during serving. No WAL mode needed.

---

## 9. Serialization

### 9.1 ExprTree Serialization

The `constr_tree` BLOB stores a serialized `ExprTree`. Use Python's `pickle` protocol (version 5) or a custom binary format. The format is internal — it is written during extraction and read during query serving by the same codebase.

**MAINTAINS**: Deserialized tree is identical to the tree that was serialized (same labels, children, depths, node_ids).

### 9.2 JSON Fields

`symbol_set` is a JSON array of strings: `["Coq.Init.Nat.add", "Coq.Init.Nat.S"]`.

`histogram` in `wl_vectors` is a JSON object: `{"a3f2...": 4, "b7c1...": 2}`.

Use Python's `json` module for serialization. No custom encoders needed.
