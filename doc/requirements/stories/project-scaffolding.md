# User Stories: Project Scaffolding

Derived from [doc/requirements/project-scaffolding.md](../project-scaffolding.md).

---

## Epic 1: Core Project Generation

### 1.1 Scaffold a Dune-Based Project

**As a** Coq newcomer using Claude Code,
**I want to** run `/scaffold` and get a complete Dune-based project that builds immediately,
**so that** I can start writing proofs without learning Dune configuration syntax.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the user runs `/scaffold` and provides a project name "my-coq-project" WHEN scaffold generation completes THEN a directory structure is created containing `dune-project`, `theories/dune`, and `theories/MyCoqProject.v`
- GIVEN a scaffolded Dune project WHEN `dune build` is run in the project root THEN the build succeeds without errors
- GIVEN the user specifies "dune" as the build system WHEN scaffold generation completes THEN the `dune-project` file contains a `(coq.theory ...)` stanza with the correct logical name derived from the project name

**Traces to:** RPS-P0-1, RPS-P0-2, RPS-P0-4, RPS-P0-5

### 1.2 Scaffold a coq_makefile-Based Project

**As a** Coq developer who prefers the traditional build system,
**I want to** run `/scaffold` and get a complete `coq_makefile`-based project,
**so that** I can start a project with `_CoqProject` and `Makefile` without writing them by hand.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the user runs `/scaffold` and selects `coq_makefile` as the build system WHEN scaffold generation completes THEN a directory structure is created containing `_CoqProject`, `theories/MyProject.v`, and a `Makefile` or instructions to generate one via `coq_makefile`
- GIVEN a scaffolded `coq_makefile` project WHEN `coq_makefile -f _CoqProject -o Makefile && make` is run THEN the build succeeds without errors
- GIVEN the generated `_CoqProject` WHEN inspected THEN it contains correct `-Q` or `-R` flags mapping the source directory to a logical path

**Traces to:** RPS-P0-1, RPS-P0-3, RPS-P0-4, RPS-P0-5

### 1.3 Generate Directory Structure

**As a** Coq developer starting a new project,
**I want to** have a conventional directory layout generated automatically,
**so that** my project follows community conventions from the start.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the user runs `/scaffold` with project name "verified-sorting" WHEN scaffold generation completes THEN the directory structure includes at minimum a `theories/` directory for Coq source files
- GIVEN the scaffold is generated WHEN the directory structure is inspected THEN no empty directories exist without at least a placeholder file
- GIVEN the user specifies a custom source directory name (e.g., "src" instead of "theories") WHEN scaffold generation completes THEN the specified directory name is used and all build files reference it correctly

**Traces to:** RPS-P0-1, RPS-P0-6

### 1.4 Generate Boilerplate Root Module

**As a** Coq newcomer,
**I want to** have a starter `.v` file generated that compiles without errors,
**so that** I have a working starting point to begin writing my proofs.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a scaffolded project WHEN the root module `theories/ProjectName.v` is inspected THEN it contains a module comment, a `From Coq Require Import` statement, and a placeholder definition or example
- GIVEN the generated root module WHEN compiled with `coqc` (directly or via the build system) THEN it compiles without errors or warnings
- GIVEN the user specified initial dependencies such as MathComp WHEN the root module is inspected THEN it includes appropriate `From` import statements for those dependencies

**Traces to:** RPS-P0-4, RPS-P0-5

---

## Epic 2: Build File Generation

### 2.1 Generate Dune Build Files with Dependencies

**As a** Coq developer starting a project that depends on external libraries,
**I want to** specify my dependencies during scaffolding and have them reflected in the Dune build files,
**so that** my project is correctly configured to find and use its dependencies from the first build.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the user specifies dependencies ["coq-mathcomp-ssreflect", "coq-equations"] during scaffolding WHEN Dune files are generated THEN the `dune-project` includes these in its `(depends ...)` stanza and each `dune` file's `coq.theory` stanza includes them in `(theories ...)`
- GIVEN a project scaffolded with dependencies that are installed in the current opam switch WHEN `dune build` is run THEN the build succeeds
- GIVEN no dependencies are specified WHEN Dune files are generated THEN the `coq.theory` stanza lists only the Coq standard library

**Traces to:** RPS-P0-2, RPS-P1-5

### 2.2 Generate Multi-Library Project Structure

**As a** Coq developer building a library with multiple sub-libraries,
**I want to** scaffold a project with multiple `coq.theory` entries and correct inter-library dependencies,
**so that** I can organize my code into logical units from the start.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN the user specifies two sub-libraries "Core" and "Examples" where "Examples" depends on "Core" WHEN scaffold generation completes THEN separate `dune` files are generated for each with the correct `(theories ...)` dependency from "Examples" to "Core"
- GIVEN a scaffolded multi-library project WHEN `dune build` is run THEN both libraries compile in the correct order without errors
- GIVEN a multi-library scaffold WHEN the directory structure is inspected THEN each library has its own subdirectory under `theories/`

**Traces to:** RPS-P0-1, RPS-P1-6

---

## Epic 3: CI Configuration

### 3.1 Generate GitHub Actions CI Workflow

**As a** Coq developer who wants continuous integration for my project,
**I want to** have a GitHub Actions workflow file generated during scaffolding,
**so that** my project has CI from the first commit without writing YAML manually.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the user opts into CI generation during scaffolding WHEN scaffold generation completes THEN a `.github/workflows/build.yml` file is created
- GIVEN the generated workflow file WHEN inspected THEN it uses a Coq Docker image (e.g., `coqorg/coq`) or sets up opam with Coq installation, and runs the project's build command
- GIVEN a scaffolded project with the generated CI workflow WHEN pushed to a GitHub repository with Actions enabled THEN the workflow runs and the build step succeeds on a clean runner
- GIVEN the user specified a Coq version preference WHEN the CI workflow is generated THEN the workflow uses a Docker image or opam pin matching that version

**Traces to:** RPS-P1-2

### 3.2 Generate .gitignore for Coq Projects

**As a** Coq developer initializing a Git repository,
**I want to** have a `.gitignore` file generated that excludes Coq build artifacts,
**so that** compiled files and build directories are not accidentally committed.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a scaffolded project WHEN the `.gitignore` file is inspected THEN it includes entries for `*.vo`, `*.vok`, `*.vos`, `*.glob`, `*.v.d`, `.coq-native/`, and `_build/`
- GIVEN a Dune-based scaffolded project WHEN the `.gitignore` is inspected THEN it also includes `_build/` (Dune's build directory)
- GIVEN a `coq_makefile`-based scaffolded project WHEN the `.gitignore` is inspected THEN it also includes `Makefile` (since it is generated), `.Makefile.d`, and `*.aux`

**Traces to:** RPS-P1-3

---

## Epic 4: Opam Integration

### 4.1 Generate opam File

**As a** Coq developer who may eventually publish my project as a package,
**I want to** have a valid `.opam` file generated during scaffolding,
**so that** my project is ready for opam packaging from the start.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the user provides a project name "coq-my-library" and a synopsis during scaffolding WHEN the `.opam` file is generated THEN it contains correct `opam-version`, `name`, `synopsis`, `maintainer`, `depends`, and `build` fields
- GIVEN a generated `.opam` file WHEN `opam lint` is run against it THEN no errors are reported
- GIVEN the user specified dependencies during scaffolding WHEN the `.opam` file is inspected THEN those dependencies appear in the `depends` field with appropriate version constraints
- GIVEN a Dune-based project WHEN the `.opam` file is inspected THEN the `build` field uses `dune build` instructions

**Traces to:** RPS-P1-1, RPS-P1-5

---

## Epic 5: Documentation Templates

### 5.1 Generate README

**As a** Coq developer starting a new project,
**I want to** have a README generated with the project name, description, build instructions, and dependency information,
**so that** my project is documented from the first commit.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a scaffolded project WHEN the `README.md` file is inspected THEN it contains the project name as a heading, a description placeholder, build instructions matching the selected build system, and a list of dependencies
- GIVEN a Dune-based project WHEN the README build instructions are inspected THEN they include `opam install . --deps-only` and `dune build`
- GIVEN a `coq_makefile`-based project WHEN the README build instructions are inspected THEN they include `coq_makefile -f _CoqProject -o Makefile && make`

**Traces to:** RPS-P1-4

---

## Epic 6: Slash Command Orchestration

### 6.1 Interactive Parameter Collection

**As a** Coq developer invoking `/scaffold`,
**I want to** be prompted for project parameters (name, build system, dependencies) conversationally,
**so that** the scaffold is tailored to my specific needs without requiring me to memorize command flags.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the user invokes `/scaffold` without arguments WHEN the command starts THEN Claude asks for the project name, build system preference, and optional parameters (dependencies, CI, license)
- GIVEN the user provides a project name only WHEN prompted for build system THEN Claude defaults to Dune if the user does not express a preference
- GIVEN the user provides all required parameters WHEN scaffold generation begins THEN Claude confirms the parameters before generating files

**Traces to:** RPS-P0-6

### 6.2 Orchestrate MCP Tools for File Generation

**As a** Coq developer using `/scaffold`,
**I want to** have the slash command use the Build System Integration MCP tools to generate and validate files,
**so that** the generated files are consistent with what the MCP tools produce individually.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the `/scaffold` command is invoked WHEN build files are generated THEN the slash command delegates to the Build System Integration MCP tools for `_CoqProject`, `dune-project`, `dune`, and `.opam` file generation rather than generating them from scratch
- GIVEN the scaffold uses MCP tools for generation WHEN the generated files are inspected THEN they are identical in format and content to what the MCP tools produce when invoked individually
- GIVEN the scaffold generation completes WHEN the user inspects the output THEN Claude reports a summary of all files created and their locations

**Traces to:** RPS-P0-6
