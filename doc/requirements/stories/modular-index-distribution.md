# User Stories: Modular Index Distribution

Derived from [doc/requirements/modular-index-distribution.md](../modular-index-distribution.md).

---

## Epic 1: Index Download

### 1.1 Download All Libraries

**As a** Coq developer,
**I want** the system to download prebuilt indexes for all 6 supported libraries automatically,
**so that** I have a complete search index without manual configuration.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the system needs a search index WHEN the download runs THEN all 6 per-library index assets (`index-stdlib.db`, `index-mathcomp.db`, `index-stdpp.db`, `index-flocq.db`, `index-coquelicot.db`, `index-coqinterval.db`) are fetched from the release
- GIVEN a per-library index is already present locally with a checksum matching the current release WHEN the download runs THEN that index is not re-downloaded

### 1.2 Checksum Verification

**As a** Coq developer,
**I want** each downloaded library index verified by checksum before use,
**so that** corrupted or tampered downloads do not produce incorrect search results.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a per-library index is downloaded WHEN its SHA-256 checksum matches the manifest THEN the file is placed in the libraries directory
- GIVEN a per-library index is downloaded WHEN its SHA-256 checksum does not match the manifest THEN the file is deleted, an error is reported, and the merge does not proceed

---

## Epic 2: Index Merging

### 2.1 Merge Into Single Database

**As a** Coq developer,
**I want** downloaded per-library indexes merged into a single database,
**so that** all existing search tools work without modification.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN all 6 per-library indexes have been downloaded WHEN the merge completes THEN a single `index.db` exists containing declarations from all 6 libraries
- GIVEN a merged `index.db` WHEN a search query is executed THEN results from all 6 libraries are returned and ranked together
- GIVEN a merged `index.db` WHEN a full-text search is executed THEN it searches across declarations from all 6 libraries

### 2.2 Metadata Tracking

**As a** developer or maintainer,
**I want** the merged database to record which libraries and versions it contains,
**so that** the system can detect when the index needs to be rebuilt.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a merged `index.db` containing all 6 libraries WHEN the metadata is queried THEN it reports all 6 libraries and their versions
- GIVEN a merged `index.db` WHEN the index is missing a library that should be present THEN the system detects the mismatch

---

## Epic 3: Container Library Support

### 3.1 Pre-installed Libraries

**As a** Coq developer,
**I want** all 6 supported libraries' compiled files available in the container,
**so that** I can write proofs using any of them and run extraction without additional installation.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the container is running WHEN `From Flocq Require Import Core.Fcore_defs.` is executed in Coq THEN it succeeds without error
- GIVEN the container is running WHEN `From stdpp Require Import gmap.` is executed in Coq THEN it succeeds without error
- GIVEN the container is running WHEN `From Coquelicot Require Import Coquelicot.` is executed in Coq THEN it succeeds without error

### 3.2 Startup Index Check

**As a** Coq developer,
**I want** the container to check whether the search index is present on every startup and download it if missing,
**so that** I always have a working search index.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN no `index.db` exists in the libraries directory WHEN the container starts THEN all 6 per-library indexes are downloaded, merged, and the index is ready before the user's session begins
- GIVEN `index.db` exists and is up to date WHEN the container starts THEN no download or rebuild occurs and startup proceeds immediately

### 3.3 Startup Library Report

**As a** Coq developer,
**I want** to see which libraries are indexed when the container starts,
**so that** I can confirm the index is complete.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the container starts with a complete index WHEN the startup message is displayed THEN it lists all 6 libraries with their versions (e.g., "stdlib 8.19.2, mathcomp 2.2.0, ...")
- GIVEN the container starts and the index was just downloaded WHEN the startup message is displayed THEN it lists all 6 libraries with their versions

### 3.4 Libraries Volume Mount

**As a** Coq developer,
**I want** per-library indexes stored in a persistent directory on my host machine,
**so that** they survive container restarts and are not re-downloaded each time.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the libraries directory is mounted from `~/poule-libraries/` WHEN per-library indexes are downloaded THEN they are written to the mounted directory and persist after the container stops
- GIVEN the libraries directory contains previously downloaded indexes WHEN a new container starts THEN the existing indexes are available without re-downloading

---

## Epic 4: Update Workflow

### 4.1 Launcher Update Flag

**As a** Coq developer,
**I want** a single command that pulls the latest container and updates my library indexes,
**so that** I can stay current without multiple manual steps.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a newer container image is available WHEN `poule --update` is run THEN the latest image is pulled
- GIVEN newer per-library index assets are available WHEN `poule --update` is run THEN the updated indexes are downloaded and the merged index is rebuilt
- GIVEN the container image and all indexes are already up to date WHEN `poule --update` is run THEN it reports that everything is current and exits

---

## Epic 5: Developer Automation

### 5.1 Nightly Re-index Script

**As a** project maintainer,
**I want** a script that detects new upstream library versions, re-extracts changed libraries, and publishes updated index assets,
**so that** users receive updated indexes without manual maintainer intervention.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN mathcomp has a new version available via opam WHEN the re-index script runs THEN it detects the version change, re-extracts mathcomp, and publishes an updated `index-mathcomp.db` asset
- GIVEN no libraries have new versions WHEN the re-index script runs THEN it reports that all indexes are current and does not publish

### 5.2 Cron-Friendly Host Launcher

**As a** project maintainer,
**I want** a host-side script that runs the nightly re-index inside a container,
**so that** I can schedule it via cron without manual Docker invocations.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN the script is invoked by cron WHEN it executes THEN it runs `docker run` with the appropriate image and mounts, executes the re-index script inside the container, and exits with code 0 on success or non-zero on failure
- GIVEN the script completes WHEN the output is inspected THEN it logs which libraries were checked, which were re-extracted, and whether a new release was published
