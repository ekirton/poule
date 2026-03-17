# Prebuilt Index Distribution

Technical design for distributing prebuilt search indexes and neural model checkpoints via GitHub Releases, enabling quick-start usage without a Coq toolchain.

**Feature**: [Pre-trained Model Distribution](../features/pre-trained-model.md)
**Stories**: [Epic 5: Pre-trained Model Distribution](../requirements/stories/neural-premise-selection.md#epic-5-pre-trained-model-distribution)

---

## Component Diagram

```
Maintainer workflow (offline)          User workflow (online)

index.db (built locally)               CLI download-index subcommand
  │                                      │
  │ scripts/publish-release.sh           │ resolve latest release
  ▼                                      ▼
GitHub Releases API                    GitHub Releases API
  │                                      │
  │ gh release create                    │ GET /repos/.../releases
  │ uploads: index.db,                   │ download: manifest.json,
  │   manifest.json,                     │   index.db,
  │   neural-premise-selector.onnx       │   neural-premise-selector.onnx
  ▼                                      ▼
Release: index-v1-coq8.19-mc2.2.0     Local filesystem
                                         ├── ./index.db
                                         └── <data_dir>/models/
                                               neural-premise-selector.onnx
```

## Distribution Vehicle: GitHub Releases

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Hosting | GitHub Releases | Free for public repos, 2 GB/asset limit, no clone-time impact, no additional infrastructure |
| Not Git LFS | — | LFS stores files in git history; 1 GB/month free bandwidth quota; derived artifacts should not be versioned with source |
| Not GitHub Packages | — | Container/package registry; overkill for two static files |
| Authentication | Unauthenticated | Public repo; no token required for downloads |

## Versioning

Indexes are versioned along three independent dimensions:

| Dimension | Source | Controls |
|-----------|--------|----------|
| Schema version | `index_meta.schema_version` | SQLite schema compatibility |
| Coq version | `index_meta.coq_version` | Compiled library compatibility |
| MathComp version | `index_meta.mathcomp_version` | Library content coverage |

### Release Tag Convention

```
index-v{schema_version}-coq{coq_version}-mc{mathcomp_version}
```

Example: `index-v1-coq8.19-mc2.2.0`

Multiple releases can coexist for different Coq/MathComp combinations. The download client selects the most recent release whose tag starts with `index-v`.

### Release Assets

Each release contains up to three assets:

| Asset | Required | Description |
|-------|----------|-------------|
| `index.db` | Yes | SQLite search index |
| `manifest.json` | Yes | Checksums and version metadata |
| `neural-premise-selector.onnx` | No | INT8-quantized ONNX model checkpoint |

## Manifest Protocol

Every release includes a `manifest.json` that the download client fetches first to obtain expected checksums before downloading large assets.

```json
{
  "schema_version": "1",
  "coq_version": "8.19",
  "mathcomp_version": "2.2.0",
  "index_db_sha256": "<hex>",
  "onnx_model_sha256": "<hex-or-null>",
  "created_at": "2026-03-17T00:00:00Z"
}
```

All metadata values are read from the `index_meta` table in the source database.

## Integrity Verification

Downloads are verified by SHA-256 checksum comparison against the manifest:

1. Download asset to a temporary file (`{dest}.tmp`)
2. Compute SHA-256 of the temporary file
3. Compare against the manifest's expected checksum
4. On match: atomic rename (`os.replace`) to final path
5. On mismatch: delete temporary file, report error

The atomic rename ensures the destination path always contains either the previous complete file or the new verified file — never a partial download.

## Platform Data Directory

The ONNX model checkpoint is placed in a platform-specific data directory, following the convention established in [neural-retrieval.md](neural-retrieval.md):

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/poule/models/neural-premise-selector.onnx` |
| Linux | `~/.local/share/poule/models/neural-premise-selector.onnx` |

The `index.db` file is placed in the current working directory by default (matching the existing `--db` convention).

## CLI Integration

The download client is exposed as a `download-index` subcommand on the existing CLI group. See the [CLI architecture](cli.md) for the full subcommand structure.

```
poule download-index [--output ./index.db] [--include-model] [--model-dir <path>] [--force]
```

The command uses only Python standard library modules (`urllib.request`, `json`, `hashlib`) — no additional dependencies.

## Publish Workflow

The maintainer publishes releases via a shell script that:

1. Reads version metadata from the built `index.db` via `sqlite3`
2. Computes SHA-256 checksums
3. Generates `manifest.json`
4. Creates a GitHub Release via `gh release create`

This is a manual process — the maintainer builds the index, verifies quality, then publishes. No CI/CD pipeline is required.

## Relationship to Existing Components

| Component | Relationship |
|-----------|-------------|
| Storage (`IndexWriter`/`IndexReader`) | The distributed `index.db` is produced by `IndexWriter` and consumed by `IndexReader` — no changes to storage interfaces |
| Neural channel | The distributed ONNX model is the same checkpoint loaded by `NeuralEncoder.load()` — no changes to the encoder interface |
| MCP server | Consumes `index.db` via `--db` option — unaware of how the database was obtained |
| Extraction pipeline | Produces `index.db` — the publish script packages its output; the download command is an alternative to running extraction |
