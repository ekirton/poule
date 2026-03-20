# Index Build Script — Product Requirements Document

Cross-reference: see [modular-index-distribution.md](modular-index-distribution.md) for the distribution initiative this enables.

## 1. Business Goals

Per-library index distribution (see modular-index-distribution) requires that each of the 6 supported Coq libraries has an independently built search index published as a GitHub Release asset. Today, the extraction pipeline produces a single index from one or two libraries, and the publish script uploads a single monolithic file. There is no automated workflow for building all 6 per-library indexes and publishing them together.

This initiative delivers a developer-facing script that builds a separate index database for each of the 6 supported libraries and publishes all 6 as a single GitHub Release with a manifest. This is the production workflow that creates the artifacts users download.

**Success metrics:**
- A single command produces 6 per-library index files, one per supported library
- Each per-library index contains only declarations from its own library
- A single command publishes all 6 per-library indexes, a manifest, and an optional model to a GitHub Release
- The published release conforms to the manifest protocol expected by the download client

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Project maintainers | Build all 6 per-library indexes in one operation, publish them as a release | Primary |

---

## 3. Competitive Context

No comparable project provides automated per-library index building and publishing. This is internal developer tooling with no direct competitor.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R-P0-1 | A build script extracts each of the 6 supported libraries into a separate per-library index database named `index-{library}.db` |
| R-P0-2 | The extraction pipeline supports discovering `.vo` files for all 6 supported libraries: stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval |
| R-P0-3 | Each per-library index database contains only declarations from its own library |
| R-P0-4 | The publish script accepts multiple per-library database files and publishes them as a single GitHub Release |
| R-P0-5 | The publish script generates a manifest with per-library entries (version, checksum, asset name, declaration count) conforming to the download client's manifest protocol |
| R-P0-6 | The build script reports progress and a summary showing per-library declaration counts |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R-P1-1 | The build script supports building a subset of the 6 libraries (e.g., only stdlib and mathcomp) for faster iteration |
| R-P1-2 | The build script skips libraries whose per-library index is already up to date (same Coq version, same library version) |

---

## 5. Scope Boundaries

**Supported libraries (same as modular-index-distribution):**
- Coq standard library (stdlib)
- Mathematical Components (mathcomp)
- std++ (stdpp)
- Flocq (flocq)
- Coquelicot (coquelicot)
- CoqInterval (coqinterval)

**In scope:**
- Build script that orchestrates per-library extraction for all 6 libraries
- Extension of library discovery to support all 6 libraries
- Update of publish script from monolithic to per-library format
- Per-library metadata written to each index database

**Out of scope:**
- User-facing download client changes (owned by modular-index-distribution)
- Neural model training or export
- Index merging (owned by download client)
