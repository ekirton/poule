# Modular Index Distribution

All 6 supported Coq libraries are indexed independently, published as per-library assets in a single GitHub Release, and downloaded together into a merged searchable database. Existing search tools work without modification.

**PRD**: [Modular Index Distribution](../requirements/modular-index-distribution.md)

---

## Problem

The search index ships as a single monolithic file covering a fixed library set. This creates two friction points:

1. **All-or-nothing updates** — when one library releases a new version, the entire index must be republished and re-downloaded
2. **No prebuilt index** — users who want the index must rebuild from source, which requires the full Coq toolchain and 15–30 minutes

## Solution

Six Coq libraries are supported as independently built and published index components:

| Library | Description |
|---------|-------------|
| stdlib | Coq standard library |
| mathcomp | Mathematical Components |
| stdpp | Extended standard library (MPI-SWS) |
| flocq | Floating-point formalization |
| coquelicot | Real analysis |
| coqinterval | Interval arithmetic |

All 6 per-library indexes are published in a single GitHub Release. The download client fetches all 6 and assembles them into a single database. All existing search and retrieval tools operate on this merged database without awareness of its modular origin.

There is no per-library selection or configuration. The standard library alone is 32 MB; the remaining 5 libraries add only 14 MB (~46 MB total). Per-library selection would add significant complexity for negligible bandwidth savings on a one-time download.

## Container Experience

The container ships with all 6 libraries' compiled Coq files pre-installed. This means:

- **Proof interaction** works for any of the 6 libraries immediately — users can `Require Import` from any of them
- **Local extraction** is possible — users can rebuild their index for any combination without installing additional packages
- **Startup check** — every container launch verifies the index is present and downloads it if missing
- **Status display** — startup reports which libraries are currently indexed, so users can confirm the index is complete

Two host directories are mounted into the container: the libraries directory (for indexes) and the user's project directory (current working directory).

## Update Workflow

A `--update` flag on the launcher pulls the latest container image and checks for newer per-library index assets. If any library has an updated index available, it is downloaded and the merged index is rebuilt. This provides a single command for staying current.

## Developer Automation

A maintainer-facing script detects new upstream library versions (via the package manager), re-extracts changed libraries, and publishes updated index assets. A host-side launcher wraps this in a container invocation suitable for scheduled automation.

## Design Rationale

### Why download-and-merge rather than multiple attached databases

Merging per-library databases into a single file at install time keeps all existing search code unchanged — every retrieval channel, the full-text search index, and the dependency graph operate on a single database with a single ID space. The alternative (querying across multiple attached SQLite databases at runtime) would require rewriting every query, fragmenting the FTS index, and handling cross-database foreign keys for dependencies.

### Why 6 libraries

These 6 were selected because they are all: actively maintained, in the Rocq Platform, compatible with Coq 8.19, and extractable without special processing (no custom proof modes). They form two coherent dependency chains — the numerical analysis stack (Flocq → Coquelicot → CoqInterval) and the general-purpose extension (stdpp) — alongside the two anchor libraries (stdlib, MathComp). Libraries requiring custom extraction handling (Iris, CompCert) are excluded from the prebuilt set.

### Why always include all 6

The standard library dominates the index at 32 MB. The other 5 libraries add only 14 MB total. Per-library selection would require a configuration file, config parsing, selective download logic, and partial merge handling — significant complexity to save ~14 MB on a one-time download. Users who have the container already have all 6 libraries' compiled files installed, so including all 6 in the search index is the expected behavior.

### Why co-locate indexes in a persistent directory

Placing per-library indexes and the merged `index.db` in a dedicated directory (`~/poule-libraries/`) keeps all persistent index state in one place. This directory is mounted into the container, so both the host-side launcher and the in-container tools see the same data without synchronization. The path is overridable via `POULE_LIBRARIES_PATH`.

## Scope Boundaries

This feature provides:

- Per-library index building and publishing
- Download of all 6 per-library indexes with integrity verification
- Transparent assembly of per-library indexes into a single search database
- Container with all 6 libraries available for proof interaction
- Startup index check and status reporting
- Single-command update workflow

It does **not** provide:

- Libraries beyond the 6 listed (future expansion possible by adding identifiers)
- Per-library neural model distribution
- Per-library selection or user configuration of library subsets
- Automatic detection of which libraries a user's project needs
- Runtime switching of library sets without container restart

---

## Acceptance Criteria

### Download All Libraries

**Priority:** P0
**Stability:** Stable

- GIVEN the system needs a search index WHEN the download runs THEN all 6 per-library index assets (`index-stdlib.db`, `index-mathcomp.db`, `index-stdpp.db`, `index-flocq.db`, `index-coquelicot.db`, `index-coqinterval.db`) are fetched from the release
- GIVEN a per-library index is already present locally with a checksum matching the current release WHEN the download runs THEN that index is not re-downloaded

### Checksum Verification

**Priority:** P0
**Stability:** Stable

- GIVEN a per-library index is downloaded WHEN its SHA-256 checksum matches the manifest THEN the file is placed in the libraries directory
- GIVEN a per-library index is downloaded WHEN its SHA-256 checksum does not match the manifest THEN the file is deleted, an error is reported, and the merge does not proceed

### Merge Into Single Database

**Priority:** P0
**Stability:** Stable

- GIVEN all 6 per-library indexes have been downloaded WHEN the merge completes THEN a single `index.db` exists containing declarations from all 6 libraries
- GIVEN a merged `index.db` WHEN a search query is executed THEN results from all 6 libraries are returned and ranked together
- GIVEN a merged `index.db` WHEN a full-text search is executed THEN it searches across declarations from all 6 libraries

### Metadata Tracking

**Priority:** P0
**Stability:** Stable

- GIVEN a merged `index.db` containing all 6 libraries WHEN the metadata is queried THEN it reports all 6 libraries and their versions
- GIVEN a merged `index.db` WHEN the index is missing a library that should be present THEN the system detects the mismatch

### Pre-installed Libraries

**Priority:** P0
**Stability:** Stable

- GIVEN the container is running WHEN `From Flocq Require Import Core.Fcore_defs.` is executed in Coq THEN it succeeds without error
- GIVEN the container is running WHEN `From stdpp Require Import gmap.` is executed in Coq THEN it succeeds without error
- GIVEN the container is running WHEN `From Coquelicot Require Import Coquelicot.` is executed in Coq THEN it succeeds without error

### Startup Index Check

**Priority:** P0
**Stability:** Stable

- GIVEN no `index.db` exists in the libraries directory WHEN the container starts THEN all 6 per-library indexes are downloaded, merged, and the index is ready before the user's session begins
- GIVEN `index.db` exists and is up to date WHEN the container starts THEN no download or rebuild occurs and startup proceeds immediately

### Startup Library Report

**Priority:** P0
**Stability:** Stable

- GIVEN the container starts with a complete index WHEN the startup message is displayed THEN it lists all 6 libraries with their versions (e.g., "stdlib 8.19.2, mathcomp 2.2.0, ...")
- GIVEN the container starts and the index was just downloaded WHEN the startup message is displayed THEN it lists all 6 libraries with their versions

### Libraries Volume Mount

**Priority:** P0
**Stability:** Stable

- GIVEN the libraries directory is mounted from `~/poule-libraries/` WHEN per-library indexes are downloaded THEN they are written to the mounted directory and persist after the container stops
- GIVEN the libraries directory contains previously downloaded indexes WHEN a new container starts THEN the existing indexes are available without re-downloading

### Launcher Update Flag

**Priority:** P0
**Stability:** Stable

- GIVEN a newer container image is available WHEN `poule --update` is run THEN the latest image is pulled
- GIVEN newer per-library index assets are available WHEN `poule --update` is run THEN the updated indexes are downloaded and the merged index is rebuilt
- GIVEN the container image and all indexes are already up to date WHEN `poule --update` is run THEN it reports that everything is current and exits
