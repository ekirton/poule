# User Stories: Index Build Script

Derived from [doc/requirements/index-build-script.md](../index-build-script.md).

---

## Epic 1: Per-Library Extraction

### 1.1 Build All Library Indexes

**As a** project maintainer,
**I want to** run a single command that builds a separate index database for each of the 6 supported Coq libraries,
**so that** I can produce all the per-library assets needed for a release without running extraction 6 times manually.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN all 6 supported libraries are installed in the Coq environment WHEN the build script runs THEN it produces 6 files: `index-stdlib.db`, `index-mathcomp.db`, `index-stdpp.db`, `index-flocq.db`, `index-coquelicot.db`, `index-coqinterval.db`
- GIVEN the build script completes WHEN each per-library database is inspected THEN it contains only declarations from its own library (e.g., `index-stdlib.db` contains no MathComp declarations)
- GIVEN the build script completes WHEN each per-library database is inspected THEN its `index_meta` table contains `schema_version`, `coq_version`, `library` (the library identifier), `library_version`, and `created_at`

### 1.2 Discover All 6 Libraries

**As a** project maintainer,
**I want** the extraction pipeline to discover `.vo` files for all 6 supported libraries,
**so that** each library can be extracted independently.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN stdpp is installed via opam WHEN `discover_libraries("stdpp")` is called THEN it returns `.vo` files from the `user-contrib/stdpp` directory
- GIVEN Flocq is installed via opam WHEN `discover_libraries("flocq")` is called THEN it returns `.vo` files from the `user-contrib/Flocq` directory
- GIVEN Coquelicot is installed via opam WHEN `discover_libraries("coquelicot")` is called THEN it returns `.vo` files from the `user-contrib/Coquelicot` directory
- GIVEN CoqInterval is installed via opam WHEN `discover_libraries("coqinterval")` is called THEN it returns `.vo` files from the `user-contrib/Interval` directory
- GIVEN a library identifier that is not one of the 6 supported libraries and is not a filesystem path WHEN `discover_libraries` is called THEN it raises an error

### 1.3 Build Subset of Libraries

**As a** project maintainer iterating on one library,
**I want to** build indexes for only a specified subset of libraries,
**so that** I do not wait for all 6 extractions when I only need to update one.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the build script is invoked with `--libraries stdlib,mathcomp` WHEN it completes THEN only `index-stdlib.db` and `index-mathcomp.db` are produced
- GIVEN the build script is invoked with no `--libraries` flag WHEN it runs THEN it builds all 6 libraries

### 1.4 Per-Library Metadata

**As a** project maintainer,
**I want** each per-library index to record which library it contains and that library's version,
**so that** the publish script and download client can identify each index file.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a per-library index for stdlib is built WHEN the `index_meta` table is queried THEN it contains `library = "stdlib"` and `library_version` matching the installed Coq stdlib version
- GIVEN a per-library index for mathcomp is built WHEN the `index_meta` table is queried THEN it contains `library = "mathcomp"` and `library_version` matching the installed MathComp version

---

## Epic 2: Publish Workflow

### 2.1 Publish Per-Library Assets

**As a** project maintainer,
**I want** the publish script to accept multiple per-library database files and publish them as a single GitHub Release,
**so that** users can download individual library indexes from one release.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN 6 per-library database files WHEN `publish-release.sh index-stdlib.db index-mathcomp.db index-stdpp.db index-flocq.db index-coquelicot.db index-coqinterval.db` is run THEN a GitHub Release is created with all 6 files as assets
- GIVEN the release is created WHEN its assets are listed THEN it includes `index-stdlib.db`, `index-mathcomp.db`, `index-stdpp.db`, `index-flocq.db`, `index-coquelicot.db`, `index-coqinterval.db`, and `manifest.json`

### 2.2 Generate Per-Library Manifest

**As a** project maintainer,
**I want** the publish script to generate a manifest with per-library entries,
**so that** the download client can verify checksums and select individual libraries.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN 6 per-library database files WHEN the publish script runs THEN the generated `manifest.json` contains a `libraries` object with entries for each library
- GIVEN the manifest is generated WHEN its `libraries.stdlib` entry is inspected THEN it contains `version`, `sha256`, `asset_name`, and `declarations` fields
- GIVEN the manifest is generated WHEN the download client parses it THEN it conforms to the manifest protocol defined in the prebuilt distribution specification

---

## Epic 3: Progress and Reporting

### 3.1 Build Progress

**As a** project maintainer running a multi-hour build,
**I want** progress reporting showing which library is being extracted and how far along it is,
**so that** I can estimate completion time and verify the build is not stuck.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the build script is running WHEN it begins extracting a library THEN it prints `Building index for {library}...` to stderr
- GIVEN the build script completes WHEN the summary is printed THEN it lists each library with its declaration count (e.g., `stdlib: 12450 declarations`)
