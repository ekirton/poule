# Modular Index Distribution

All 6 supported Coq libraries are indexed independently, published as per-library assets in a single GitHub Release, and downloaded together into a merged searchable database. Existing search tools work without modification.

**PRD**: [Modular Index Distribution](../requirements/modular-index-distribution.md)
**Stories**: [Modular Index Distribution](../requirements/stories/modular-index-distribution.md)

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
