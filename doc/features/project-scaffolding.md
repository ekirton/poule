# Project Scaffolding

Starting a new Coq project means navigating a maze of interrelated configuration decisions — build system choice, directory layout, logical path mappings, opam metadata, CI setup — before writing a single line of proof. Project Scaffolding eliminates this barrier with a `/scaffold` slash command that generates a complete, buildable project skeleton from a project name and a brief conversation about the developer's needs. What takes hours of boilerplate assembly today becomes a two-minute interaction.

---

## Problem

The Coq ecosystem has no project generator. Before a developer can write their first theorem, they must create and correctly populate configuration files for at least one build system (`dune-project` and per-directory `dune` files, or `_CoqProject` and a `Makefile`), set up logical path mappings, add opam packaging metadata in yet another format, write CI configuration YAML with the right Docker images or opam setup steps, and create a `.gitignore` that covers Coq's many build artifacts. Each of these files has its own syntax and conventions, and none of them generate the others.

Lean solved this problem with Lake: `lake init` produces a complete, buildable project in seconds. Coq developers have no equivalent. Newcomers frequently abandon Coq at the project setup stage — not because the proof assistant is too hard, but because the tooling around it is. Experienced developers fare better but still waste time recreating boilerplate they have written many times before, often by copying from old projects and adapting by hand.

Community template repositories exist but are static snapshots that grow stale and require manual adaptation. They cannot adapt to a specific developer's choices about build system, dependencies, or project structure.

## Solution

Project Scaffolding provides a `/scaffold` slash command that generates everything a developer needs to start a new Coq project. The developer provides a project name and answers a few questions; the command produces a complete directory tree with build files, boilerplate source modules, CI configuration, opam metadata, and documentation templates — all tailored to the developer's choices and all following current Coq community conventions.

### Interactive Parameter Collection

Rather than requiring developers to memorize command flags or configuration schemas, `/scaffold` works conversationally. It asks about the project name, preferred build system, initial dependencies, whether CI is desired, and other optional parameters. Sensible defaults are provided at every step — a developer who simply provides a project name and accepts defaults gets a working Dune-based project without making any other decisions.

### Complete Project Generation

The generated skeleton includes everything needed for a successful first build: directory structure following community conventions, build system configuration (Dune or `coq_makefile`), a root module that compiles without errors, and correctly wired logical path mappings. When the developer requests it, the scaffold also includes opam packaging metadata, GitHub Actions CI workflows, a Coq-appropriate `.gitignore`, and a README with build instructions matching the chosen build system. If the developer specifies dependencies — MathComp, Equations, or others — those dependencies appear in the build files, opam metadata, and import statements consistently.

### Adaptability Over Templates

Unlike static templates, `/scaffold` adapts its output to the developer's specific parameters. A newcomer who wants the simplest possible setup gets a minimal Dune project. An experienced developer building a multi-library package with MathComp dependencies and CI gets a more elaborate scaffold with correct inter-library dependency declarations, opam version constraints, and a CI workflow that installs the right packages. The same command serves both cases because it responds to what the developer asks for rather than stamping out a fixed template.

## Scope

Project Scaffolding provides:

- A `/scaffold` slash command that collects project parameters conversationally
- Directory structure generation following Coq community conventions
- Dune build file generation (`dune-project`, per-directory `dune` files with `coq.theory` stanzas)
- `coq_makefile` build file generation (`_CoqProject`, `Makefile`) as an alternative
- Boilerplate root modules that compile without errors on first build
- opam file generation with correct metadata and dependency declarations
- GitHub Actions CI workflow generation
- Coq-appropriate `.gitignore` generation
- README generation with build instructions matching the chosen build system
- Dependency specification reflected consistently across all generated files
- Multi-library project structures with correct inter-library dependencies

Project Scaffolding does not provide:

- Substantive proof content or theorem statements — the scaffold produces compilable boilerplate only
- Support for build systems other than Dune and `coq_makefile`
- Git repository initialization or remote configuration
- Publishing scaffolded projects to opam repositories
- Ongoing project maintenance after initial scaffolding (see [Build System Integration](build-system-integration.md) for post-setup workflows)
- IDE-specific configuration files
- Static template hosting or distribution outside of Claude Code

---

## Design Rationale

### Why a slash command rather than a standalone tool

Project scaffolding is inherently a multi-step workflow: collect parameters, generate files across multiple directories, validate consistency, and report results. A slash command lets Claude orchestrate this workflow conversationally — asking clarifying questions, confirming choices before generating, and explaining what was created. A single MCP tool call cannot support this kind of back-and-forth interaction. The slash command also reuses the Build System Integration MCP tools as building blocks, ensuring that the generated files are consistent with what those tools produce individually.

### Why interactive parameter collection

Coq project setup involves choices that interact with each other: the build system affects the directory layout, the dependency set affects both build files and opam metadata, and CI configuration depends on all of the above. Presenting these as a flat list of command-line flags would recreate the very complexity the feature aims to eliminate. A conversational interaction lets Claude explain each choice, offer sensible defaults, and adapt later questions based on earlier answers. A newcomer who does not know what Dune is can accept the default; an expert can specify exactly what they want.

### Why Dune as the default build system

Dune is the recommended build system for new Coq projects as of Coq 8.x and the Rocq transition. It provides reproducible builds, better dependency tracking, and is the expected build system for opam packaging. While `coq_makefile` remains widely used in existing projects, steering new projects toward Dune aligns with the direction of the Coq ecosystem. Developers who prefer `coq_makefile` can still select it explicitly.

### Why this matters more than it appears

Project setup is not just an inconvenience — it is an adoption filter. Developers who cannot get a project building in their first session often do not return. Lean's Lake eliminated this problem for Lean, and Lean's rapid adoption growth is partly attributable to the smoothness of the first-project experience. By providing a comparable (and in some ways superior, because it adapts to user choices) experience for Coq, this feature addresses one of the most significant practical barriers to Coq adoption.

## Acceptance Criteria

### Core Project Generation

**Priority:** P0
**Stability:** Stable

- GIVEN the user runs `/scaffold` and provides a project name "my-coq-project" WHEN scaffold generation completes THEN a directory structure is created containing `dune-project`, `theories/dune`, and `theories/MyCoqProject.v`
- GIVEN a scaffolded Dune project WHEN `dune build` is run in the project root THEN the build succeeds without errors
- GIVEN the user specifies "dune" as the build system WHEN scaffold generation completes THEN the `dune-project` file contains a `(coq.theory ...)` stanza with the correct logical name derived from the project name
- GIVEN the user runs `/scaffold` and selects `coq_makefile` as the build system WHEN scaffold generation completes THEN a directory structure is created containing `_CoqProject`, `theories/MyProject.v`, and a `Makefile` or instructions to generate one via `coq_makefile`
- GIVEN a scaffolded `coq_makefile` project WHEN `coq_makefile -f _CoqProject -o Makefile && make` is run THEN the build succeeds without errors
- GIVEN the generated `_CoqProject` WHEN inspected THEN it contains correct `-Q` or `-R` flags mapping the source directory to a logical path
- GIVEN the user runs `/scaffold` with project name "verified-sorting" WHEN scaffold generation completes THEN the directory structure includes at minimum a `theories/` directory for Coq source files
- GIVEN the scaffold is generated WHEN the directory structure is inspected THEN no empty directories exist without at least a placeholder file
- GIVEN the user specifies a custom source directory name (e.g., "src" instead of "theories") WHEN scaffold generation completes THEN the specified directory name is used and all build files reference it correctly
- GIVEN a scaffolded project WHEN the root module `theories/ProjectName.v` is inspected THEN it contains a module comment, a `From Coq Require Import` statement, and a placeholder definition or example
- GIVEN the generated root module WHEN compiled with `coqc` (directly or via the build system) THEN it compiles without errors or warnings
- GIVEN the user specified initial dependencies such as MathComp WHEN the root module is inspected THEN it includes appropriate `From` import statements for those dependencies

**Traces to:** RPS-P0-1, RPS-P0-2, RPS-P0-3, RPS-P0-4, RPS-P0-5, RPS-P0-6

### Build File Generation with Dependencies

**Priority:** P1
**Stability:** Stable

- GIVEN the user specifies dependencies ["coq-mathcomp-ssreflect", "coq-equations"] during scaffolding WHEN Dune files are generated THEN the `dune-project` includes these in its `(depends ...)` stanza and each `dune` file's `coq.theory` stanza includes them in `(theories ...)`
- GIVEN a project scaffolded with dependencies that are installed in the current opam switch WHEN `dune build` is run THEN the build succeeds
- GIVEN no dependencies are specified WHEN Dune files are generated THEN the `coq.theory` stanza lists only the Coq standard library

**Traces to:** RPS-P0-2, RPS-P1-5

### Multi-Library Project Structure

**Priority:** P1
**Stability:** Draft

- GIVEN the user specifies two sub-libraries "Core" and "Examples" where "Examples" depends on "Core" WHEN scaffold generation completes THEN separate `dune` files are generated for each with the correct `(theories ...)` dependency from "Examples" to "Core"
- GIVEN a scaffolded multi-library project WHEN `dune build` is run THEN both libraries compile in the correct order without errors
- GIVEN a multi-library scaffold WHEN the directory structure is inspected THEN each library has its own subdirectory under `theories/`

**Traces to:** RPS-P0-1, RPS-P1-6

### CI Configuration

**Priority:** P1
**Stability:** Stable

- GIVEN the user opts into CI generation during scaffolding WHEN scaffold generation completes THEN a `.github/workflows/build.yml` file is created
- GIVEN the generated workflow file WHEN inspected THEN it uses a Coq Docker image (e.g., `coqorg/coq`) or sets up opam with Coq installation, and runs the project's build command
- GIVEN a scaffolded project with the generated CI workflow WHEN pushed to a GitHub repository with Actions enabled THEN the workflow runs and the build step succeeds on a clean runner
- GIVEN the user specified a Coq version preference WHEN the CI workflow is generated THEN the workflow uses a Docker image or opam pin matching that version
- GIVEN a scaffolded project WHEN the `.gitignore` file is inspected THEN it includes entries for `*.vo`, `*.vok`, `*.vos`, `*.glob`, `*.v.d`, `.coq-native/`, and `_build/`
- GIVEN a Dune-based scaffolded project WHEN the `.gitignore` is inspected THEN it also includes `_build/` (Dune's build directory)
- GIVEN a `coq_makefile`-based scaffolded project WHEN the `.gitignore` is inspected THEN it also includes `Makefile` (since it is generated), `.Makefile.d`, and `*.aux`

**Traces to:** RPS-P1-2, RPS-P1-3

### Opam Integration

**Priority:** P1
**Stability:** Stable

- GIVEN the user provides a project name "coq-my-library" and a synopsis during scaffolding WHEN the `.opam` file is generated THEN it contains correct `opam-version`, `name`, `synopsis`, `maintainer`, `depends`, and `build` fields
- GIVEN a generated `.opam` file WHEN `opam lint` is run against it THEN no errors are reported
- GIVEN the user specified dependencies during scaffolding WHEN the `.opam` file is inspected THEN those dependencies appear in the `depends` field with appropriate version constraints
- GIVEN a Dune-based project WHEN the `.opam` file is inspected THEN the `build` field uses `dune build` instructions

**Traces to:** RPS-P1-1, RPS-P1-5

### Documentation Templates

**Priority:** P1
**Stability:** Stable

- GIVEN a scaffolded project WHEN the `README.md` file is inspected THEN it contains the project name as a heading, a description placeholder, build instructions matching the selected build system, and a list of dependencies
- GIVEN a Dune-based project WHEN the README build instructions are inspected THEN they include `opam install . --deps-only` and `dune build`
- GIVEN a `coq_makefile`-based project WHEN the README build instructions are inspected THEN they include `coq_makefile -f _CoqProject -o Makefile && make`

**Traces to:** RPS-P1-4

### Slash Command Orchestration

**Priority:** P0
**Stability:** Stable

- GIVEN the user invokes `/scaffold` without arguments WHEN the command starts THEN Claude asks for the project name, build system preference, and optional parameters (dependencies, CI, license)
- GIVEN the user provides a project name only WHEN prompted for build system THEN Claude defaults to Dune if the user does not express a preference
- GIVEN the user provides all required parameters WHEN scaffold generation begins THEN Claude confirms the parameters before generating files
- GIVEN the `/scaffold` command is invoked WHEN build files are generated THEN the slash command delegates to the Build System Integration MCP tools for `_CoqProject`, `dune-project`, `dune`, and `.opam` file generation rather than generating them from scratch
- GIVEN the scaffold uses MCP tools for generation WHEN the generated files are inspected THEN they are identical in format and content to what the MCP tools produce when invoked individually
- GIVEN the scaffold generation completes WHEN the user inspects the output THEN Claude reports a summary of all files created and their locations

**Traces to:** RPS-P0-6
