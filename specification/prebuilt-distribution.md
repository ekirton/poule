# Prebuilt Index Distribution

Download and integrity verification of prebuilt search indexes and neural model checkpoints from GitHub Releases.

**Architecture**: [prebuilt-distribution.md](../doc/architecture/prebuilt-distribution.md), [cli.md](../doc/architecture/cli.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the download client for prebuilt index databases and model checkpoints: release discovery, asset download with progress reporting, integrity verification, and platform-specific file placement.

## 2. Scope

**In scope**: `download-index` CLI subcommand, GitHub Releases API integration, manifest parsing, SHA-256 checksum verification, atomic file placement, platform data directory resolution, publish script behavior.

**Out of scope**: Index creation (owned by extraction), storage schema (owned by storage), neural encoder interface (owned by neural-retrieval), MCP server configuration (owned by mcp-server).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Release | A GitHub Release tagged with the `index-v` prefix, containing index and manifest assets |
| Manifest | A JSON file (`manifest.json`) in each release containing version metadata and SHA-256 checksums |
| Data directory | The platform-specific directory for application data (`~/Library/Application Support/poule/` on macOS, `~/.local/share/poule/` on Linux) |

## 4. Behavioral Requirements

### 4.1 Platform Data Directory

#### get_data_dir()

- REQUIRES: Nothing.
- ENSURES: Returns the platform-specific data directory path for poule. On macOS (`sys.platform == "darwin"`): `~/Library/Application Support/poule/`. On all other platforms: `~/.local/share/poule/`. Does not create the directory.

#### get_model_dir()

- REQUIRES: Nothing.
- ENSURES: Returns `get_data_dir() / "models"`. Does not create the directory.

### 4.2 Release Discovery

#### find_latest_release()

- REQUIRES: Network access to the GitHub API.
- ENSURES: Returns the most recent GitHub Release whose `tag_name` starts with `index-v`. Releases are returned by the API in reverse chronological order; the first match is selected.
- On no matching release: raises an error with message `"No index release found on GitHub."`.
- On network failure: raises an error with message `"Failed to reach GitHub API: {details}"`.

The discovery endpoint is:
```
GET https://api.github.com/repos/ekirton/poule/releases
Accept: application/vnd.github+json
```

No authentication is required (public repository). Unauthenticated rate limit: 60 requests/hour.

> **Given** the repository has releases tagged `index-v1-coq8.19-mc2.2.0` and `index-v1-coq8.20-mc2.3.0`
> **When** `find_latest_release()` is called
> **Then** returns the release with tag `index-v1-coq8.20-mc2.3.0` (most recent)

> **Given** the repository has no releases with `index-v` prefix
> **When** `find_latest_release()` is called
> **Then** raises error: `"No index release found on GitHub."`

### 4.3 Manifest

The manifest is a JSON object with the following schema:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | Yes | Index schema version |
| `coq_version` | string | Yes | Coq version used during extraction |
| `mathcomp_version` | string | Yes | MathComp version used during extraction |
| `index_db_sha256` | string | Yes | Hex-encoded SHA-256 digest of `index.db` |
| `onnx_model_sha256` | string or null | Yes | Hex-encoded SHA-256 digest of the ONNX model, or null if not included |
| `created_at` | string | Yes | ISO 8601 timestamp of index creation |

All values except checksums are read from the `index_meta` table of the source database.

### 4.4 Asset Download

#### download_file(url, dest, label)

- REQUIRES: `url` is a valid HTTPS URL. `dest` is a writable path.
- ENSURES: The file at `url` is downloaded to `{dest}.tmp`. Progress is printed to stderr during download: `Downloading {label} ... {downloaded_mb:.1f} / {total_mb:.1f} MB`. On success, returns the temporary file path. On network failure: deletes the temporary file and raises an error. On any other exception: deletes the temporary file and re-raises.

Downloads use the asset's `browser_download_url` field (direct HTTPS, no redirect handling required). Data is read in 64 KB chunks.

### 4.5 Checksum Verification

#### verify_checksum(path, expected_sha256, label)

- REQUIRES: `path` points to an existing file. `expected_sha256` is a hex-encoded SHA-256 digest string.
- ENSURES: Computes the SHA-256 digest of the file at `path`. If the digest matches `expected_sha256`, returns successfully. If the digest does not match: deletes the file at `path` and raises an error with message `"Checksum verification failed for {label}. Expected {expected}, got {actual}. File deleted."`.

> **Given** a downloaded file whose SHA-256 matches the manifest
> **When** `verify_checksum` is called
> **Then** returns successfully

> **Given** a corrupted download whose SHA-256 does not match the manifest
> **When** `verify_checksum` is called
> **Then** deletes the file and raises a checksum error

### 4.6 Atomic File Placement

After checksum verification succeeds, the temporary file is moved to the final destination via `os.replace()`. This operation is atomic on POSIX systems: the destination path always contains either the previous complete file or the new verified file.

### 4.7 download-index CLI Subcommand

```
poule download-index [--output <path>] [--include-model] [--model-dir <path>] [--force]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output` | path | `./index.db` | Where to save the database file |
| `--include-model` | flag | false | Also download the ONNX neural premise selection model |
| `--model-dir` | path | `get_model_dir()` | Where to save the ONNX model |
| `--force` | flag | false | Overwrite existing files without prompting |

#### Behavior

1. Check if `--output` exists and `--force` is not set → exit 1.
2. If `--include-model`: check if model path exists and `--force` is not set → exit 1.
3. Call `find_latest_release()` to resolve the latest index release.
4. Download `manifest.json` from the release (in memory, not to disk).
5. Download `index.db`: stream to temporary file, verify checksum, atomic rename to `--output`.
6. If `--include-model` and `onnx_model_sha256` is not null: create `--model-dir` if needed, download ONNX model with same stream/verify/rename pattern. If `onnx_model_sha256` is null: print warning to stderr, skip.
7. Print summary to stderr.

> **Given** no `index.db` exists locally and a valid release exists on GitHub
> **When** `download-index` is run
> **Then** `index.db` is downloaded, verified, and placed at `./index.db`

> **Given** `index.db` exists locally and `--force` is not set
> **When** `download-index` is run
> **Then** exits with code 1: `"./index.db already exists. Use --force to overwrite."`

> **Given** `--include-model` is set and the release contains an ONNX model
> **When** `download-index --include-model` is run
> **Then** both `index.db` and the ONNX model are downloaded, verified, and placed

> **Given** `--include-model` is set but the release has no ONNX model
> **When** `download-index --include-model` is run
> **Then** `index.db` is downloaded; a warning is printed to stderr; exit code is 0

## 5. Publish Script

The publish script (`scripts/publish-release.sh`) is a shell script for the project maintainer.

### Signature

```
./scripts/publish-release.sh <DB_PATH> [--model <MODEL_PATH>]
```

### Prerequisites

| Tool | Purpose |
|------|---------|
| `gh` | GitHub CLI, authenticated (`gh auth status`) |
| `sqlite3` | Read version metadata from `index_meta` table |
| `shasum` | Compute SHA-256 checksums |

### Behavior

1. Validate prerequisites (all tools present, `gh` authenticated, files exist).
2. Read `schema_version`, `coq_version`, `mathcomp_version`, `created_at` from the database's `index_meta` table via `sqlite3`.
3. Compute SHA-256 checksums of all assets.
4. Generate `manifest.json` (temporary file).
5. Construct release tag: `index-v{schema_version}-coq{coq_version}-mc{mathcomp_version}`.
6. If tag already exists: abort with error.
7. Create GitHub Release via `gh release create` with all assets.
8. Print release URL on success.

## 6. Error Specification

### download-index

| Condition | Exit code | stderr message |
|-----------|-----------|---------------|
| Output file exists, no `--force` | 1 | `{path} already exists. Use --force to overwrite.` |
| Model file exists, no `--force` | 1 | `{path} already exists. Use --force to overwrite.` |
| Network failure / API unreachable | 1 | `Failed to reach GitHub API: {details}` |
| No matching release | 1 | `No index release found on GitHub.` |
| Asset not found in release | 1 | `Asset '{name}' not found in release '{tag}'.` |
| Download failure | 1 | `Download failed for {label}: {details}` |
| Checksum mismatch | 1 | `Checksum verification failed for {label}. Expected {expected}, got {actual}. File deleted.` |
| Disk write error | 1 | `Failed to write {path}: {details}` |

### publish-release.sh

| Condition | Exit code | stderr message |
|-----------|-----------|---------------|
| `gh` not found | 1 | `Error: gh CLI not found. Install from https://cli.github.com/` |
| `gh` not authenticated | 1 | `Error: gh not authenticated. Run 'gh auth login' first.` |
| `sqlite3` not found | 1 | `Error: sqlite3 not found.` |
| DB file not found | 1 | `Error: {path} does not exist.` |
| Model file not found | 1 | `Error: {path} does not exist.` |
| Missing metadata in `index_meta` | 1 | `Error: could not read version metadata from index_meta table.` |
| Release tag already exists | 1 | `Error: Release {tag} already exists. Delete it first or use a different version.` |

## 7. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Download chunk size | 64 KB |
| External dependencies (download client) | None beyond Python stdlib (`urllib.request`, `json`, `hashlib`, `pathlib`, `os`) |
| Progress reporting | stderr, updated per chunk with `\r` |
| File safety | Atomic rename via `os.replace()`; no partial files left on failure |

## 8. Examples

### Download prebuilt index

```
$ poule download-index
Finding latest index release...
Found release: index-v1-coq8.19-mc2.2.0
  Downloading index.db ... 142.3 / 142.3 MB
  index.db (142.3 MB) -> ./index.db
Done.
```

### Download with neural model

```
$ poule download-index --include-model
Finding latest index release...
Found release: index-v1-coq8.19-mc2.2.0
  Downloading index.db ... 142.3 / 142.3 MB
  index.db (142.3 MB) -> ./index.db
  Downloading neural-premise-selector.onnx ... 98.5 / 98.5 MB
  neural-premise-selector.onnx (98.5 MB) -> /home/user/.local/share/poule/models/neural-premise-selector.onnx
Done.
```

### File already exists

```
$ poule download-index
Error: ./index.db already exists. Use --force to overwrite.
$ echo $?
1
```

### Publish a release

```
$ ./scripts/publish-release.sh index.db --model models/neural-premise-selector.onnx
Index metadata:
  schema_version:  1
  coq_version:     8.19
  mathcomp_version: 2.2.0
  created_at:      2026-03-17T12:00:00Z
  index.db SHA-256: a1b2c3...
  ONNX SHA-256:    d4e5f6...

Generated manifest.json:
{ ... }

Release tag: index-v1-coq8.19-mc2.2.0
Release created: index-v1-coq8.19-mc2.2.0
URL: https://github.com/ekirton/poule/releases/tag/index-v1-coq8.19-mc2.2.0
```

## 9. Language-Specific Notes (Python)

- Use `click.command` for the `download-index` subcommand, registered on the existing `cli` Click group in `poule.cli.commands`.
- Use `urllib.request.urlopen` for HTTP requests (no external HTTP library).
- Use `hashlib.sha256` for checksum computation.
- Use `os.replace` for atomic file rename (POSIX atomic, Windows replaces atomically if same volume).
- Use `click.echo(..., err=True)` for all progress and status output.
- Package location: download client in `src/poule/cli/download.py`, path helpers in `src/poule/paths.py`.
