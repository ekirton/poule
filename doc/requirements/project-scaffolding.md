# Project Scaffolding — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md), section 4 (Agentic Workflows) for ecosystem context.

## 1. Business Goals

Starting a new Coq/Rocq project is disproportionately difficult relative to the complexity of the work itself. Before writing a single line of proof, a developer must make interrelated decisions about build system choice (`coq_makefile` vs. Dune), directory layout conventions, logical path mappings, opam packaging metadata, and CI configuration — then express those decisions correctly across multiple configuration files with different syntaxes. Newcomers frequently abandon Coq at this stage, and experienced developers lose time recreating boilerplate they have written many times before.

This initiative provides a Claude Code slash command (`/scaffold`) that generates a complete, buildable project skeleton from a project name and minimal user input. The command orchestrates the MCP tools from the Build System Integration initiative to produce directory structures, build files, CI configuration, opam metadata, boilerplate module structure, and README templates — all conforming to current Coq community conventions. By collapsing hours of setup into a single conversational interaction, this initiative lowers the barrier to entry for newcomers and eliminates repetitive overhead for experienced developers.

**Success metrics:**
- Scaffolded projects build successfully (`dune build` or `make`) on first attempt without manual correction in >= 95% of cases
- Time from "start a new project" to "first successful build" is reduced to under 2 minutes for users invoking `/scaffold`
- Generated CI configurations pass on a clean runner without modification in >= 90% of cases
- Generated opam files pass `opam lint` without errors in >= 95% of cases
- Newcomer satisfaction surveys report that project setup is no longer a significant adoption barrier

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq newcomers starting their first project | A working project skeleton without needing to understand build system conventions, directory layout, or opam packaging | Primary |
| Experienced Coq developers starting a new project | Rapid scaffolding that follows current best practices, eliminating repetitive boilerplate setup | Primary |
| Educators and course instructors | Consistent project templates for assignments and student exercises with predictable structure | Secondary |
| Formalization teams starting a new library | Multi-library project scaffolds with correct inter-library dependencies and CI pipelines | Secondary |

---

## 3. Competitive Context

**Lean ecosystem (comparative baseline):**
- Lake provides `lake init` and `lake new`, which generate a complete project skeleton with a single command: `lakefile.lean`, `Main.lean`, a `.gitignore`, and a `lean-toolchain` file. The generated project builds immediately. Lean newcomers never struggle with project setup because Lake eliminates the problem entirely.

**Coq ecosystem (current state):**
- No official project generator exists. Developers copy from example repositories, adapt templates found in blog posts, or build configuration files from scratch by reading documentation for multiple tools.
- `coq_makefile` requires manual creation of a `_CoqProject` file. Dune requires `dune-project` and per-directory `dune` files with Coq-specific stanzas. opam requires a `.opam` file with its own format. CI configuration (GitHub Actions, GitLab CI) requires platform-specific YAML with Coq Docker images or opam setup steps. None of these tools generate the others' configuration.
- Community templates exist (e.g., `coq-community/templates`) but are static, quickly outdated, and require manual adaptation. They do not adapt to the user's specific project parameters.
- See [../background/coq-ecosystem-tooling.md](../background/coq-ecosystem-tooling.md) for detailed analysis of the Coq tooling landscape.

**Gap:** Lean's `lake init` provides a zero-configuration project start. Coq has no equivalent. This initiative provides an AI-assisted equivalent that is more capable than `lake init` because it adapts to user-specified parameters (build system choice, dependency set, CI platform) rather than producing a single fixed template.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RPS-P0-1 | Given a project name and optional parameters, generate a complete directory structure following Coq community conventions (e.g., `theories/`, `src/`, or user-specified layout) |
| RPS-P0-2 | Generate valid Dune build files (`dune-project` and per-directory `dune` files with `coq.theory` stanzas) for the scaffolded project |
| RPS-P0-3 | Generate a valid `_CoqProject` file as an alternative when the user selects `coq_makefile` as the build system |
| RPS-P0-4 | Generate a boilerplate root module (e.g., `theories/MyProject.v`) that compiles without errors |
| RPS-P0-5 | The scaffolded project must build successfully on first attempt without manual correction |
| RPS-P0-6 | Implement the workflow as a Claude Code slash command (`/scaffold`) that orchestrates existing MCP tools as building blocks |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RPS-P1-1 | Generate a valid `.opam` file with correct metadata, dependency declarations, and build instructions for the scaffolded project |
| RPS-P1-2 | Generate CI configuration for GitHub Actions that builds the project, including Coq Docker image selection and opam dependency installation |
| RPS-P1-3 | Generate a `.gitignore` file appropriate for Coq projects (excluding `*.vo`, `*.vok`, `*.vos`, `*.glob`, `_build/`, etc.) |
| RPS-P1-4 | Generate a README template with project name, description, build instructions, and dependency information |
| RPS-P1-5 | Allow the user to specify initial dependencies (e.g., MathComp, Equations) and include them in the generated build and opam files |
| RPS-P1-6 | Support generating multi-library project structures with correct inter-library dependency declarations |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RPS-P2-1 | Generate CI configuration for GitLab CI in addition to GitHub Actions |
| RPS-P2-2 | Generate a `CONTRIBUTING.md` template with project-specific build and development instructions |
| RPS-P2-3 | Generate a license file based on user-specified license choice |
| RPS-P2-4 | Generate Alectryon-compatible documentation stubs for literate documentation workflows |
| RPS-P2-5 | Offer a "minimal" vs. "full" scaffold mode, where minimal produces only the build-essential files |

---

## 5. Scope Boundaries

**In scope:**
- Generation of directory structures, build configuration files, CI configuration, opam metadata, boilerplate Coq modules, and documentation templates
- Support for both Dune and `coq_makefile` as build system targets
- GitHub Actions CI configuration generation
- Orchestration of existing Build System Integration MCP tools from within the `/scaffold` slash command
- Adaptation of generated files to user-specified parameters (project name, build system, dependencies, directory layout)

**Out of scope:**
- Generating substantive proof content or theorem statements (the scaffold produces compilable boilerplate only)
- Hosting or distributing project templates as static artifacts outside of Claude Code
- Supporting build systems other than `coq_makefile` and Dune (e.g., Nix-based builds)
- Publishing the scaffolded project to opam repositories
- Git repository initialization or remote configuration
- IDE-specific configuration files (VS Code settings, Emacs `.dir-locals.el`)
- Ongoing project maintenance after initial scaffolding (see Build System Integration for post-setup workflows)
