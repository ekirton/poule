# Index Build Script

Technical design for building per-library search indexes and publishing them as GitHub Release assets.

**Feature**: [Index Build Script](../features/index-build-script.md)

---

## Component Diagram

```
Build workflow:                         Publish workflow:

scripts/build-indexes.sh                scripts/publish-release.sh
  │                                       │
  │ for each library:                     │ reads index_meta from each DB
  │   poule extract --target <lib>        │ computes SHA-256 checksums
  │     --output index-<lib>.db           │ generates manifest.json
  ▼                                       │ gh release create
Extraction Pipeline                       ▼
  │                                     GitHub Releases
  │ discover_libraries(lib)               ├── index-stdlib.db
  │ run_extraction(targets=[lib],         ├── index-mathcomp.db
  │   db_path=index-<lib>.db)             ├── index-stdpp.db
  ▼                                       ├── index-flocq.db
Per-library index DB                      ├── index-coquelicot.db
  ├── index-stdlib.db                     ├── index-coqinterval.db
  ├── index-mathcomp.db                   ├── manifest.json
  ├── index-stdpp.db                      └── neural-premise-selector.onnx (optional)
  ├── index-flocq.db
  ├── index-coquelicot.db
  └── index-coqinterval.db
```

## Library Discovery Extension

The existing `discover_libraries()` function supports `"stdlib"`, `"mathcomp"`, and filesystem paths. It must be extended to support all 6 library identifiers.

### Library-to-Directory Mapping

Each library's compiled `.vo` files reside under the Coq installation's `user-contrib/` directory, but the directory name does not always match the library identifier.

| Library identifier | user-contrib directory | opam package |
|-------------------|----------------------|-------------|
| `stdlib` | `Stdlib` (Rocq 9.x) or `theories/` (Coq 8.x) | `coq` |
| `mathcomp` | `mathcomp` | `coq-mathcomp-ssreflect` |
| `stdpp` | `stdpp` | `coq-stdpp` |
| `flocq` | `Flocq` | `coq-flocq` |
| `coquelicot` | `Coquelicot` | `coq-coquelicot` |
| `coqinterval` | `Interval` | `coq-interval` |

The stdlib case retains existing logic (check both `theories/` and `user-contrib/Stdlib/`, prefer whichever has more `.vo` files). All other libraries use `user-contrib/{contrib_dir}`.

### Discovery Procedure

1. Run `coqc -where` to obtain the Coq base directory
2. If the target is a known library identifier, look up its `user-contrib` subdirectory name from the mapping table
3. Recursively glob for `*.vo` files in that directory
4. If no `.vo` files are found, raise `ExtractionError` naming the library and the searched path

If the target is not a known library identifier and is not a filesystem path, raise `ExtractionError` listing valid library identifiers.

## Per-Library Metadata

Each per-library index database records additional metadata beyond what the current extraction pipeline writes:

| Meta key | Value | Source |
|----------|-------|--------|
| `schema_version` | Schema version string | Hardcoded in pipeline |
| `coq_version` | Coq version | Backend detection |
| `library` | Library identifier (e.g., `"stdlib"`) | Build script parameter |
| `library_version` | Library version string | Version detection |
| `declarations` | Declaration count | Pipeline summary |
| `created_at` | ISO 8601 timestamp | Pipeline |

### Version Detection

Library versions are detected by querying the opam package manager:

| Library | Detection method |
|---------|-----------------|
| stdlib | Parse Coq version from `coqc --version` (stdlib version equals Coq version) |
| mathcomp | `opam show coq-mathcomp-ssreflect --field=version` |
| stdpp | `opam show coq-stdpp --field=version` |
| flocq | `opam show coq-flocq --field=version` |
| coquelicot | `opam show coq-coquelicot --field=version` |
| coqinterval | `opam show coq-interval --field=version` |

## Build Script

`scripts/build-indexes.sh` — a shell script that:

1. Accepts an optional `--libraries` flag with a comma-separated list of library identifiers (default: all 6)
2. Accepts an optional `--output-dir` flag for where to write per-library databases (default: current directory)
3. For each selected library, invokes the extraction CLI:
   ```
   python -m Poule.extraction --target <library> --output <output_dir>/index-<library>.db
   ```
4. Prints a summary table of per-library declaration counts

The script runs extractions sequentially — each library extraction is CPU-bound and memory-intensive, so parallelism provides no benefit within a single container.

## Publish Script Updates

The existing `scripts/publish-release.sh` must be updated from monolithic to per-library format:

### Current behavior (to be replaced)

- Accepts a single `index.db` file
- Reads monolithic metadata (includes `mathcomp_version`)
- Generates a flat manifest with a single `index_db_sha256`
- Tag format: `index-v{schema}-coq{coq}-mc{mathcomp}`

### New behavior

- Accepts multiple per-library `index-{library}.db` files as positional arguments
- Reads `library`, `library_version`, `schema_version`, `coq_version`, and `declarations` from each database's `index_meta` table
- Verifies all databases share the same `schema_version` and `coq_version`
- Generates a manifest with per-library entries matching the manifest protocol defined in [prebuilt-distribution.md](prebuilt-distribution.md)
- Tag format: `index-v{schema_version}-coq{coq_version}` (no per-library versions in tag)
- Creates a GitHub Release with all per-library assets + manifest + optional model

## Relationship to Existing Components

| Component | Change |
|-----------|--------|
| Extraction Pipeline (`discover_libraries`) | Extended with 4 new library targets (stdpp, flocq, coquelicot, coqinterval) |
| Extraction Pipeline (`run_extraction`) | Per-library metadata (`library`, `library_version`, `declarations`) written to `index_meta` |
| Version Detection (`version_detection.py`) | New `detect_library_version(library)` function for all 6 libraries |
| Publish Script (`publish-release.sh`) | Rewritten for per-library format |
| Build Script (`build-indexes.sh`) | New file |
| Prebuilt Distribution (download client) | No changes — already expects per-library format |
| Storage (`IndexWriter`) | No changes — metadata written via existing `write_meta()` |
