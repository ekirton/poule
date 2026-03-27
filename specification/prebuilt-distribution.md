# Prebuilt Index Distribution

Download and integrity verification of prebuilt search indexes and neural model checkpoints from GitHub Releases.

**Architecture**: [prebuilt-distribution.md](../doc/architecture/prebuilt-distribution.md), [cli.md](../doc/architecture/cli.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the download client for prebuilt index databases and model checkpoints: release discovery, asset download with progress reporting, integrity verification, index merging, and publish script behavior.

## 2. Scope

**In scope**: `download-index` CLI subcommand, GitHub Releases API integration, manifest parsing, SHA-256 checksum verification, atomic file placement, per-library index management, index merging, publish script behavior.

**Out of scope**: Index creation (owned by extraction), storage schema (owned by storage), neural encoder interface (owned by neural-retrieval), MCP server configuration (owned by mcp-server).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Release | A GitHub Release tagged with the `index-v` prefix, containing index and manifest assets |
| Manifest | A JSON file (`manifest.json`) in each release containing version metadata and SHA-256 checksums |
| Data directory | The platform-specific directory for application data (`~/Library/Application Support/poule/` on macOS, `~/.local/share/poule/` on Linux) |
| Libraries directory | The host directory storing per-library indexes and the merged index (default `~/poule-libraries/`, overridable via `POULE_LIBRARIES_PATH`) |
| Per-library index | A SQLite database containing declarations from a single Coq library, named `index-{library}.db` |
| Merged index | A single SQLite database combining declarations from all 6 per-library indexes |
| Supported libraries | The fixed set of 6 libraries: `stdlib`, `mathcomp`, `stdpp`, `flocq`, `coquelicot`, `coqinterval` |

## 4. Behavioral Requirements

### 4.1 Platform Data Directory

#### get_data_dir()

- REQUIRES: Nothing.
- ENSURES: Returns the platform-specific data directory path for poule. On macOS (`sys.platform == "darwin"`): `~/Library/Application Support/poule/`. On all other platforms: `~/.local/share/poule/`. Does not create the directory.

#### get_model_dir()

- REQUIRES: Nothing.
- ENSURES: Returns `get_data_dir() / "models"`. Does not create the directory.

### 4.2 Libraries Directory

#### get_libraries_dir()

- REQUIRES: Nothing.
- ENSURES: If `POULE_LIBRARIES_PATH` environment variable is set, returns its value as a Path. Otherwise returns `Path.home() / "poule-libraries"`.

### 4.3 Release Discovery

#### find_latest_release()

- REQUIRES: Network access to the GitHub API.
- ENSURES: Returns the most recent GitHub Release whose `tag_name` starts with `index-v`. Releases are returned by the API in reverse chronological order; the first match is selected.
- On no matching release: raises an error with message `"No index release found on GitHub."`.
- On network failure: raises an error with message `"Failed to reach GitHub API: {details}"`.

The discovery endpoint is:
```
GET https://api.github.com/repos/ekirton/Poule/releases
Accept: application/vnd.github+json
```

No authentication is required (public repository). Unauthenticated rate limit: 60 requests/hour.

> **Given** the repository has releases tagged `index-v1-coq9.1` and `index-v1-coq9.2`
> **When** `find_latest_release()` is called
> **Then** returns the release with tag `index-v1-coq9.2` (most recent)

> **Given** the repository has no releases with `index-v` prefix
> **When** `find_latest_release()` is called
> **Then** raises error: `"No index release found on GitHub."`

### 4.4 Manifest

The manifest is a JSON object with the following schema:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | Yes | Index schema version |
| `coq_version` | string | Yes | Coq version used during extraction |
| `libraries` | object | Yes | Per-library metadata (see below) |
| `onnx_model_sha256` | string or null | Yes | Hex-encoded SHA-256 digest of the ONNX model, or null |
| `created_at` | string | Yes | ISO 8601 timestamp of index creation |

Each entry in `libraries` is keyed by library identifier and contains:

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Library version |
| `sha256` | string | Hex-encoded SHA-256 digest of the per-library index file |
| `asset_name` | string | Release asset filename (e.g., `index-stdlib.db`) |
| `declarations` | integer | Number of declarations in this library's index |

### 4.5 Asset Download

#### download_file(url, dest, label)

- REQUIRES: `url` is a valid HTTPS URL. `dest` is a writable path.
- ENSURES: The file at `url` is downloaded to `{dest}.tmp`. Progress is printed to stderr during download: `Downloading {label} ... {downloaded_mb:.1f} / {total_mb:.1f} MB`. On success, returns the temporary file path. On network failure: deletes the temporary file and raises an error. On any other exception: deletes the temporary file and re-raises.

Downloads use the asset's `browser_download_url` field (direct HTTPS, no redirect handling required). Data is read in 64 KB chunks.

### 4.6 Checksum Verification

#### verify_checksum(path, expected_sha256, label)

- REQUIRES: `path` points to an existing file. `expected_sha256` is a hex-encoded SHA-256 digest string.
- ENSURES: Computes the SHA-256 digest of the file at `path`. If the digest matches `expected_sha256`, returns successfully. If the digest does not match: deletes the file at `path` and raises an error with message `"Checksum verification failed for {label}. Expected {expected}, got {actual}. File deleted."`.

> **Given** a downloaded file whose SHA-256 matches the manifest
> **When** `verify_checksum` is called
> **Then** returns successfully

> **Given** a corrupted download whose SHA-256 does not match the manifest
> **When** `verify_checksum` is called
> **Then** deletes the file and raises a checksum error

### 4.7 Atomic File Placement

After checksum verification succeeds, the temporary file is moved to the final destination via `os.replace()`. This operation is atomic on POSIX systems: the destination path always contains either the previous complete file or the new verified file.

### 4.8 Index Merging

#### merge_indexes(sources, dest)

- REQUIRES: `sources` is a non-empty list of `(library_name, path)` tuples where each path points to a valid per-library SQLite index database. All source databases must share the same `schema_version` and `coq_version` in their `index_meta` tables. `dest` is a writable path. If `dest` exists, it is deleted before merge begins.
- ENSURES: Creates a new SQLite database at `dest` containing:
  - All declarations from all source databases with new auto-assigned IDs
  - All within-library dependency edges with source and destination IDs remapped via per-source old-to-new ID maps. Edges where either endpoint's ID is missing from the per-source map are silently dropped.
  - Cross-library dependency edges generated by resolving each declaration's `symbol_set` entries against the global name-to-ID map using multi-strategy resolution (exact match, `Coq.` prefix, suffix match). Self-references and duplicates (by primary key) are skipped. Ambiguous suffix matches are skipped.
  - All WL histogram vectors with remapped declaration IDs
  - All `re_export_aliases` rows from all source databases. Duplicate `alias_fqn` keys are silently ignored (first source wins via `INSERT OR IGNORE`).
  - A rebuilt FTS5 index covering all merged declarations
  - Recomputed symbol frequencies across the merged set
  - `index_meta` entries: `schema_version` and `coq_version` from sources, `libraries` as JSON array of library identifiers, `library_versions` as JSON object mapping identifier to version, `created_at` as current ISO 8601 timestamp
- Returns a dict with keys: `total_declarations` (int), `total_dependencies` (int), `dropped_dependencies` (int), `libraries` (list of str).

> **Given** all 6 per-library index databases
> **When** `merge_indexes` is called with all 6
> **Then** `dest` contains all declarations from all 6 libraries, and cross-library dependency edges are resolved

> **Given** `index-mathcomp.db` has dependency edges referencing stdlib declarations
> **When** merged with `index-stdlib.db` and all other libraries
> **Then** those dependency edges are resolved by name to the merged stdlib declaration IDs

> **Given** a declaration in `index-coquelicot.db` has `symbol_set` containing `"Corelib.Init.Datatypes.nat"` and `index-stdlib.db` contains declaration `Coq.Init.Datatypes.nat`
> **When** `merge_indexes` is called
> **Then** a cross-library dependency edge `(coquelicot_decl, stdlib_nat, "uses")` is created via `Coq.` prefix resolution

> **Given** two source databases with different `schema_version` values
> **When** `merge_indexes` is called
> **Then** raises error: `"Schema version mismatch: {v1} vs {v2}"`

### 4.9 download-index CLI Subcommand

```
poule download-index [--output <path>] [--libraries-dir <path>] [--include-model] [--model-dir <path>] [--force]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output` | path | `libraries_dir / index.db` | Where to save the merged database file |
| `--libraries-dir` | path | `get_libraries_dir()` | Libraries directory for per-library indexes |
| `--include-model` | flag | false | Also download the ONNX neural premise selection model |
| `--model-dir` | path | `get_model_dir()` | Where to save the ONNX model |
| `--force` | flag | false | Overwrite existing files without prompting |

#### Behavior

1. Call `find_latest_release()` to resolve the latest index release.
2. Download `manifest.json` from the release (in memory).
3. For each of the 6 supported libraries:
   a. Check if `index-{library}.db` exists in `libraries_dir` with checksum matching the manifest → skip if up to date.
   b. Otherwise: download, verify checksum, atomic rename to `libraries_dir / index-{library}.db`.
4. If any library was downloaded or `index.db` does not exist in `libraries_dir`:
   a. Run `merge_indexes` to produce `libraries_dir / index.db`.
5. If `--include-model` and `onnx_model_sha256` is not null: download ONNX model.
6. Print summary.

## 5. Publish Script

The publish script (`scripts/publish-release.sh`) is a shell script for the project maintainer.

### Signature

```
./scripts/publish-release.sh index-stdlib.db index-mathcomp.db ... [--model <MODEL_PATH>] [--replace]
```

### Prerequisites

| Tool | Purpose |
|------|---------|
| `gh` | GitHub CLI, authenticated (`gh auth status`) |
| `sqlite3` | Read version metadata from `index_meta` table |
| `shasum` | Compute SHA-256 checksums |

### Behavior

1. Validate prerequisites (all tools present, `gh` authenticated, files exist).
2. For each per-library DB: read `schema_version`, `coq_version`, `library`, `library_version`, and `declarations` from `index_meta`. Verify all databases share the same `schema_version` and `coq_version`.
3. Compute SHA-256 checksums of all assets.
4. Generate `manifest.json` with per-library entries. Each library entry contains `version` (from `library_version`), `sha256`, `asset_name` (`index-{library}.db`), and `declarations` (from `declarations` metadata key).
5. Construct release tag: `index-v{schema_version}-coq{coq_version}`.
6. If tag already exists and `--replace` is not set: abort with error. If `--replace` is set: delete the existing release via `gh release delete <tag> --yes`, delete the tag via `git push origin :refs/tags/<tag>`, then continue to step 7.
7. Create GitHub Release via `gh release create` with all per-library assets + manifest + optional model.

## 6. Error Specification

### download-index

| Condition | Exit code | stderr message |
|-----------|-----------|---------------|
| Network failure / API unreachable | 1 | `Failed to reach GitHub API: {details}` |
| No matching release | 1 | `No index release found on GitHub.` |
| Library not in release manifest | 1 | `Library '{name}' not found in release manifest.` |
| Asset not found in release | 1 | `Asset '{name}' not found in release '{tag}'.` |
| Download failure | 1 | `Download failed for {label}: {details}` |
| Checksum mismatch | 1 | `Checksum verification failed for {label}. Expected {expected}, got {actual}. File deleted.` |
| Schema version mismatch during merge | 1 | `Schema version mismatch: {v1} vs {v2}` |
| Coq version mismatch during merge | 1 | `Coq version mismatch: {v1} vs {v2}` |
| Disk write error | 1 | `Failed to write {path}: {details}` |

### publish-release.sh

| Condition | Exit code | stderr message |
|-----------|-----------|---------------|
| `gh` not found | 1 | `Error: gh CLI not found. Install from https://cli.github.com/` |
| `gh` not authenticated | 1 | `Error: gh not authenticated. Run 'gh auth login' first.` |
| `sqlite3` not found | 1 | `Error: sqlite3 not found.` |
| DB file not found | 1 | `Error: {path} does not exist.` |
| Model file not found | 1 | `Error: {path} does not exist.` |
| Missing metadata in `index_meta` | 1 | `Error: could not read version metadata from index_meta table in {path}.` |
| Schema version mismatch across DBs | 1 | `Error: schema version mismatch: {path1} has {v1}, {path2} has {v2}.` |
| Coq version mismatch across DBs | 1 | `Error: Coq version mismatch: {path1} has {v1}, {path2} has {v2}.` |
| Release tag already exists (without `--replace`) | 1 | `Error: Release {tag} already exists. Delete it first or use a different version.` |
| `--replace` set, `gh release delete` fails | 1 | `Error: Failed to delete existing release {tag}.` |
| `--replace` set, tag deletion fails | 1 | `Error: Failed to delete tag {tag}.` |

## 7. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Download chunk size | 64 KB |
| External dependencies (download client) | None beyond Python stdlib (`urllib.request`, `json`, `hashlib`, `pathlib`, `os`) |
| Progress reporting | stderr, updated per chunk with `\r` |
| File safety | Atomic rename via `os.replace()`; no partial files left on failure |

## 8. Examples

### Download all libraries

```
$ poule download-index
Finding latest index release...
Found release: index-v1-coq9.1
  Downloading index-stdlib.db ... 30.8 / 30.8 MB
  Downloading index-mathcomp.db ... 3.7 / 3.7 MB
  Downloading index-stdpp.db ... 0.8 / 0.8 MB
  Downloading index-flocq.db ... 1.1 / 1.1 MB
  Downloading index-coquelicot.db ... 1.4 / 1.4 MB
  Downloading index-coqinterval.db ... 6.2 / 6.2 MB
  Merging 6 libraries into index.db...
Done. Indexed: stdlib 9.1.1, mathcomp 2.5.0, stdpp 1.12.0, flocq 4.2.2, coquelicot 3.4.4, coqinterval 4.11.4
```

### Skip up-to-date libraries

```
$ poule download-index
Finding latest index release...
Found release: index-v1-coq9.1
  index-stdlib.db is up to date.
  index-mathcomp.db is up to date.
  index-stdpp.db is up to date.
  index-flocq.db is up to date.
  index-coquelicot.db is up to date.
  index-coqinterval.db is up to date.
  index.db is up to date.
Done. Indexed: stdlib 9.1.1, mathcomp 2.5.0, stdpp 1.12.0, flocq 4.2.2, coquelicot 3.4.4, coqinterval 4.11.4
```

### Download with neural model

```
$ poule download-index --include-model
Finding latest index release...
Found release: index-v1-coq9.1
  Downloading index-stdlib.db ... 30.8 / 30.8 MB
  Downloading index-mathcomp.db ... 3.7 / 3.7 MB
  Downloading index-stdpp.db ... 0.8 / 0.8 MB
  Downloading index-flocq.db ... 1.1 / 1.1 MB
  Downloading index-coquelicot.db ... 1.4 / 1.4 MB
  Downloading index-coqinterval.db ... 6.2 / 6.2 MB
  Merging 6 libraries into index.db...
  Downloading neural-premise-selector.onnx ... 98.5 / 98.5 MB
  neural-premise-selector.onnx (98.5 MB) -> /home/user/.local/share/poule/models/neural-premise-selector.onnx
Done. Indexed: stdlib 9.1.1, mathcomp 2.5.0, stdpp 1.12.0, flocq 4.2.2, coquelicot 3.4.4, coqinterval 4.11.4
```

### Publish a release

```
$ ./scripts/publish-release.sh index-stdlib.db index-mathcomp.db index-stdpp.db index-flocq.db index-coquelicot.db index-coqinterval.db --model models/neural-premise-selector.onnx
Index metadata:
  schema_version:  1
  coq_version:     9.1.1
Libraries:
  stdlib:          9.1.1   (31035 declarations, SHA-256: a1b2c3...)
  mathcomp:        2.5.0   (57903 declarations, SHA-256: d4e5f6...)
  stdpp:           1.12.0  (4868 declarations, SHA-256: 112233...)
  flocq:           4.2.2   (2599 declarations, SHA-256: 445566...)
  coquelicot:      3.4.4   (2398 declarations, SHA-256: 778899...)
  coqinterval:     4.11.4  (20274 declarations, SHA-256: aabbcc...)
  ONNX model:              (SHA-256: 789abc...)

Generated manifest.json:
{ ... }

Release tag: index-v1-coq9.1
Release created: index-v1-coq9.1
URL: https://github.com/ekirton/Poule/releases/tag/index-v1-coq9.1
```

## 9. Language-Specific Notes (Python)

- Use `click.command` for the `download-index` subcommand, registered on the existing `cli` Click group in `poule.cli.commands`.
- Use `urllib.request.urlopen` for HTTP requests (no external HTTP library).
- Use `hashlib.sha256` for checksum computation.
- Use `os.replace` for atomic file rename (POSIX atomic, Windows replaces atomically if same volume).
- Use `click.echo(..., err=True)` for all progress and status output.
- Merge module location: `src/poule/cli/merge.py` or `src/poule/storage/merge.py`.
- Package location: download client in `src/poule/cli/download.py`, path helpers in `src/poule/paths.py`.
