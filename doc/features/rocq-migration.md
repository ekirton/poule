# Coq-to-Rocq Migration

The Coq proof assistant is being officially renamed to Rocq. This rename is rolling out across multiple releases, touching namespaces, module paths, tactic names, command names, and build system references throughout the ecosystem. Every Coq project must eventually migrate, and doing so manually is tedious and error-prone: deprecated names are scattered across dozens of files, the correct replacements are not always obvious, and a single missed rename can break the build. Coq-to-Rocq Migration provides a `/migrate-rocq` slash command that handles the entire process — scanning a project for deprecated names, suggesting replacements, applying bulk renames, and verifying the result — so users can migrate with confidence instead of grep and hope.

---

## Problem

The Coq-to-Rocq rename is not a single event — it unfolds incrementally across releases as deprecated names are phased out. Users face a compounding problem: they must track which names have been deprecated in their target version, locate every occurrence across source files and build configuration, determine the correct Rocq replacement for each, apply changes without breaking proofs, and verify correctness by building. Miss one name and the build fails. Rename a string in a comment and the diff is noisy. Forget a module path in a `From ... Require` statement and imports break silently.

Today, users rely on compiler deprecation warnings (which report one occurrence at a time during a build), community `sed` scripts (which do not understand Coq's namespace semantics and cannot distinguish identifiers from comments), or manual search-and-replace (which does not scale). None of these approaches scan a project comprehensively, suggest replacements, apply them safely, and verify the result. The migration remains a manual, file-by-file slog that discourages adoption of the new naming and leaves projects accumulating deprecation warnings.

## Solution

Coq-to-Rocq Migration lets a user point Claude at their project and say "migrate this to Rocq naming." Claude scans the codebase, identifies every deprecated Coq name, shows the user what it plans to change, and — once the user approves — applies all renames and confirms the project still builds.

### Comprehensive Scanning

The migration scans all Coq source files in a project for deprecated names that have Rocq replacements. It covers not just identifier names within proofs and definitions, but also module paths in `Require Import` and `From ... Require` statements, and references in build system files like `_CoqProject`, `dune`, and `.opam`. Users with large codebases can scope the scan to specific files or directories to migrate incrementally.

### Context-Aware Renaming

Not every occurrence of a deprecated string should be renamed. A name appearing in a comment or string literal is not a reference to the deprecated identifier. The migration distinguishes identifier references from coincidental matches, so renames are applied only where they are semantically meaningful. This avoids noisy diffs and prevents changes that would alter documentation or output strings unintentionally.

### Review Before Commit

Before any files are modified, the user sees a complete summary of every proposed change — which files, which lines, which names, and what each will become. Nothing is applied until the user confirms. This gives the user full visibility and control, especially important for large projects where hundreds of renames might be proposed.

### Build Verification

After renames are applied, the migration runs the project's build to confirm that the changes are correct. If the build succeeds, the user knows the migration is safe. If the build fails, the migration distinguishes between failures caused by the rename and pre-existing issues, so the user knows what to fix and what was already broken.

### Rollback Safety

Every change made by the migration can be reverted. If the user is unsatisfied with the result or the build fails unexpectedly, they can return to their pre-migration state without risk of lost work. The migration does not create commits automatically, so standard version control tools remain available for reviewing and reverting changes.

## Scope

Coq-to-Rocq Migration provides:

- Scanning of Coq source files for deprecated names with known Rocq replacements
- Coverage of module paths in `Require Import` and `From ... Require` statements
- Scanning of build system files (`_CoqProject`, `dune`, `.opam`) for deprecated references
- Context-aware renaming that skips comments and string literals
- Incremental migration scoped to specific files or directories
- A change summary for user review before any files are modified
- Bulk rename application across multiple files in a single operation
- Build verification after renames are applied
- Rollback of all migration changes
- A migration report suitable for commit messages or changelogs

Coq-to-Rocq Migration does not provide:

- Modifications to the Coq/Rocq compiler or standard library
- Migration of third-party plugin internals — only references to plugins are covered
- Semantic verification beyond build success (e.g., confirming that renamed lemmas have identical types)
- Support for Coq versions that predate the rename initiative
- Resolution of breaking changes unrelated to the rename, such as API or tactic behavior changes between versions
- Automatic commits — the user controls when and how changes are committed

---

## Design Rationale

### Why a slash command

The Coq-to-Rocq migration is a multi-step workflow — scan, review, apply, verify — that the user initiates with a single intent: "migrate my project." A slash command (`/migrate-rocq`) captures that intent directly and lets Claude orchestrate the steps without the user needing to invoke individual tools manually. This matches how users think about the task: not "scan for deprecated names, then suggest replacements, then apply renames, then build" but "migrate this project to Rocq."

### Why review before apply

Bulk renaming across a codebase is a high-stakes operation. A single incorrect rename can break proofs in ways that are difficult to diagnose. Requiring user confirmation before applying changes ensures that the user retains control and can catch edge cases — such as identifiers that are intentionally kept at the old name for compatibility, or names that the rename map handles incorrectly. The cost of an extra confirmation step is small; the cost of an unwanted bulk rename is large.

### Why build verification matters

Renaming identifiers in a proof assistant is not like renaming variables in a typical programming language. Coq's type system and tactic machinery mean that a rename can fail in subtle ways — a tactic that resolved a name by its old path may not find it under the new one, or a notation that depended on a specific identifier may break. The only reliable way to confirm that a migration is correct is to build the project afterward. Integrating build verification into the workflow closes the loop: the user does not need to remember to build, and failures are surfaced immediately with context about whether they are migration-related.

### Why incremental migration

Large Coq projects — especially libraries with many interdependent modules — cannot always be migrated in a single pass. Dependencies may not yet support Rocq naming, or the user may want to test changes in isolation before migrating the entire codebase. Supporting file-level and directory-level scoping lets users migrate at their own pace, tackling one module at a time and verifying each step before moving on.

### Why this is time-sensitive

The Coq-to-Rocq rename is happening now. Deprecated names are already generating compiler warnings, and future Rocq releases will remove them entirely. Every Coq user will need to migrate eventually, and the longer they wait, the more deprecated names accumulate. Providing migration tooling now — while the rename is actively unfolding — captures users at the moment of highest need and prevents the ecosystem from fragmenting between old and new naming conventions.

## Acceptance Criteria

### Deprecated Name Scanning

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project directory WHEN the `/migrate-rocq` command is invoked in scan mode THEN all `.v` files are scanned and every occurrence of a deprecated Coq name is reported with its file path, line number, and the deprecated identifier
- GIVEN a project with no deprecated names WHEN the scan completes THEN a message confirms that no deprecated names were found
- GIVEN a project with deprecated names in comments or string literals WHEN the scan completes THEN those occurrences are excluded from the results or clearly marked as non-actionable
- GIVEN a file path or directory path WHEN the scan is invoked with that path THEN only files within the specified scope are scanned
- GIVEN a directory path WHEN the scan is invoked THEN all `.v` files within that directory and its subdirectories are included
- GIVEN an invalid path WHEN the scan is invoked THEN a clear error message is returned

**Traces to:** RRM-P0-1, RRM-P0-5, RRM-P0-7

### Build System File Scanning

**Priority:** P1
**Stability:** Draft

- GIVEN a project with a `_CoqProject` file containing deprecated library paths WHEN the scan completes THEN those deprecated references are reported
- GIVEN a project using dune WHEN the scan completes THEN deprecated references in `dune` and `dune-project` files are reported
- GIVEN a project with `.opam` files WHEN the scan completes THEN deprecated package names or dependency references are reported

**Traces to:** RRM-P1-4

### Replacement Suggestion

**Priority:** P0
**Stability:** Stable

- GIVEN a scan result containing deprecated names WHEN replacements are suggested THEN each deprecated name is paired with its correct Rocq replacement
- GIVEN a deprecated name with a known replacement in the rename map WHEN the replacement is suggested THEN the suggestion matches the official Rocq rename
- GIVEN a deprecated name with no known replacement WHEN the replacement is suggested THEN the name is flagged for manual review with an explanation
- GIVEN a set of proposed renames WHEN the summary is presented THEN it lists every change grouped by file, showing the deprecated name, the replacement, and the line number
- GIVEN a summary of proposed changes WHEN the user has not confirmed THEN no files are modified
- GIVEN a summary of proposed changes WHEN the user confirms THEN the renames proceed as described in the summary

**Traces to:** RRM-P0-2, RRM-P0-3, RRM-P0-6

### Require and Import Path Changes

**Priority:** P1
**Stability:** Draft

- GIVEN a file with `From Coq Require Import Lists.List` where `Coq` is deprecated in favor of `Rocq` WHEN the replacement is suggested THEN the suggestion updates the module path to `From Rocq Require Import Lists.List`
- GIVEN a file with `Require Import Coq.Init.Datatypes` WHEN the replacement is suggested THEN the full module path is updated to use the Rocq namespace
- GIVEN a `From` clause with a path that has no direct Rocq equivalent WHEN the replacement is suggested THEN the path is flagged for manual review

**Traces to:** RRM-P1-5

### Bulk Rename Application

**Priority:** P0
**Stability:** Stable

- GIVEN a confirmed set of proposed renames spanning multiple files WHEN the renames are applied THEN every listed change is made in the corresponding file
- GIVEN a rename operation WHEN it completes THEN file structure, indentation, and formatting are preserved except for the renamed identifiers
- GIVEN a rename operation targeting a file WHEN the file contains both deprecated names and non-deprecated identical strings in comments THEN only the identifier references are renamed
- GIVEN a confirmed set of proposed renames WHEN the user specifies a subset of files THEN only those files are modified
- GIVEN a partial rename operation WHEN it completes THEN unmodified files remain untouched
- GIVEN a partial rename WHEN the modified files depend on unmodified files that still use deprecated names THEN a warning is issued about potential inconsistencies

**Traces to:** RRM-P0-4, RRM-P0-5, RRM-P0-7

### Build Verification

**Priority:** P1
**Stability:** Stable

- GIVEN a project with renames applied WHEN the build verification step runs THEN the project's build command is executed and the result (success or failure) is reported
- GIVEN a project that builds successfully after migration WHEN the build result is reported THEN a confirmation message indicates all renames are safe
- GIVEN a project that uses `_CoqProject` with `coq_makefile` WHEN the build is triggered THEN the correct build command is used
- GIVEN a project that uses dune WHEN the build is triggered THEN `dune build` is used

**Traces to:** RRM-P1-1

### Build Failure Diagnosis

**Priority:** P1
**Stability:** Draft

- GIVEN a build failure after migration WHEN the error output is analyzed THEN errors referencing renamed identifiers are classified as migration-related
- GIVEN a build failure with errors unrelated to renamed identifiers WHEN the error output is analyzed THEN those errors are classified as pre-existing or unrelated
- GIVEN a migration-related build error WHEN the diagnosis is reported THEN a suggested fix is included (e.g., a missed rename or a module path that needs updating)

**Traces to:** RRM-P1-2

### Rollback Safety

**Priority:** P1
**Stability:** Stable

- GIVEN a completed migration with applied renames WHEN the user requests a rollback THEN all modified files are restored to their pre-migration state
- GIVEN a rollback operation WHEN it completes THEN every file matches its content from before the migration was applied
- GIVEN a project under version control WHEN the migration is applied THEN the workflow does not create commits automatically, allowing the user to use `git checkout` or `git diff` to review and revert changes

**Traces to:** RRM-P1-3

### Migration Report

**Priority:** P2
**Stability:** Draft

- GIVEN a completed migration WHEN the report is generated THEN it lists every file modified, the number of renames per file, and the specific deprecated-to-Rocq name mappings applied
- GIVEN a migration report WHEN it is formatted THEN it is suitable for direct inclusion in a git commit message
- GIVEN a migration that encountered warnings or items flagged for manual review WHEN the report is generated THEN those items are listed separately

**Traces to:** RRM-P2-1
