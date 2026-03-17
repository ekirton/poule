# Cross-Library Compatibility Analysis — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context.

## 1. Business Goals

Dependency incompatibility is one of the most frequently cited pain points among Coq/Rocq project maintainers. When a project declares multiple library dependencies, each with its own constraints on the Coq version, OCaml version, and transitive dependencies, version conflicts are common. Today, these conflicts surface only when `opam install` fails — producing opaque solver output that most users cannot interpret. The feedback loop is slow: the user edits a constraint, re-runs the solver, waits, and reads another wall of diagnostic text. Many users resort to trial-and-error or abandon dependencies entirely.

This initiative provides a proactive compatibility analysis workflow, implemented as a Claude Code slash command (`/check-compat`), that detects version conflicts before the user hits build failures. The workflow orchestrates opam metadata queries, interprets Coq version constraint semantics, and explains conflicts in plain language with actionable resolution paths. By shifting conflict detection from build time to planning time, this initiative eliminates one of the most time-consuming and discouraging aspects of Coq project maintenance.

**Success metrics:**
- Correctly identifies all mutually incompatible dependency pairs in >= 90% of analyzed projects
- Provides a plain-language explanation for each detected conflict in 100% of reported cases
- Reduces average time from "add a dependency" to "working build" by >= 50% compared to manual opam constraint debugging
- Users report that conflict explanations are actionable (i.e., they understand what to change) in >= 85% of cases
- False positive rate (reporting a conflict where none exists) is < 10%

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq project maintainers managing multiple dependencies | Proactive detection of version conflicts before attempting installation; clear explanation of which constraints clash and why | Primary |
| Coq developers adding a new library dependency | Verification that the new dependency is compatible with existing dependencies and the current Coq version before committing to it | Primary |
| Coq library authors preparing a release | Confidence that declared dependency constraints are satisfiable and do not exclude common dependency combinations | Secondary |
| Coq newcomers setting up their first multi-library project | Guidance through the opam constraint landscape without needing to understand solver internals | Secondary |

---

## 3. Competitive Context

**Lean ecosystem (comparative baseline):**
- Lake manages dependencies declaratively in `lakefile.lean` and resolves them at build time. Version conflicts are rare in practice because Lake fetches dependencies from Git with explicit commit hashes, avoiding the constraint-solving problem entirely. When conflicts do occur, Lake's error messages are relatively clear.

**Coq ecosystem (current state):**
- opam is the sole dependency manager. It uses a SAT-based constraint solver that is powerful but produces diagnostic output designed for package manager developers, not end users. When the solver fails, the output lists unsatisfied constraints in a format that requires familiarity with opam's internal representation.
- No existing tool provides pre-installation compatibility checking with plain-language explanations. Users must attempt `opam install`, wait for solver failure, and interpret the output manually.
- The Coq Platform project maintains a curated set of compatible package versions, but it covers only a subset of the ecosystem and does not help users working outside that set.

**Gap:** There is no tool — in the Coq ecosystem or any other proof assistant ecosystem — that proactively analyzes a project's declared dependencies for mutual compatibility and explains conflicts in plain language. This is a workflow that requires combining opam metadata queries, Coq version constraint interpretation, and natural language explanation — exactly the kind of multi-step, interpretive task that an agentic workflow excels at.

See also: [doc/requirements/build-system-integration.md](build-system-integration.md) for the underlying opam MCP tools that this workflow builds upon.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RCA-P0-1 | Given a Coq project with declared dependencies (in `.opam`, `dune-project`, or `_CoqProject` with opam metadata), extract the complete list of direct dependencies and their version constraints |
| RCA-P0-2 | For each declared dependency, query opam metadata to determine the dependency's own constraints on Coq version, OCaml version, and transitive dependencies |
| RCA-P0-3 | Determine whether the full set of declared dependencies (direct and transitive) has a satisfiable solution given the available package versions |
| RCA-P0-4 | When a conflict is detected, identify the specific packages and version constraints that are mutually incompatible |
| RCA-P0-5 | For each detected conflict, provide a plain-language explanation of why the constraints are incompatible, naming the packages, the conflicting constraints, and the resource (e.g., Coq version) they disagree on |
| RCA-P0-6 | Generate a summary report listing all detected conflicts, all compatible dependency pairs, and an overall compatibility verdict (compatible / incompatible) |
| RCA-P0-7 | When no conflicts are detected, confirm compatibility and report the solution space (e.g., the range of Coq versions that satisfy all constraints) |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RCA-P1-1 | For each detected conflict, suggest at least one resolution strategy (e.g., upgrade package A, downgrade package B, use an alternative package, relax a constraint) |
| RCA-P1-2 | Check compatibility against a specific target Coq version supplied by the user, not just the currently installed version |
| RCA-P1-3 | Detect and report when a declared dependency is not available in any configured opam repository |
| RCA-P1-4 | Support analysis of hypothetical dependency additions (e.g., "would adding coq-equations be compatible with my current dependencies?") without modifying project files |
| RCA-P1-5 | Report the newest mutually compatible version of each dependency, enabling users to maximize version freshness within compatibility constraints |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RCA-P2-1 | Visualize the dependency constraint graph, showing which packages constrain which shared resources and where conflicts arise |
| RCA-P2-2 | Compare compatibility across multiple Coq versions (e.g., "are my dependencies compatible with both Coq 8.18 and 8.19?") |
| RCA-P2-3 | Suggest the minimal set of constraint changes needed to make an incompatible dependency set satisfiable |
| RCA-P2-4 | Cache opam metadata across invocations to reduce query latency for repeated analyses |

---

## 5. Scope Boundaries

**In scope:**
- Extraction of dependency declarations from `.opam`, `dune-project`, and `_CoqProject` files
- Querying opam metadata for package version constraints and transitive dependencies
- Constraint satisfiability analysis across all declared dependencies
- Plain-language conflict explanation and compatibility reporting
- Resolution suggestions for detected conflicts
- Hypothetical dependency addition analysis
- Implementation as a Claude Code slash command (`/check-compat`) orchestrating MCP tools from the build system integration initiative

**Out of scope:**
- Modifying opam, the opam solver, or opam repository infrastructure
- Automatically applying fixes to project dependency files (the workflow reports and suggests; the user decides)
- Dependency resolution for non-opam package managers (Nix, esy, manual builds)
- Analysis of build-time failures unrelated to version constraints (e.g., missing C libraries, compiler flags)
- Managing opam switches or opam repository configuration
- Runtime compatibility testing (e.g., whether two libraries' APIs compose correctly beyond version constraints)
- Publishing packages or modifying the opam repository
