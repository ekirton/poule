# Index Entities

Canonical definitions for all persistent entities in the SQLite search index. These entities are written by Coq Library Extraction, stored by the Storage component, read by the Retrieval Pipeline, and checked by the MCP Server on startup.

**Architecture docs**: [storage.md](../storage.md), [coq-extraction.md](../coq-extraction.md), [retrieval-pipeline.md](../retrieval-pipeline.md)

---

## declarations

The core indexing unit representing one Coq/Rocq declaration extracted from a compiled library.

| Field | Type | Constraints |
|-------|------|-------------|
| `id` | identifier | Primary key; auto-assigned |
| `name` | qualified name | Unique; required; must be fully qualified canonical form |
| `module` | qualified name | Required; must be a valid module path (e.g., `Coq.Arith.PeanoNat`) |
| `kind` | enumeration | Required; one of: `lemma`, `theorem`, `definition`, `instance`, `inductive`, `constructor`, `axiom` |
| `statement` | text | Required; pretty-printed for display and full-text search |
| `type_expr` | text | Optional; pretty-printed type signature; null when type extraction is unsupported for this kind |
| `constr_tree` | serialized tree | Optional; CSE-normalized expression tree (see [expression-tree.md](expression-tree.md)); null when extraction is unsupported for this kind |
| `node_count` | positive integer | Required; must be > 0; determines which ranking metrics apply (TED threshold at 50) |
| `symbol_set` | list of qualified names | Required; JSON-encoded; each entry must be a fully qualified constant, inductive, or constructor name |

### Relationships

- **Owns** many `dependencies` as source (1:*). Deleting a declaration cascades to its dependency edges.
- **Owns** many `dependencies` as destination (1:*). Deleting a declaration cascades to referencing edges.
- **Owns** many `wl_vectors`, one per h value (1:3). Deleting a declaration cascades to its vectors.
- **Referenced by** `declarations_fts` via content sync (1:1).
- **References** `symbol_freq` via `symbol_set` entries (many-to-many, implicit through JSON array).

---

## dependencies

A directed edge capturing a structural relationship between two declarations.

| Field | Type | Constraints |
|-------|------|-------------|
| `src` | reference to declaration | Required; must reference an existing declaration |
| `dst` | reference to declaration | Required; must reference an existing declaration; must differ from `src` (no self-loops) |
| `relation` | enumeration | Required; one of: `uses` (src directly references dst), `instance_of` (src is a typeclass instance of dst) |

**Composite key**: (`src`, `dst`, `relation`). Multiple relation types may exist between the same pair.

### Relationships

- **Belongs to** one declaration as source (*:1, owned by `declarations`).
- **References** one declaration as destination (*:1).

---

## wl_vectors

A precomputed Weisfeiler-Lehman histogram vector for one declaration at one iteration depth, used for structural screening.

| Field | Type | Constraints |
|-------|------|-------------|
| `decl_id` | reference to declaration | Required; must reference an existing declaration |
| `h` | bounded integer | Required; must be one of {1, 3, 5}; h=3 is the only depth computed in Phase 1; h∈{1, 5} are reserved for future experimentation |
| `histogram` | map of label to count | Required; JSON-encoded; all values must be non-negative integers; sparse (only labels with count > 0) |

**Composite key**: (`decl_id`, `h`). One vector per declaration per h value.

### Relationships

- **Belongs to** one declaration (*:1, owned by `declarations`; three vectors per declaration at h=1, 3, 5).

---

## symbol_freq

A global frequency entry recording how many declarations contain a given symbol, used for inverse-frequency weighting in symbol-based retrieval.

| Field | Type | Constraints |
|-------|------|-------------|
| `symbol` | qualified name | Primary key; must be a fully qualified constant, inductive, or constructor name; must appear in at least one declaration's `symbol_set` |
| `freq` | positive integer | Required; must be > 0; count of declarations containing this symbol |

### Relationships

- **Referenced by** `declarations` via `symbol_set` entries (many-to-many, implicit).

---

## index_meta

A key-value metadata entry managing index lifecycle and version compatibility.

| Field | Type | Constraints |
|-------|------|-------------|
| `key` | text | Primary key; must be one of the required keys or a recognized optional key |
| `value` | text | Required; format depends on key (see below) |

### Required keys (all indexes)

| Key | Value constraint |
|-----|-----------------|
| `schema_version` | Parseable as a positive integer; must match the tool's expected version |
| `coq_version` | Valid version string (e.g., `9.1.1`) |
| `created_at` | Valid ISO 8601 timestamp (e.g., `2026-03-21T12:00:00Z`) |

### Required keys (per-library indexes)

Per-library indexes are produced by the extraction pipeline when targeting a single library (e.g., `index-stdlib.db`).

| Key | Value constraint |
|-----|-----------------|
| `library` | A single library identifier: one of `stdlib`, `mathcomp`, `stdpp`, `flocq`, `coquelicot`, `coqinterval` |
| `library_version` | Valid version string for the library (e.g., `2.5.0`) |
| `declarations` | Parseable as a non-negative integer; count of indexed declarations |

### Required keys (merged indexes)

Merged indexes are produced by the merge pipeline from all 6 per-library indexes (see [prebuilt-distribution.md](../prebuilt-distribution.md)).

| Key | Value constraint |
|-----|-----------------|
| `libraries` | JSON array of library identifiers; each element must be one of: `stdlib`, `mathcomp`, `stdpp`, `flocq`, `coquelicot`, `coqinterval` |
| `library_versions` | JSON object mapping library identifier to valid version string; keys must match entries in `libraries` |

### Relationships

- Standalone entity; no foreign key relationships.

---

## declarations_fts

A full-text search index over declarations enabling lexical search by name, statement, and module.

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | text | Content-synced from `declarations.name` |
| `statement` | text | Content-synced from `declarations.statement` |
| `module` | text | Content-synced from `declarations.module` |

Tokenizer: Unicode with Porter stemming. BM25 column weights: name=10.0, statement=1.0, module=5.0.

### Relationships

- **Mirrors** one declaration (1:1, content-synced via `content=declarations, content_rowid=id`; not independently owned).

---

## re_export_aliases

A mapping from a Coq re-export path to the canonical definition FQN. Captured during extraction when a declaration appears in a `.vo` file whose module path differs from the declaration's own module prefix — indicating a module re-export.

| Field | Type | Constraints |
|-------|------|-------------|
| `alias_fqn` | qualified name | Primary key; the module-qualified re-export path (e.g., `Coq.Lists.List.map`) |
| `canonical_fqn` | qualified name | Required; the canonical definition FQN (e.g., `Coq.Lists.ListDef.map`); must exist as a key in the inverted index |

### Relationships

- **References** a symbol in the inverted index via `canonical_fqn` (many-to-one, implicit).

---

## Cross-Entity Relationships

```
declarations 1──* dependencies (owns, as src)
declarations 1──* dependencies (owns, as dst)
declarations 1──3 wl_vectors (owns, one per h value)
declarations *──* symbol_freq (references, via symbol_set)
declarations 1──1 declarations_fts (mirrors, content-synced)
re_export_aliases *──1 symbol_freq (references canonical_fqn)
index_meta (standalone)
```

## Schema Versioning

The index is a derived artifact — it is always rebuildable from source `.vo` files. There is no incremental migration. When the schema version changes, the entire index is rebuilt from scratch. The `schema_version` key in `index_meta` is the sole mechanism for detecting incompatibility.
