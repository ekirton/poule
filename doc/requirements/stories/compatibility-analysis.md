# User Stories: Cross-Library Compatibility Analysis

Derived from [doc/requirements/compatibility-analysis.md](../compatibility-analysis.md).

---

## Epic 1: Dependency Scanning

### 1.1 Extract Dependencies from opam File

**As a** Coq project maintainer,
**I want** the `/check-compat` command to automatically extract my project's declared dependencies and version constraints from the `.opam` file,
**so that** I do not need to manually list my dependencies when requesting a compatibility check.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with a `.opam` file containing three dependencies with version constraints WHEN `/check-compat` is invoked THEN all three dependencies and their exact constraints are extracted and displayed
- GIVEN a project with a `.opam` file containing dependencies without version constraints WHEN `/check-compat` is invoked THEN those dependencies are extracted with an indication that no constraint is specified
- GIVEN a project with no `.opam` file WHEN `/check-compat` is invoked THEN the command reports that no dependency file was found and prompts the user to specify dependencies manually

**Traces to:** RCA-P0-1

### 1.2 Extract Dependencies from Dune Project

**As a** Coq developer using Dune,
**I want** the `/check-compat` command to extract dependency declarations from my `dune-project` file,
**so that** compatibility analysis works regardless of which build system I use.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with a `dune-project` file containing a `(depends ...)` stanza WHEN `/check-compat` is invoked THEN all listed dependencies and their version constraints are extracted
- GIVEN a project with both a `.opam` and a `dune-project` file WHEN `/check-compat` is invoked THEN the command uses the `.opam` file as the authoritative source and notes the existence of both files
- GIVEN a `dune-project` file with `(coq.theory (theories ...))` entries that imply transitive dependencies WHEN `/check-compat` is invoked THEN the command extracts those implied dependencies

**Traces to:** RCA-P0-1

---

## Epic 2: Constraint Analysis

### 2.1 Retrieve Transitive Dependency Constraints

**As a** Coq project maintainer,
**I want** the `/check-compat` command to query opam metadata for each of my dependencies' own constraints,
**so that** the analysis considers the full dependency tree, not just my direct declarations.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project depending on `coq-mathcomp-ssreflect` WHEN `/check-compat` is invoked THEN the command retrieves `coq-mathcomp-ssreflect`'s constraints on `coq` version, `ocaml` version, and any transitive dependencies from opam metadata
- GIVEN a dependency with multiple available versions WHEN constraints are retrieved THEN the command considers the constraints from all versions that are compatible with the user's declared constraint range
- GIVEN an opam metadata query that fails due to a network error WHEN the failure occurs THEN the command reports which dependency's metadata could not be retrieved and continues with partial analysis

**Traces to:** RCA-P0-2

### 2.2 Check Against a Target Coq Version

**As a** Coq developer planning an upgrade,
**I want** to check whether my dependencies are compatible with a specific Coq version I intend to upgrade to,
**so that** I can assess the feasibility of the upgrade before attempting it.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with dependencies and the user specifies `--coq-version 8.19.0` WHEN `/check-compat` is invoked THEN the analysis constrains the Coq version to 8.19.0 and checks compatibility accordingly
- GIVEN a target Coq version that is incompatible with one dependency WHEN analysis completes THEN the report names the incompatible dependency and its Coq version constraint
- GIVEN a target Coq version that has no packages available in opam WHEN `/check-compat` is invoked THEN the command reports that the specified version is not available

**Traces to:** RCA-P1-2

---

## Epic 3: Conflict Detection

### 3.1 Detect Mutually Incompatible Dependencies

**As a** Coq project maintainer,
**I want** the `/check-compat` command to determine whether my full set of dependencies can be simultaneously satisfied,
**so that** I discover version conflicts before wasting time on a failing `opam install`.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project where dependency A requires `coq >= 8.18` and dependency B requires `coq < 8.18` WHEN `/check-compat` is invoked THEN the report identifies A and B as mutually incompatible due to conflicting Coq version constraints
- GIVEN a project where all dependencies are mutually compatible WHEN `/check-compat` is invoked THEN the report confirms compatibility and states "no conflicts detected"
- GIVEN a project with a transitive conflict (dependency A depends on C >= 2.0, dependency B depends on C < 2.0) WHEN `/check-compat` is invoked THEN the report identifies the transitive conflict through C, naming A and B as the root cause

**Traces to:** RCA-P0-3, RCA-P0-4

### 3.2 Detect Unavailable Dependencies

**As a** Coq developer who may have misspelled a package name or referenced a removed package,
**I want** the `/check-compat` command to flag any dependency that does not exist in configured opam repositories,
**so that** I catch configuration errors before they cause confusing solver failures.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project declaring a dependency on `coq-nonexistent-package` WHEN `/check-compat` is invoked THEN the report flags `coq-nonexistent-package` as not found in any configured opam repository
- GIVEN a project declaring a dependency on a package that exists but has no version matching the declared constraint WHEN `/check-compat` is invoked THEN the report notes that no available version satisfies the constraint and lists the available versions
- GIVEN a misspelled package name that is similar to an existing package WHEN the package is flagged as not found THEN the report suggests the closest matching package name

**Traces to:** RCA-P1-3

### 3.3 Analyze Hypothetical Dependency Addition

**As a** Coq developer considering adding a new library to my project,
**I want** to check whether a prospective dependency would be compatible with my existing dependencies without modifying my project files,
**so that** I can evaluate options before committing to a dependency choice.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with existing dependencies and the user specifies `--add coq-equations` WHEN `/check-compat` is invoked THEN the analysis includes `coq-equations` alongside existing dependencies and reports compatibility
- GIVEN a hypothetical addition that would introduce a conflict WHEN analysis completes THEN the report clearly distinguishes between existing conflicts and conflicts introduced by the proposed addition
- GIVEN a hypothetical addition WHEN analysis completes THEN no project files are modified

**Traces to:** RCA-P1-4

---

## Epic 4: Conflict Explanation and Reporting

### 4.1 Generate Plain-Language Conflict Explanations

**As a** Coq developer who does not understand opam's constraint language,
**I want** each detected conflict to be explained in plain language,
**so that** I understand what is wrong without needing to parse solver diagnostics.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a conflict between `coq-mathcomp-ssreflect` (requires `coq >= 8.18`) and `coq-iris` (requires `coq < 8.18`) WHEN the conflict is reported THEN the explanation states in plain language that these two packages disagree on the required Coq version, naming the specific constraints
- GIVEN a transitive conflict WHEN the explanation is generated THEN it traces the conflict path from the user's direct dependencies through the transitive chain to the conflicting resource
- GIVEN a conflict involving three or more packages constraining the same resource WHEN the explanation is generated THEN it lists all contributing constraints and identifies the minimal incompatible subset

**Traces to:** RCA-P0-5

### 4.2 Generate Compatibility Summary Report

**As a** Coq project maintainer,
**I want** a structured summary report after each compatibility analysis,
**so that** I have a clear overview of my project's dependency health.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with two conflicts and three compatible dependency pairs WHEN the report is generated THEN it includes an overall verdict ("incompatible"), a list of conflicts with explanations, and a confirmation that the remaining pairs are compatible
- GIVEN a project with no conflicts WHEN the report is generated THEN the overall verdict is "compatible" and the report includes the range of Coq versions that satisfy all constraints
- GIVEN a report WHEN it is displayed THEN the conflicts are listed first, followed by compatible dependencies, so the most actionable information is immediately visible

**Traces to:** RCA-P0-6, RCA-P0-7

---

## Epic 5: Resolution Suggestions

### 5.1 Suggest Resolution Strategies for Conflicts

**As a** Coq project maintainer who has been told about a version conflict,
**I want** the `/check-compat` command to suggest concrete resolution strategies,
**so that** I know what to change rather than just what is broken.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a conflict where upgrading package A to version 2.0 would resolve the incompatibility WHEN the resolution is suggested THEN the suggestion names the specific version to upgrade to and confirms that the upgrade resolves the conflict
- GIVEN a conflict with multiple possible resolutions (upgrade A, downgrade B, or use alternative package C) WHEN suggestions are generated THEN all viable options are listed with trade-offs noted
- GIVEN a conflict where no resolution exists within the available package versions WHEN suggestions are generated THEN the report states that no compatible combination was found and suggests contacting the package maintainers or waiting for a new release

**Traces to:** RCA-P1-1

### 5.2 Report Newest Compatible Versions

**As a** Coq project maintainer,
**I want** the `/check-compat` command to report the newest mutually compatible version of each dependency,
**so that** I can keep my dependencies as up-to-date as possible within compatibility constraints.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a project with three compatible dependencies WHEN the report is generated THEN it includes the newest available version of each dependency that is mutually compatible with all others
- GIVEN a project where the newest version of one dependency is incompatible but an older version works WHEN the report is generated THEN it reports the older compatible version and notes that a newer incompatible version exists
- GIVEN a project with no conflicts WHEN newest compatible versions are reported THEN the versions are verified to form a satisfiable combination

**Traces to:** RCA-P1-5
