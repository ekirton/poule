# Modular Index Distribution — Product Requirements Document

Cross-reference: see [semantic-lemma-search.md](semantic-lemma-search.md) for the core search initiative this extends.

## 1. Business Goals

The search index currently ships as a single monolithic file covering a fixed set of libraries. Library maintainers cannot update a single library's index without republishing everything, and users who want the index must rebuild it from source — a process requiring the full Coq toolchain and 15–30 minutes of extraction time.

This initiative delivers modular, per-library index distribution: each supported library is indexed independently and published as a separate asset within a single GitHub Release. The download client fetches all 6 per-library indexes and assembles them into a single search database. The container ships with all supported libraries pre-installed so proof interaction works out of the box.

All 6 libraries are always included in the download. The standard library alone is 32 MB; the remaining 5 libraries add only 14 MB total (~46 MB combined). Per-library selection would add significant complexity (configuration parsing, selective download, partial merge) to save a negligible amount of bandwidth on a one-time download.

**Success metrics:**
- Users receive a working search index covering all 6 supported libraries with no configuration required
- Container startup reports which libraries are currently indexed within 5 seconds of launch
- A merged index produces search results identical in ranking to a monolithically-extracted index of the same libraries

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers using Claude Code | Download a complete search index covering all 6 supported libraries, update when new versions are available | Primary |
| Project maintainers | Automate detection of new library versions, re-indexing, and publishing of updated indexes | Secondary |

---

## 3. Competitive Context

No Coq search tool offers prebuilt indexes across multiple libraries. Lean's search tools (Loogle, Moogle) index Mathlib monolithically — there is no modular build or distribution mechanism. Providing a zero-configuration index covering 6 major libraries is a differentiator that eliminates onboarding friction.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R-P0-1 | Each supported library's index is published as an independent asset within a single GitHub Release |
| R-P0-2 | The download process fetches all 6 per-library indexes from the release |
| R-P0-3 | Downloaded per-library indexes are merged into a single search database usable by all existing search tools |
| R-P0-4 | A merged index produces search results identical in ranking to a monolithically-extracted index of the same library set |
| R-P0-5 | The container pre-installs compiled library files for all 6 supported libraries so proof interaction and extraction work without additional installation |
| R-P0-6 | On every container startup, the system checks whether the index is present and downloads it if missing |
| R-P0-7 | On container startup, the system displays which libraries are currently indexed and available |
| R-P0-8 | The container mounts two persistent directories from the host: a libraries directory for indexes and the user's project directory |
| R-P0-9 | A `--update` flag on the launcher pulls the latest container image and updates library indexes |
| R-P0-10 | Per-library indexes and the merged index are stored in a persistent libraries directory (default `~/poule-libraries/`) configurable via the `POULE_LIBRARIES_PATH` environment variable |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R-P1-1 | A developer script detects new upstream versions of supported libraries, re-extracts changed libraries, and publishes updated index assets |
| R-P1-2 | A host-side launcher executes the developer re-index script inside a container, suitable for scheduled automation (e.g., cron) |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R-P2-1 | Users can add their own project's declarations to the merged index alongside library declarations |

---

## 5. Scope Boundaries

**Supported libraries (this initiative):**
- Coq standard library (stdlib)
- Mathematical Components (mathcomp)
- std++ (stdpp)
- Flocq
- Coquelicot
- CoqInterval

**In scope:**
- Per-library index building and publishing
- Download of all 6 per-library indexes
- Index merging from per-library components
- Container with all 6 libraries pre-installed
- Startup index check and library status reporting
- Launcher update flag for pulling new images and indexes
- Developer automation for detecting and publishing library updates

**Out of scope (this initiative):**
- Libraries beyond the 6 listed above
- Per-library neural model distribution (neural models are distributed separately)
- User project indexing merged with library indexes (existing requirement in semantic-lemma-search)
- Per-library selection or user configuration of library subsets (unnecessary given the small total download size)
