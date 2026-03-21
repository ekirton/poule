# Build System Integration

Unified management of Coq's three build tools — `coq_makefile`, Dune, and opam — through MCP tools that Claude Code can invoke to generate project configuration files, run builds, interpret errors in plain language, and manage package dependencies. Instead of requiring developers to learn three separate configuration formats and debug opaque error messages, the build system integration handles the mechanical details so the developer can focus on their Coq code.

---

## Problem

Coq's build story is fragmented across three tools that evolved independently, each with its own configuration format, conventions, and failure modes.

`coq_makefile` is the traditional option: a `_CoqProject` file lists source directories and logical path mappings, and `coq_makefile` generates a Makefile from it. It is simple but limited — no dependency management, no cross-project builds, and the `_CoqProject` must be maintained by hand as the project grows. Dune is more powerful (multi-library projects, incremental builds, cross-project dependencies) but introduces its own complexity: `dune-project` files, per-directory `dune` files, and Coq-specific stanzas (`coq.theory`) with semantics that differ from the OCaml stanzas most Dune documentation covers. opam handles package installation and dependency resolution, but requires `.opam` files written in a domain-specific constraint language and an understanding of version pinning, repository configuration, and switch management.

For newcomers, this fragmentation is a wall. Before writing a single proof, a new Coq developer must choose a build system, learn its configuration format, set up opam correctly, and resolve any dependency version mismatches — all tasks that require expertise they do not yet have. Even experienced developers lose time to misconfigured `_CoqProject` files, missing Dune stanzas, and broken dependency pins. And when builds fail, the error messages from `coqc`, Dune, and opam are terse and assume familiarity with the tool's internal model, making diagnosis slow and frustrating.

## Solution

### Project File Generation

Given a Coq project's directory structure, the build system integration generates the correct configuration files for the developer's chosen build system. For `coq_makefile` projects, this means a `_CoqProject` file with source directories, logical path mappings (`-Q` and `-R` flags), and any required Coq flags. For Dune projects, this means a `dune-project` file and per-directory `dune` files with correct `coq.theory` stanzas, including library names, logical paths, and inter-library dependency declarations. For packages intended for distribution, this means a valid `.opam` file with metadata, dependency declarations with appropriate version constraints, and build instructions.

The generated files are immediately valid — they pass `coq_makefile`, `dune build`, and `opam lint` without manual correction. When the project structure changes (new files, new directories, new dependencies), the configuration can be updated in place, preserving any custom flags or comments the developer has added.

For projects that have outgrown `coq_makefile` and want to adopt Dune, the integration reads an existing `_CoqProject` and generates equivalent Dune configuration, reporting any flags that cannot be directly translated.

### Build Execution and Error Interpretation

The integration runs builds within the conversational workflow — `make` via `coq_makefile`-generated Makefiles or `dune build` — and captures the complete output. When the build succeeds, the developer sees confirmation. When the build fails, each error is interpreted in plain language: what went wrong, why, and what to do about it.

A "Cannot find a physical path bound to logical path" error becomes an explanation that a logical path mapping is missing, with a specific suggestion to add the right `-Q` flag or `theories` entry. A "Required library not found" error becomes an identification of the missing dependency and the opam package that provides it. When builds produce multiple errors, each receives its own explanation and fix suggestion rather than a wall of undifferentiated compiler output.

### Package and Dependency Management

The integration queries opam to report what packages are installed in the current switch and what versions are available in configured repositories. When the developer wants to add a dependency, the integration updates the `.opam` or `dune-project` file with the new package and appropriate version constraints, avoiding duplicates.

Before installation is attempted, the integration checks whether a set of desired dependencies has version conflicts — identifying the specific packages and their incompatible constraints so the developer can resolve the issue proactively rather than waiting for a failed `opam install` and parsing its output.

## Design Rationale

### Why three tools, not one

Coq's build ecosystem is not going to consolidate into a single tool in the near term. `coq_makefile` remains the default for simple projects and much existing documentation. Dune is the direction the ecosystem is moving for serious development. opam is the only package manager. Covering all three is not a design choice — it is a recognition of the ecosystem as it exists. Developers need help with whichever tool they are using, and many projects use all three simultaneously.

### Why Lean's Lake is the competitive benchmark

Lake demonstrates what a well-integrated build and package management experience looks like for a proof assistant. A single `lakefile.lean` configures builds, dependencies, and targets. Lean users rarely struggle with project setup. The gap between Lake's experience and Coq's fragmented toolchain is the single largest developer-experience disadvantage Coq faces relative to Lean. This integration does not unify Coq's tools — that is beyond scope — but it gives developers a single point of interaction (Claude Code) that absorbs the complexity on their behalf, closing the experiential gap.

### What this does not cover

This feature does not manage opam switches — creating, deleting, or switching between them. Switch management is an environment-level concern that interacts with system configuration in ways that are risky to automate without explicit user control.

This feature does not generate continuous integration configuration (GitHub Actions, GitLab CI, etc.). CI pipelines depend on organizational preferences, runner infrastructure, and deployment workflows that vary too widely to address within a build system integration.

This feature does not support build systems other than `coq_makefile` and Dune (e.g., Nix-based Coq builds), does not publish packages to the opam repository, and does not integrate with IDE-specific build features (VS Code tasks, Emacs compile mode).

---

## Acceptance Criteria

### Generate _CoqProject File

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project directory containing `.v` files in subdirectories WHEN project file generation is invoked THEN a `_CoqProject` file is produced listing all source directories with correct `-Q` or `-R` flag mappings
- GIVEN a generated `_CoqProject` file WHEN `coq_makefile -f _CoqProject -o Makefile` is run THEN it succeeds without errors
- GIVEN a project with a single top-level source directory WHEN generation is invoked THEN the logical path mapping uses the directory name as the logical prefix

**Traces to:** R-P0-1

### Generate Dune Build Files

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project directory structure WHEN Dune file generation is invoked THEN a `dune-project` file and per-directory `dune` files are produced with correct `coq.theory` stanzas
- GIVEN generated Dune files WHEN `dune build` is run THEN it succeeds without configuration errors
- GIVEN a project with inter-library dependencies WHEN generation is invoked THEN the `(theories ...)` field in each `dune` file correctly lists the dependencies

**Traces to:** R-P0-2

### Generate .opam File

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project with known dependencies WHEN `.opam` generation is invoked THEN the produced file includes correct `depends`, `build`, `synopsis`, and `maintainer` fields
- GIVEN a generated `.opam` file WHEN `opam lint` is run against it THEN no errors are reported
- GIVEN a project that depends on `coq-mathcomp-ssreflect` version 2.x WHEN generation is invoked THEN the `depends` field includes the constraint `"coq-mathcomp-ssreflect" {>= "2.0.0"}`

**Traces to:** R-P0-3

### Run a Build

**Priority:** P0
**Stability:** Stable

- GIVEN a project with a `_CoqProject` file WHEN a build is requested THEN `coq_makefile` generates a Makefile and `make` is executed, with the complete stdout and stderr captured
- GIVEN a project with a `dune-project` file WHEN a build is requested THEN `dune build` is executed, with the complete stdout and stderr captured
- GIVEN a successful build WHEN the result is returned THEN it indicates success and includes the build output
- GIVEN a failed build WHEN the result is returned THEN it includes the complete error output

**Traces to:** R-P0-4

### Interpret Build Errors

**Priority:** P0
**Stability:** Stable

- GIVEN build output containing a "Cannot find a physical path bound to logical path" error WHEN interpretation is invoked THEN the explanation identifies the missing logical path mapping and suggests adding the correct `-Q` or `-R` flag to `_CoqProject` or the correct `(theories ...)` entry in `dune`
- GIVEN build output containing a "Required library" not-found error WHEN interpretation is invoked THEN the explanation identifies the missing dependency and suggests the opam package to install
- GIVEN build output containing multiple errors WHEN interpretation is invoked THEN each error receives a separate explanation with a specific fix suggestion

**Traces to:** R-P0-5

### Query Installed Packages

**Priority:** P0
**Stability:** Stable

- GIVEN an active opam switch WHEN installed package listing is requested THEN the result includes each installed package name and its version
- GIVEN an active opam switch with `coq` version 8.19.0 installed WHEN the listing is inspected THEN it includes `coq 8.19.0`
- GIVEN the installed package listing WHEN it is returned THEN packages are sorted alphabetically by name

**Traces to:** R-P0-6

### Add a Dependency

**Priority:** P1
**Stability:** Stable

- GIVEN a project with an existing `.opam` file WHEN a dependency on `coq-equations` is added THEN the `depends` field is updated to include `"coq-equations"` with an appropriate version constraint
- GIVEN a project with an existing `dune-project` file WHEN a dependency is added THEN the `(depends ...)` stanza is updated accordingly
- GIVEN an add-dependency request WHEN the package is already listed as a dependency THEN the tool reports that the dependency already exists rather than duplicating it

**Traces to:** R-P1-2

### Detect Version Conflicts

**Priority:** P1
**Stability:** Stable

- GIVEN a set of dependencies where package A requires `coq >= 8.18` and package B requires `coq < 8.18` WHEN conflict detection is invoked THEN the result identifies the conflicting `coq` version constraints from packages A and B
- GIVEN a set of dependencies with no conflicts WHEN conflict detection is invoked THEN the result reports that all constraints are satisfiable
- GIVEN a conflict detection result WHEN it identifies a conflict THEN it names the specific packages and their incompatible constraints

**Traces to:** R-P1-3

### Check Package Availability

**Priority:** P1
**Stability:** Stable

- GIVEN a package name that exists in the configured opam repositories WHEN availability is checked THEN the result lists all available versions of that package
- GIVEN a package name that does not exist WHEN availability is checked THEN the result reports that the package was not found
- GIVEN a package with multiple versions WHEN availability is checked THEN the versions are listed in descending order (newest first)

**Traces to:** R-P1-1

### Update _CoqProject on File Addition

**Priority:** P1
**Stability:** Stable

- GIVEN a project with an existing `_CoqProject` and a newly added subdirectory containing `.v` files WHEN update is invoked THEN the `_CoqProject` is updated with the new directory's logical path mapping
- GIVEN an update request WHEN the existing `_CoqProject` contains custom flags or comments THEN those are preserved in the updated file
- GIVEN a project where no new files or directories have been added WHEN update is invoked THEN the `_CoqProject` is not modified

**Traces to:** R-P1-4

### Migrate from coq_makefile to Dune

**Priority:** P1
**Stability:** Draft

- GIVEN a project with a `_CoqProject` file containing `-Q` and `-R` mappings WHEN migration is invoked THEN equivalent `dune-project` and `dune` files are generated with matching `coq.theory` stanzas
- GIVEN a migrated project WHEN `dune build` is run THEN it builds the same set of `.vo` files that `make` produced under the original configuration
- GIVEN a `_CoqProject` with flags not representable in Dune WHEN migration is invoked THEN the tool reports which flags could not be migrated

**Traces to:** R-P1-5
