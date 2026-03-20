# Index Build Script

A developer-facing script that builds a separate search index database for each of the 6 supported Coq libraries and publishes them as a GitHub Release, producing the artifacts that users download via the modular index distribution system.

**PRD**: [Index Build Script](../requirements/index-build-script.md)
**Stories**: [Index Build Script](../requirements/stories/index-build-script.md)

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
