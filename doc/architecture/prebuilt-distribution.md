# Prebuilt Index Distribution

Technical design for distributing prebuilt search indexes and neural model checkpoints via GitHub Releases, enabling quick-start usage without a Coq toolchain.

**Feature**: [Pre-trained Model Distribution](../features/pre-trained-model.md)

---

## Component Diagram

```
Maintainer workflow (offline)          User workflow (online)

Per-library extraction:
  stdlib → index-stdlib.db             Download client
  mathcomp → index-mathcomp.db           │
  stdpp → index-stdpp.db                 │ fetch all 6 per-library DBs
  flocq → index-flocq.db                │ + manifest
  coquelicot → index-coquelicot.db      ▼
  coqinterval → index-coqinterval.db  ~/poule-libraries/
  │                                      ├── index-stdlib.db
  │ scripts/publish-release.sh           ├── index-mathcomp.db
  ▼                                      ├── index-stdpp.db
GitHub Releases API                      ├── index-flocq.db
  │                                      ├── index-coquelicot.db
  │ gh release create                    ├── index-coqinterval.db
  │ uploads: index-{lib}.db (×6),        └── index.db (merged)
  │   manifest.json,                          │
  │   neural-premise-selector.onnx            │ merge pipeline
  ▼                                           ▼
Release: index-v1-coq9.1               MCP server / CLI (reads index.db)
```

## Distribution Vehicle: GitHub Releases

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Hosting | GitHub Releases | Free for public repos, 2 GB/asset limit, no clone-time impact, no additional infrastructure |
| Not Git LFS | — | LFS stores files in git history; 1 GB/month free bandwidth quota; derived artifacts should not be versioned with source |
| Not GitHub Packages | — | Container/package registry; overkill for two static files |
| Authentication | Unauthenticated | Public repo; no token required for downloads |

## Versioning

Indexes are versioned along four independent dimensions:

| Dimension | Source | Controls |
|-----------|--------|----------|
| Schema version | `index_meta.schema_version` | SQLite schema compatibility |
| Coq version | `index_meta.coq_version` | Compiled library compatibility |
| Library set | `index_meta.libraries` | Which libraries are included |
| Library versions | `index_meta.library_versions` | Per-library content coverage |

### Release Tag Convention

```
index-v{schema_version}-coq{coq_version}
```

Example: `index-v1-coq9.1`

Multiple releases can coexist for different Coq versions. Per-library versions are recorded in the manifest, not the tag. The download client selects the most recent release whose tag starts with `index-v`.

### Release Assets

Each release contains all 6 per-library index databases, a manifest, and an optional model checkpoint:

| Asset | Required | Description |
|-------|----------|-------------|
| `index-stdlib.db` | Yes | Per-library index: Coq standard library |
| `index-mathcomp.db` | Yes | Per-library index: Mathematical Components |
| `index-stdpp.db` | Yes | Per-library index: std++ |
| `index-flocq.db` | Yes | Per-library index: Flocq |
| `index-coquelicot.db` | Yes | Per-library index: Coquelicot |
| `index-coqinterval.db` | Yes | Per-library index: CoqInterval |
| `manifest.json` | Yes | Checksums and version metadata for all libraries |
| `neural-premise-selector.onnx` | No | INT8-quantized ONNX model checkpoint |

## Manifest Protocol

Every release includes a `manifest.json` that the download client fetches first to obtain expected checksums before downloading large assets. The manifest lists all 6 per-library indexes with their checksums and version metadata. The download client reads the manifest, then fetches all 6 per-library assets.

```json
{
  "schema_version": "1",
  "coq_version": "9.1.1",
  "created_at": "2026-03-18T00:00:00Z",
  "libraries": {
    "stdlib": {
      "version": "9.1.1",
      "sha256": "<hex>",
      "asset_name": "index-stdlib.db",
      "declarations": 31035
    },
    "mathcomp": {
      "version": "2.5.0",
      "sha256": "<hex>",
      "asset_name": "index-mathcomp.db",
      "declarations": 57903
    },
    "stdpp": {
      "version": "1.12.0",
      "sha256": "<hex>",
      "asset_name": "index-stdpp.db",
      "declarations": 4868
    },
    "flocq": {
      "version": "4.2.2",
      "sha256": "<hex>",
      "asset_name": "index-flocq.db",
      "declarations": 2599
    },
    "coquelicot": {
      "version": "3.4.4",
      "sha256": "<hex>",
      "asset_name": "index-coquelicot.db",
      "declarations": 2398
    },
    "coqinterval": {
      "version": "4.11.4",
      "sha256": "<hex>",
      "asset_name": "index-coqinterval.db",
      "declarations": 20274
    }
  },
  "onnx_model_sha256": "<hex-or-null>"
}
```

## Libraries Directory

Per-library indexes and the merged index are stored in a persistent directory on the host.

### Directory location

The libraries directory defaults to `~/poule-libraries/` and is overridable via the `POULE_LIBRARIES_PATH` environment variable.

### Directory contents

```
~/poule-libraries/
├── index-stdlib.db       # Per-library index
├── index-mathcomp.db     # Per-library index
├── index-stdpp.db        # Per-library index
├── index-flocq.db        # Per-library index
├── index-coquelicot.db   # Per-library index
├── index-coqinterval.db  # Per-library index
└── index.db              # Merged search index
```

## Index Merge Pipeline

Per-library index databases are combined into a single `index.db` at install time. The merge preserves all data from each source database while resolving cross-database references.

### Merge procedure

1. Create a fresh `index.db` with the standard schema
2. For each per-library database, in deterministic order:
   a. Read all declarations and insert into the target with new auto-assigned IDs
   b. Maintain a name-to-new-ID mapping for dependency resolution
3. After all declarations are inserted:
   a. For each source database, read dependency edges and remap both source and destination IDs using the per-source old-to-new ID map
   b. Insert remapped dependency edges (skip edges where either endpoint's ID is missing from the per-source map)
4. Resolve cross-library dependencies:
   a. Build a suffix reverse-lookup table from all FQNs in the global name-to-ID map
   b. For each declaration, read its `symbol_set` and resolve each symbol against the global name-to-ID map using multi-strategy resolution (exact match, `Coq.` prefix, suffix match)
   c. For each resolved symbol that maps to a different declaration, insert a `(src, dst, "uses")` edge (deduplicated by primary key)
5. Rebuild the FTS5 index from merged declarations
6. Recompute symbol frequencies across the merged declaration set
7. Merge WL histogram vectors with remapped declaration IDs
8. Write `index_meta` with:
   - `schema_version`: from source databases (must all match)
   - `coq_version`: from source databases (must all match)
   - `libraries`: JSON array of all 6 library identifiers
   - `library_versions`: JSON object mapping library identifier to version string
   - `created_at`: current timestamp

### Cross-library dependency resolution

Per-library indexes contain only within-library dependency edges (since each library is extracted in isolation). During merge, cross-library edges are created by re-resolving each declaration's `symbol_set` against the global name-to-ID map using the multi-strategy resolver (exact match, `Coq.` prefix, suffix match — the same strategy used in extraction §4.5). This captures dependencies between libraries (e.g., a MathComp lemma whose type references `nat` from stdlib).

Within-library edges from each source database are also preserved via ID remapping. The combined result is a dependency graph spanning all 6 libraries.

### Determinism

The merge produces identical output given identical input databases and identical library ordering. Library ordering follows the canonical order: stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval.

## Integrity Verification

Downloads are verified by SHA-256 checksum comparison against the manifest:

1. Download asset to a temporary file (`{dest}.tmp`)
2. Compute SHA-256 of the temporary file
3. Compare against the manifest's expected checksum
4. On match: atomic rename (`os.replace`) to final path
5. On mismatch: delete temporary file, report error

The atomic rename ensures the destination path always contains either the previous complete file or the new verified file — never a partial download.

## Container Startup

On every container launch, the entrypoint verifies the search index before starting the user's session.

### Startup sequence

1. If `index.db` exists in the libraries directory and its metadata lists all 6 libraries: proceed to step 4
2. Download any per-library indexes not present in the libraries directory (with checksum verification)
3. Run the merge pipeline to produce a new `index.db`
4. Display a status line listing the indexed libraries and their versions
5. Start the MCP server and user session

### Status display

The startup message lists each indexed library with its version:

```
[poule] Indexed libraries: stdlib 9.1.1, mathcomp 2.5.0, stdpp 1.12.0, flocq 4.2.2, coquelicot 3.4.4, coqinterval 4.11.4
```

## Volume Mounts

The container mounts two host directories:

| Mount | Host default | Container path | Purpose |
|-------|-------------|----------------|---------|
| Libraries | `~/poule-libraries/` (or `POULE_LIBRARIES_PATH`) | `/opt/poule-libraries` | Per-library indexes, merged index.db |
| Project | Current working directory | Working directory | User's Coq project source |

The libraries mount persists per-library index files and the merged index across container restarts.

## Publish Workflow

The maintainer publishes releases via a shell script that:

1. Accepts one or more per-library database files
2. Reads version metadata from each database
3. Verifies all databases share the same schema version and Coq version
4. Computes SHA-256 checksums of all assets
5. Generates `manifest.json` with per-library entries
6. Constructs release tag: `index-v{schema_version}-coq{coq_version}`
7. If tag already exists: abort with error
8. Creates GitHub Release via `gh release create` with all assets

## Relationship to Existing Components

| Component | Relationship |
|-----------|-------------|
| Storage (`IndexWriter`/`IndexReader`) | The distributed `index.db` is produced by `IndexWriter` and consumed by `IndexReader` — no changes to storage interfaces |
| Neural channel | The distributed ONNX model is the same checkpoint loaded by `NeuralEncoder.load()` — no changes to the encoder interface |
| MCP server | Consumes `index.db` via `--db` option — unaware of how the database was obtained |
| Extraction pipeline | Produces per-library `index-{library}.db` files — the publish script packages its output; the download command is an alternative to running extraction |
| Merge pipeline | Combines all 6 per-library databases into single `index.db`; transparent to downstream consumers |
