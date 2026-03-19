# Nightly Re-index Automation

Automated detection of new upstream library versions, re-extraction of changed libraries, and publication of updated per-library index assets.

**Feature**: [Modular Index Distribution — Developer Automation](../features/modular-index-distribution.md#developer-automation)
**Stories**: [Epic 6: Developer Automation](../requirements/stories/modular-index-distribution.md#epic-6-developer-automation)

---

## Component Diagram

```
Host machine (cron)                 Container (dev image)

scripts/reindex-cron.sh             scripts/nightly-reindex.sh
  │                                   │
  │ docker run ... nightly-reindex    │ 1. opam update
  │                                   │ 2. detect version changes
  │                                   │ 3. re-extract changed libraries
  │                                   │ 4. publish release
  ▼                                   ▼
Container lifecycle                 Reused components:
  start → run script → exit           ├── opam (version detection)
  exit code propagated                ├── Extraction Pipeline (run_extraction)
                                      ├── publish-release.sh (GitHub Releases)
                                      └── GitHub CLI (gh)
```

## Two-Script Architecture

The automation is split into two scripts with distinct execution environments:

| Script | Runs on | Purpose | Exit code |
|--------|---------|---------|-----------|
| `scripts/nightly-reindex.sh` | Inside container | Detect version changes, re-extract, publish | 0 = success (even if nothing changed), non-zero = failure |
| `scripts/reindex-cron.sh` | Host machine | Start container, run inner script, propagate exit code | Mirrors inner script |

The split exists because extraction requires the Coq toolchain, coq-lsp, and the full opam environment — all of which live inside the container. The host-side script is a thin wrapper that invokes `docker run` with the correct image and mounts.

## Inner Script: `nightly-reindex.sh`

### Version Detection

The script queries opam for the currently installed version of each supported library and compares it against the last-published version recorded in the most recent release's manifest.

```
For each library in {stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval}:
  │
  ├─ Query installed version:
  │    stdlib  → coqc --version (Coq version = stdlib version)
  │    others  → opam list <package> --short --columns=version
  │
  ├─ Query last-published version:
  │    Read manifest.json from the latest index-v* GitHub Release
  │    Extract libraries.<lib>.version
  │
  └─ Compare: if installed != published → mark for re-extraction
```

### Opam Package Names

Each library identifier maps to an opam package name for version queries:

| Library ID | Opam package |
|------------|-------------|
| stdlib | *(derived from `coqc --version`)* |
| mathcomp | coq-mathcomp-ssreflect |
| stdpp | coq-stdpp |
| flocq | coq-flocq |
| coquelicot | coq-coquelicot |
| coqinterval | coq-interval |

### Extraction

For each library marked as changed, the script runs the existing extraction pipeline to produce a per-library index database:

```
For each changed library:
  │
  ├─ run_extraction(targets=[library], db_path=workdir/index-{library}.db)
  │    Reuses Poule.extraction.pipeline.run_extraction
  │    Output: workdir/index-{library}.db
  │
  └─ Verify output exists and is non-empty
```

Libraries that have not changed are not re-extracted. Their existing assets from the current release are carried forward into the new release.

### Carrying Forward Unchanged Assets

When only a subset of libraries has changed, the script must still produce a complete release with all 6 per-library index files. Unchanged libraries' assets are downloaded from the current release and included in the new release alongside freshly extracted assets.

```
For each unchanged library:
  │
  ├─ Download index-{library}.db from current release
  │    (via GitHub Releases API, same as user download path)
  │
  └─ Place in workdir alongside newly extracted files
```

### Publication

After extraction completes, the script publishes a new release containing all per-library index files (both newly extracted and carried forward):

```
1. Collect all per-library index files: workdir/index-{lib}.db (×6)
2. Read metadata from each file (schema_version, coq_version, library_versions)
3. Verify all files share the same schema_version and coq_version
4. Compute SHA-256 checksum for each file
5. Generate manifest.json with per-library entries
6. Construct release tag: index-v{schema_version}-coq{coq_version}
7. If tag exists: delete old release (nightly replaces, not appends)
8. Create new GitHub Release via gh release create with all assets
```

This reuses the manifest format defined in [prebuilt-distribution.md](prebuilt-distribution.md#manifest-protocol).

### No-Change Behavior

When no library has a new version, the script logs that all indexes are current and exits 0 without publishing. This makes it safe to run on every cron invocation without creating spurious releases.

### Pipeline

```
nightly-reindex.sh
  │
  ├─ 1. Fetch current manifest from latest release
  │      gh release view --json assets → download manifest.json
  │      (If no release exists: treat all libraries as changed)
  │
  ├─ 2. Detect installed versions
  │      coqc --version → stdlib version
  │      opam list <pkg> → library versions
  │
  ├─ 3. Compare installed vs. published
  │      For each library: installed_version != manifest_version?
  │      → changed_libs[], unchanged_libs[]
  │
  ├─ 4. Early exit if nothing changed
  │      Log "All indexes are current." → exit 0
  │
  ├─ 5. Re-extract changed libraries
  │      For each lib in changed_libs:
  │        python -m Poule.extraction --target <lib> --db workdir/index-<lib>.db
  │
  ├─ 6. Carry forward unchanged libraries
  │      For each lib in unchanged_libs:
  │        Download index-<lib>.db from current release → workdir/
  │
  ├─ 7. Publish new release
  │      scripts/publish-release.sh --replace workdir/index-*.db
  │
  └─ 8. Log summary
         "Re-indexed: mathcomp 2.2.0 → 2.3.0, flocq 4.2.1 → 4.3.0"
         "Carried forward: stdlib 8.19.2, stdpp 1.12.0, ..."
         "Published: index-v1-coq8.19"
```

## Outer Script: `reindex-cron.sh`

The host-side script is minimal:

```
reindex-cron.sh
  │
  ├─ Pull latest dev image (ensures Coq packages are current)
  │    docker pull ghcr.io/ekirton/Poule:dev
  │
  ├─ Run inner script inside container
  │    docker run --rm \
  │      -e GH_TOKEN=$GH_TOKEN \
  │      ghcr.io/ekirton/Poule:dev \
  │      /poule/scripts/nightly-reindex.sh
  │
  └─ Propagate exit code
```

### Environment Requirements

| Variable | Required | Purpose |
|----------|----------|---------|
| `GH_TOKEN` | Yes | GitHub token with `contents:write` scope for creating releases |

The `GH_TOKEN` is passed into the container via `-e`. The inner script uses `gh` (GitHub CLI), which reads `GH_TOKEN` automatically. No other credentials are needed — opam repositories are public, and the GitHub Releases API for public repos requires only a token for write operations.

### Cron Configuration

The script is designed for daily scheduling. Example crontab entry:

```
0 3 * * * GH_TOKEN=ghp_... /path/to/scripts/reindex-cron.sh >> /var/log/poule-reindex.log 2>&1
```

## Logging

Both scripts write structured log messages to stdout/stderr for cron capture:

| Level | Destination | Examples |
|-------|-------------|---------|
| Progress | stderr | "Checking mathcomp version...", "Extracting flocq..." |
| Summary | stdout | "Re-indexed: mathcomp 2.2.0 → 2.3.0" |
| Errors | stderr | "Extraction failed for coquelicot: backend crash" |

The distinction allows cron to capture the full log while summary lines can be piped or grepped separately.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| GitHub API unreachable | Abort with error, exit 1 |
| No existing release (first run) | Treat all libraries as changed, extract all 6 |
| opam query fails for a library | Log warning, skip that library (do not abort entire run) |
| Extraction fails for one library | Log error, continue with remaining libraries, publish partial update with carried-forward asset for the failed library |
| All extractions fail | Abort, exit 1 (do not publish) |
| `gh release create` fails | Abort with error, exit 1 |
| `GH_TOKEN` not set | `gh` reports auth error, exit 1 |

### Partial Failure

If extraction fails for one library but succeeds for others, the script still publishes a release. The failed library's asset is carried forward from the previous release unchanged. This ensures that a single library's extraction failure does not block updates to all other libraries.

## Relationship to Existing Components

| Component | Relationship |
|-----------|-------------|
| Extraction Pipeline (`run_extraction`) | Reused to produce per-library `index-{lib}.db` files — no modification needed |
| `discover_libraries()` | Reused for `.vo` file discovery — currently supports `stdlib` and `mathcomp`; must be extended to support all 6 library identifiers |
| `scripts/publish-release.sh` | Updated to accept `--replace` flag that deletes an existing release before creating a new one |
| Download client (`download_index`) | Not used by this script — download client is the user-facing counterpart |
| Merge pipeline (`merge_indexes`) | Not used by this script — merging happens on the user side after download |
| Config module | Not used — the nightly script always processes all 6 libraries |

## Design Rationale

### Why a shell script rather than a Python CLI command

The nightly script orchestrates external tools (opam, coqc, gh, docker) and the existing Python extraction pipeline. The control flow is linear: detect → extract → publish. Shell is the natural language for this kind of tool orchestration. The extraction itself runs through the existing Python `run_extraction` function, invoked via the `python -m Poule.extraction` CLI command.

### Why extract inside the container rather than on the host

The extraction pipeline requires coq-lsp, the Coq toolchain, and compiled `.vo` files for all 6 libraries. These are all present in the container image but would require separate installation on the host. Running inside the container guarantees a consistent, reproducible environment.

### Why carry forward unchanged assets rather than re-extracting everything

Re-extracting all 6 libraries takes 15–30 minutes even when nothing has changed. Carrying forward unchanged assets from the current release reduces the typical nightly run to under 5 minutes (version checks only) when no libraries have been updated, and proportional time when only one or two have changed.

### Why delete and replace the release rather than creating a new tag

Per-library index assets are not independently versioned in the tag — the tag captures schema version and Coq version, not individual library versions. When a single library updates, the release content changes but the tag dimensions do not. Replacing the existing release keeps a single "latest" release that the download client can find without tag-version parsing logic.
