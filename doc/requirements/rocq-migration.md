# Coq-to-Rocq Migration — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context (section 4, "Agentic Workflows with No IDE Equivalent").

## 1. Business Goals

The Coq proof assistant is undergoing an official rename to Rocq. This rename touches namespaces, module paths, tactic names, command names, and build system references across the entire ecosystem. Every Coq project must eventually migrate, and the migration is not a one-time event — it unfolds across multiple Coq/Rocq releases as deprecated names are phased out incrementally. Users face a tedious, error-prone process: identifying deprecated names scattered across dozens of files, determining the correct replacement for each, applying bulk renames without breaking proofs, and verifying that the project still builds after changes.

No IDE can automate this end-to-end. The task requires pattern matching over a large and evolving rename map, safe multi-file refactoring that respects Coq's namespace semantics, and build verification to confirm correctness. This is a compound, multi-step workflow that demands tool orchestration, intermediate reasoning, and adaptive strategy — exactly what an agentic workflow delivers.

This initiative provides a Claude Code slash command (`/migrate-rocq`) that scans a project for deprecated Coq names, suggests Rocq replacements, applies bulk renames across files, and verifies the result by running the build. Users state their intent ("migrate this project to Rocq naming") and Claude handles the rest.

**Success metrics:**
- 95% or more of deprecated Coq names in a scanned project are correctly identified and mapped to their Rocq replacements
- Bulk renames applied by the workflow produce a project that builds successfully without manual fixups in 80% or more of migrations
- Migration time for a typical project (< 50 files) is reduced by at least 5x compared to manual search-and-replace
- Zero instances of silent semantic breakage: every rename is verified by a successful build or flagged for manual review
- Users can complete a full migration without consulting external rename tables or migration guides

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers migrating to Rocq | Automated identification and replacement of deprecated names across their projects, with confidence that the result is correct | Primary |
| Library maintainers | Bulk migration of large codebases with many files and cross-module dependencies, with minimal manual intervention | Primary |
| Formalization teams | Coordinated migration across multiple interdependent packages, ensuring consistency | Secondary |
| Coq newcomers | Guidance on which names are deprecated and what the current Rocq equivalents are, even outside a full migration workflow | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Coq ecosystem tooling survey](../background/coq-ecosystem-tooling.md)
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)

**Current migration tooling:**
- The Rocq project provides deprecation warnings in the compiler output when deprecated names are used, but users must manually interpret these warnings and apply fixes one at a time.
- Some community scripts exist for specific rename batches (e.g., `sed`-based bulk replacement), but these are fragile: they do not understand Coq's namespace semantics, they cannot distinguish identifiers from string literals or comments, and they do not verify correctness after renaming.
- No existing tool provides end-to-end migration: scan, suggest, apply, and verify in a single workflow.

**Why an agentic workflow is required:**
- The rename map evolves across releases. A static tool requires manual updates; an LLM-driven workflow can interpret deprecation warnings dynamically and adapt to new renames.
- Safe multi-file refactoring requires understanding which occurrences of a name are references to the deprecated identifier versus coincidental string matches. This requires contextual reasoning.
- Build verification after rename is essential but no existing migration tool integrates it. The agentic workflow orchestrates the rename, runs the build, interprets errors, and iterates if needed.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RRM-P0-1 | Scan all Coq source files (`.v`) in a project and identify uses of deprecated Coq names that have Rocq replacements |
| RRM-P0-2 | Maintain or reference a rename map that covers the official Coq-to-Rocq namespace changes across supported Coq/Rocq versions |
| RRM-P0-3 | For each deprecated name found, suggest the correct Rocq replacement |
| RRM-P0-4 | Apply bulk renames across multiple files in a single operation, preserving file structure and formatting |
| RRM-P0-5 | Distinguish between identifier references and coincidental string matches (e.g., names appearing in comments or string literals) to avoid incorrect renames |
| RRM-P0-6 | Present a summary of all proposed changes before applying them, so the user can review before committing |
| RRM-P0-7 | Support incremental migration: allow the user to migrate specific files or directories rather than the entire project |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RRM-P1-1 | After applying renames, run the project build and report whether it succeeds or fails |
| RRM-P1-2 | When the build fails after renaming, parse the error output and attempt to diagnose whether the failure is due to the migration or a pre-existing issue |
| RRM-P1-3 | Support rollback: revert all changes made by the migration if the user is not satisfied with the result or the build fails |
| RRM-P1-4 | Detect deprecated names in build system files (`_CoqProject`, `dune` files, `.opam` files) in addition to source files |
| RRM-P1-5 | Handle renames that require changes to `Require Import` and `From ... Require` paths, not just identifier names |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RRM-P2-1 | Generate a migration report summarizing all changes made, organized by file, suitable for inclusion in a commit message or changelog |
| RRM-P2-2 | Detect and warn about custom notations or tactics that shadow deprecated names, which may require manual attention |
| RRM-P2-3 | Support migration of Coq plugin references and configuration files beyond the core source and build files |

---

## 5. Scope Boundaries

**In scope:**
- Scanning Coq source files for deprecated names
- Mapping deprecated Coq names to Rocq replacements
- Bulk rename application across multiple files
- Contextual filtering to avoid renaming names in comments or strings
- Pre-rename summary and user confirmation
- Build verification after rename
- Rollback of applied changes
- Incremental (per-file or per-directory) migration
- Detection of deprecated names in build system files

**Out of scope:**
- Modifications to the Coq/Rocq compiler or standard library
- Migration of third-party plugin internals (only references to plugins are in scope)
- Semantic analysis of proof correctness beyond build verification (e.g., checking that renamed lemmas have identical types)
- Support for Coq versions that predate the rename initiative
- Automatic resolution of breaking changes unrelated to the rename (e.g., API changes, tactic behavior changes between versions)
- IDE plugin development
