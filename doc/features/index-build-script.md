# Index Build Script

A developer-facing script that builds a separate search index database for each of the 6 supported Coq libraries and publishes them as a GitHub Release, producing the artifacts that users download via the modular index distribution system.

**PRD**: [Index Build Script](../requirements/index-build-script.md)

---

## Problem

The modular index distribution system requires 6 per-library index database files (`index-stdlib.db`, `index-mathcomp.db`, etc.) published as GitHub Release assets. Today, the extraction pipeline supports only stdlib and mathcomp targets, and the publish script uploads a single monolithic database. There is no workflow for building all 6 libraries independently or publishing them in the per-library format expected by the download client.

## Solution

Two scripts form the production workflow:

1. **Build script** — runs the extraction pipeline once per library, producing 6 independent `index-{library}.db` files. Each contains only declarations from its own library with per-library metadata (library identifier, library version, schema version, Coq version).

2. **Publish script** (updated) — accepts all 6 per-library databases, reads metadata from each, generates a manifest with per-library checksums and declaration counts, and publishes everything as a single GitHub Release.

### Supported Libraries

| Identifier | opam contrib directory | Description |
|-----------|----------------------|-------------|
| stdlib | `Stdlib` (or `theories/`) | Coq standard library |
| mathcomp | `mathcomp` | Mathematical Components |
| stdpp | `stdpp` | Extended standard library (MPI-SWS) |
| flocq | `Flocq` | Floating-point formalization |
| coquelicot | `Coquelicot` | Real analysis |
| coqinterval | `Interval` | Interval arithmetic |

### Library Discovery

The extraction pipeline's library discovery is extended to locate `.vo` files for all 6 libraries. Each library's compiled files reside under `user-contrib/` in the Coq installation, with directory names that may differ from the library identifier (e.g., CoqInterval uses `Interval/`, not `coqinterval/`).

### Per-Library Metadata

Each per-library index database records its identity in the `index_meta` table: `library` (identifier), `library_version` (version string), `schema_version`, `coq_version`, and `created_at`. The publish script reads these metadata entries to construct the manifest.

### Version Detection

Library versions are detected from the installed opam packages. The detection strategy varies by library — some embed version info in their compiled files, while others require querying the package manager.

## Design Rationale

### Why a build script rather than extending the CLI

The build script orchestrates 6 sequential extractions — each is a full pipeline run producing an independent database. This is a batch developer workflow, not an interactive command. A shell script calling the extraction CLI once per library is simpler and more transparent than adding multi-target orchestration to the Python CLI.

### Why per-library databases rather than one database with library tags

Per-library databases enable independent publishing and downloading. A user adding one library downloads one new file and re-merges. The alternative — a single database with per-row library tags — would require re-downloading the entire index whenever any library updates.

### Why extend discover_libraries rather than hardcode paths in the build script

Library discovery belongs in the extraction module because it encapsulates knowledge of Coq's installation layout (which varies between Coq 8.x and Rocq 9.x). The build script should declare *what* to extract, not *where* to find files.

## Scope Boundaries

This feature provides:

- Build script for producing all 6 per-library index databases
- Extended library discovery for all 6 supported libraries
- Updated publish script for per-library release format
- Per-library metadata in each index database

It does **not** provide:

- User-facing download or merge changes
- Neural model building or publishing (handled separately)
- Support for libraries beyond the 6 listed

---

## Acceptance Criteria

### Build All Library Indexes

**Priority:** P0
**Stability:** Stable

- GIVEN all 6 supported libraries are installed in the Coq environment WHEN the build script runs THEN it produces 6 files: `index-stdlib.db`, `index-mathcomp.db`, `index-stdpp.db`, `index-flocq.db`, `index-coquelicot.db`, `index-coqinterval.db`
- GIVEN the build script completes WHEN each per-library database is inspected THEN it contains only declarations from its own library (e.g., `index-stdlib.db` contains no MathComp declarations)
- GIVEN the build script completes WHEN each per-library database is inspected THEN its `index_meta` table contains `schema_version`, `coq_version`, `library` (the library identifier), `library_version`, and `created_at`

### Discover All 6 Libraries

**Priority:** P0
**Stability:** Stable

- GIVEN stdpp is installed via opam WHEN `discover_libraries("stdpp")` is called THEN it returns `.vo` files from the `user-contrib/stdpp` directory
- GIVEN Flocq is installed via opam WHEN `discover_libraries("flocq")` is called THEN it returns `.vo` files from the `user-contrib/Flocq` directory
- GIVEN Coquelicot is installed via opam WHEN `discover_libraries("coquelicot")` is called THEN it returns `.vo` files from the `user-contrib/Coquelicot` directory
- GIVEN CoqInterval is installed via opam WHEN `discover_libraries("coqinterval")` is called THEN it returns `.vo` files from the `user-contrib/Interval` directory
- GIVEN a library identifier that is not one of the 6 supported libraries and is not a filesystem path WHEN `discover_libraries` is called THEN it raises an error

### Build Subset of Libraries

**Priority:** P1
**Stability:** Stable

- GIVEN the build script is invoked with `--libraries stdlib,mathcomp` WHEN it completes THEN only `index-stdlib.db` and `index-mathcomp.db` are produced
- GIVEN the build script is invoked with no `--libraries` flag WHEN it runs THEN it builds all 6 libraries

### Force Rebuild

**Priority:** P1
**Stability:** Stable

- GIVEN the build script is invoked with `--force` WHEN it completes THEN all selected per-library indexes are rebuilt regardless of whether their library versions have changed
- GIVEN the build script rebuilds any per-library index (whether due to `--force` or a version change) WHEN the merge step runs THEN the merged `index.db` is regenerated from all per-library indexes

### Merge Per-Library Indexes

**Priority:** P0
**Stability:** Stable

- GIVEN all per-library indexes have been built WHEN the build script reaches the merge step THEN it produces a single `index.db` combining all per-library declarations
- GIVEN the merged `index.db` already exists and all per-library index versions match WHEN no per-library index was rebuilt during this run THEN the merge step is skipped
- GIVEN any per-library index was rebuilt during this run WHEN the merge step runs THEN `index.db` is regenerated even if library version strings have not changed

### Per-Library Metadata

**Priority:** P0
**Stability:** Stable

- GIVEN a per-library index for stdlib is built WHEN the `index_meta` table is queried THEN it contains `library = "stdlib"` and `library_version` matching the installed Coq stdlib version
- GIVEN a per-library index for mathcomp is built WHEN the `index_meta` table is queried THEN it contains `library = "mathcomp"` and `library_version` matching the installed MathComp version

### Publish Per-Library Assets

**Priority:** P0
**Stability:** Stable

- GIVEN 6 per-library database files WHEN `publish-release.sh index-stdlib.db index-mathcomp.db index-stdpp.db index-flocq.db index-coquelicot.db index-coqinterval.db` is run THEN a GitHub Release is created with all 6 files as assets
- GIVEN the release is created WHEN its assets are listed THEN it includes `index-stdlib.db`, `index-mathcomp.db`, `index-stdpp.db`, `index-flocq.db`, `index-coquelicot.db`, `index-coqinterval.db`, and `manifest.json`

### Generate Per-Library Manifest

**Priority:** P0
**Stability:** Stable

- GIVEN 6 per-library database files WHEN the publish script runs THEN the generated `manifest.json` contains a `libraries` object with entries for each library
- GIVEN the manifest is generated WHEN its `libraries.stdlib` entry is inspected THEN it contains `version`, `sha256`, `asset_name`, and `declarations` fields
- GIVEN the manifest is generated WHEN the download client parses it THEN it conforms to the manifest protocol defined in the prebuilt distribution specification

### Build Progress

**Priority:** P0
**Stability:** Stable

- GIVEN the build script is running WHEN it begins extracting a library THEN it prints `Building index for {library}...` to stderr
- GIVEN the build script completes WHEN the summary is printed THEN it lists each library with its declaration count (e.g., `stdlib: 12450 declarations`)
