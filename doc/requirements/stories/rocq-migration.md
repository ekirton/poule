# User Stories: Coq-to-Rocq Migration

Derived from [doc/requirements/rocq-migration.md](../rocq-migration.md).

---

## Epic 1: Deprecated Name Scanning

### 1.1 Scan Project for Deprecated Coq Names

**As a** Coq developer migrating to Rocq,
**I want to** scan my entire project for uses of deprecated Coq names,
**so that** I know the full scope of changes needed before I start renaming.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq project directory WHEN the `/migrate-rocq` command is invoked in scan mode THEN all `.v` files are scanned and every occurrence of a deprecated Coq name is reported with its file path, line number, and the deprecated identifier
- GIVEN a project with no deprecated names WHEN the scan completes THEN a message confirms that no deprecated names were found
- GIVEN a project with deprecated names in comments or string literals WHEN the scan completes THEN those occurrences are excluded from the results or clearly marked as non-actionable

**Traces to:** RRM-P0-1, RRM-P0-5

### 1.2 Scan Specific Files or Directories

**As a** library maintainer with a large codebase,
**I want to** scan only specific files or subdirectories rather than the entire project,
**so that** I can migrate incrementally without being overwhelmed by the full scope.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a file path or directory path WHEN the scan is invoked with that path THEN only files within the specified scope are scanned
- GIVEN a directory path WHEN the scan is invoked THEN all `.v` files within that directory and its subdirectories are included
- GIVEN an invalid path WHEN the scan is invoked THEN a clear error message is returned

**Traces to:** RRM-P0-7

### 1.3 Scan Build System Files

**As a** Coq developer migrating to Rocq,
**I want** the scan to also check build system files (`_CoqProject`, `dune`, `.opam`) for deprecated references,
**so that** my build configuration is updated alongside my source code.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a project with a `_CoqProject` file containing deprecated library paths WHEN the scan completes THEN those deprecated references are reported
- GIVEN a project using dune WHEN the scan completes THEN deprecated references in `dune` and `dune-project` files are reported
- GIVEN a project with `.opam` files WHEN the scan completes THEN deprecated package names or dependency references are reported

**Traces to:** RRM-P1-4

---

## Epic 2: Replacement Suggestion

### 2.1 Suggest Rocq Replacements for Deprecated Names

**As a** Coq developer migrating to Rocq,
**I want to** see the correct Rocq replacement for each deprecated name found in my project,
**so that** I can understand what each name will be changed to before any modifications are made.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a scan result containing deprecated names WHEN replacements are suggested THEN each deprecated name is paired with its correct Rocq replacement
- GIVEN a deprecated name with a known replacement in the rename map WHEN the replacement is suggested THEN the suggestion matches the official Rocq rename
- GIVEN a deprecated name with no known replacement WHEN the replacement is suggested THEN the name is flagged for manual review with an explanation

**Traces to:** RRM-P0-2, RRM-P0-3

### 2.2 Present Change Summary Before Applying

**As a** Coq developer migrating to Rocq,
**I want to** review a summary of all proposed changes before they are applied,
**so that** I can verify the plan and catch any issues before my files are modified.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a set of proposed renames WHEN the summary is presented THEN it lists every change grouped by file, showing the deprecated name, the replacement, and the line number
- GIVEN a summary of proposed changes WHEN the user has not confirmed THEN no files are modified
- GIVEN a summary of proposed changes WHEN the user confirms THEN the renames proceed as described in the summary

**Traces to:** RRM-P0-6

### 2.3 Handle Require and Import Path Changes

**As a** Coq developer migrating to Rocq,
**I want** the migration to update `Require Import` and `From ... Require` paths that reference deprecated module names,
**so that** my import statements reflect the new Rocq namespace structure.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a file with `From Coq Require Import Lists.List` where `Coq` is deprecated in favor of `Rocq` WHEN the replacement is suggested THEN the suggestion updates the module path to `From Rocq Require Import Lists.List`
- GIVEN a file with `Require Import Coq.Init.Datatypes` WHEN the replacement is suggested THEN the full module path is updated to use the Rocq namespace
- GIVEN a `From` clause with a path that has no direct Rocq equivalent WHEN the replacement is suggested THEN the path is flagged for manual review

**Traces to:** RRM-P1-5

---

## Epic 3: Bulk Rename Application

### 3.1 Apply Bulk Renames Across Multiple Files

**As a** Coq developer migrating to Rocq,
**I want to** apply all approved renames across my project in a single operation,
**so that** I do not have to manually edit each file one at a time.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a confirmed set of proposed renames spanning multiple files WHEN the renames are applied THEN every listed change is made in the corresponding file
- GIVEN a rename operation WHEN it completes THEN file structure, indentation, and formatting are preserved except for the renamed identifiers
- GIVEN a rename operation targeting a file WHEN the file contains both deprecated names and non-deprecated identical strings in comments THEN only the identifier references are renamed

**Traces to:** RRM-P0-4, RRM-P0-5

### 3.2 Apply Renames to a Subset of Files

**As a** library maintainer with a large codebase,
**I want to** apply renames to only a subset of files or directories,
**so that** I can migrate incrementally and test changes in isolation.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a confirmed set of proposed renames WHEN the user specifies a subset of files THEN only those files are modified
- GIVEN a partial rename operation WHEN it completes THEN unmodified files remain untouched
- GIVEN a partial rename WHEN the modified files depend on unmodified files that still use deprecated names THEN a warning is issued about potential inconsistencies

**Traces to:** RRM-P0-7

---

## Epic 4: Build Verification

### 4.1 Run Build After Migration

**As a** Coq developer migrating to Rocq,
**I want** the migration workflow to automatically build my project after renames are applied,
**so that** I have immediate confirmation that the migration did not break anything.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a project with renames applied WHEN the build verification step runs THEN the project's build command is executed and the result (success or failure) is reported
- GIVEN a project that builds successfully after migration WHEN the build result is reported THEN a confirmation message indicates all renames are safe
- GIVEN a project that uses `_CoqProject` with `coq_makefile` WHEN the build is triggered THEN the correct build command is used
- GIVEN a project that uses dune WHEN the build is triggered THEN `dune build` is used

**Traces to:** RRM-P1-1

### 4.2 Diagnose Build Failures After Migration

**As a** Coq developer migrating to Rocq,
**I want** the workflow to parse build errors after a failed migration build and tell me whether the failure is due to the migration,
**so that** I can distinguish migration issues from pre-existing problems.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a build failure after migration WHEN the error output is analyzed THEN errors referencing renamed identifiers are classified as migration-related
- GIVEN a build failure with errors unrelated to renamed identifiers WHEN the error output is analyzed THEN those errors are classified as pre-existing or unrelated
- GIVEN a migration-related build error WHEN the diagnosis is reported THEN a suggested fix is included (e.g., a missed rename or a module path that needs updating)

**Traces to:** RRM-P1-2

---

## Epic 5: Rollback Safety

### 5.1 Rollback All Migration Changes

**As a** Coq developer migrating to Rocq,
**I want to** revert all changes made by the migration workflow if the result is unsatisfactory or the build fails,
**so that** I can return to my original state without risk of data loss.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a completed migration with applied renames WHEN the user requests a rollback THEN all modified files are restored to their pre-migration state
- GIVEN a rollback operation WHEN it completes THEN every file matches its content from before the migration was applied
- GIVEN a project under version control WHEN the migration is applied THEN the workflow does not create commits automatically, allowing the user to use `git checkout` or `git diff` to review and revert changes

**Traces to:** RRM-P1-3

### 5.2 Generate Migration Report

**As a** Coq developer migrating to Rocq,
**I want** a summary report of all changes made during the migration,
**so that** I can include it in a commit message, changelog, or review request.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a completed migration WHEN the report is generated THEN it lists every file modified, the number of renames per file, and the specific deprecated-to-Rocq name mappings applied
- GIVEN a migration report WHEN it is formatted THEN it is suitable for direct inclusion in a git commit message
- GIVEN a migration that encountered warnings or items flagged for manual review WHEN the report is generated THEN those items are listed separately

**Traces to:** RRM-P2-1
