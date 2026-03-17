Scan a Coq project for deprecated Coq-era names, suggest their Rocq replacements, apply bulk renames after user confirmation, and verify the result builds. This command modifies source files only after explicit user approval.

## Rename patterns

The Coq-to-Rocq migration follows these known rename patterns. Use these as the basis for scanning and replacement.

### Namespace prefixes

- `Coq.` module prefix becomes `Rocq.` (e.g., `Coq.Init.Datatypes` becomes `Rocq.Init.Datatypes`)
- `From Coq` in import statements becomes `From Rocq`
- `Require Import Coq.` becomes `Require Import Rocq.`
- `Require Export Coq.` becomes `Require Export Rocq.`

### Build system and package names

- `coq` becomes `rocq` in opam package names (e.g., `coq-core` becomes `rocq-core`, `coq-stdlib` becomes `rocq-stdlib`)
- `coq.` becomes `rocq.` in dune library names and public_name fields
- `-Q` and `-R` flags in `_CoqProject` that reference `Coq` paths
- `coq_makefile` references may need updating depending on the toolchain version

### Key module renames

- `Coq.Init.*` becomes `Rocq.Init.*`
- `Coq.Logic.*` becomes `Rocq.Logic.*`
- `Coq.Arith.*` becomes `Rocq.Arith.*`
- `Coq.Lists.*` becomes `Rocq.Lists.*`
- `Coq.Bool.*` becomes `Rocq.Bool.*`
- `Coq.Strings.*` becomes `Rocq.Strings.*`
- `Coq.Structures.*` becomes `Rocq.Structures.*`
- `Coq.Classes.*` becomes `Rocq.Classes.*`
- `Coq.Program.*` becomes `Rocq.Program.*`
- `Coq.ZArith.*` becomes `Rocq.ZArith.*`
- `Coq.NArith.*` becomes `Rocq.NArith.*`
- `Coq.QArith.*` becomes `Rocq.QArith.*`
- `Coq.Reals.*` becomes `Rocq.Reals.*`
- `Coq.Sets.*` becomes `Rocq.Sets.*`
- `Coq.Vectors.*` becomes `Rocq.Vectors.*`
- `Coq.Wellfounded.*` becomes `Rocq.Wellfounded.*`
- `Coq.micromega.*` becomes `Rocq.micromega.*`
- `Coq.omega.*` becomes `Rocq.omega.*`
- `Coq.ssr.*` becomes `Rocq.ssr.*`
- `Coq.derive.*` becomes `Rocq.derive.*`
- `Coq.Floats.*` becomes `Rocq.Floats.*`
- `Coq.Unicode.*` becomes `Rocq.Unicode.*`

The general rule: every standard library module under `Coq.*` has moved to `Rocq.*`. Apply the prefix replacement broadly across all `Coq.` module references.

## Step 1: Discover project files

Use Glob to find all relevant files. Run these in parallel:

- `**/*.v` — Coq source files
- `**/_CoqProject` — Coq project files
- `**/dune` — dune build files
- `**/dune-project` — dune project files
- `**/*.opam` — opam package files
- `**/Makefile` — Makefiles that may reference coq_makefile or coq paths

If no `.v` files are found, report "No Coq source files found in this project" and stop.

If the user passed a file or directory path as an argument, restrict the scan to that scope.

## Step 2: Scan for deprecated names

Use Grep to search all discovered files for deprecated names. Run these searches in parallel:

**In `.v` files:**
- `\bFrom\s+Coq\b` — From Coq import statements
- `\bRequire\s+(Import|Export)\s+Coq\.` — Require Import/Export of Coq modules
- `\bCoq\.\w+` — qualified references to Coq namespace modules (e.g., `Coq.Init.Datatypes`)

**In build system files (`_CoqProject`, `dune`, `dune-project`, `.opam`, `Makefile`):**
- `\bcoq\b` (case-sensitive) — package name references
- `\bCoq\b` — namespace references in build configuration
- `coq-\w+` — coq-prefixed package names (e.g., `coq-core`, `coq-stdlib`)

Use output_mode "content" with `-n` for line numbers.

## Step 3: Filter out false positives

Review each match to eliminate false positives before presenting results:

- **Comments:** Discard matches inside Coq comments `(* ... *)`. Check whether the match falls between an opening `(*` and closing `*)`. Multiline comments require reading surrounding context.
- **String literals:** Discard matches inside double-quoted strings unless the string is itself a module path used programmatically.
- **User-defined names:** If an identifier like `CoqHammer` or `coq_tactics` is a user-defined name (not a standard library reference), do not propose renaming it.
- **Documentation references:** Matches in comments that refer to the Coq project by name (e.g., "This module implements..." or "See the Coq manual") are non-actionable. Exclude them from the rename plan but note them separately if there are many.
- **Already-migrated names:** If `Rocq.` equivalents are already present alongside `Coq.` references, note this but do not propose redundant changes.

For ambiguous cases, use `vernacular_query` with `Locate` to check whether a name resolves in the current environment, which can confirm whether a `Coq.*` reference is a real module path.

## Step 4: Present findings

Present results grouped by file. For each file, list:

- The file path
- Each deprecated reference with its line number
- The proposed replacement

Format example:

```
src/Sorting.v:
  Line 3:  From Coq Require Import Lists.List     -->  From Rocq Require Import Lists.List
  Line 7:  Require Import Coq.Arith.PeanoNat       -->  Require Import Rocq.Arith.PeanoNat
  Line 45: Coq.Init.Datatypes.nat                  -->  Rocq.Init.Datatypes.nat

_CoqProject:
  Line 2:  -Q . Coq.MyLib                          -->  (flag for manual review — user namespace)
```

After the per-file listing, print a summary:

- Total files with deprecated names
- Total renames proposed
- Any items flagged for manual review (with reasons)

Then ask the user: "Apply these renames? (yes / no / select specific files)"

Do NOT proceed until the user confirms. If the user says no, stop. If the user selects specific files, apply only to those files.

## Step 5: Apply renames

After user confirmation, apply renames using the Edit tool. For each file with proposed changes:

1. Read the file to get current content.
2. Apply each rename using Edit with the exact old and new strings. Use `replace_all` when the same substitution applies to multiple occurrences in a file (e.g., replacing `From Coq` with `From Rocq`).
3. For `From Coq` and `Require Import Coq.` patterns, replace at the statement level to preserve surrounding syntax.
4. Do not modify lines that were flagged for manual review unless the user explicitly approved them.

Process files one at a time. Report each file as it is updated.

## Step 6: Verify build

After all renames are applied, run the project build to verify correctness.

Detect the build system:
- If a `dune-project` or `dune` file exists at the project root, run `dune build` via Bash.
- If a `_CoqProject` file exists, run `make` via Bash (which uses the Makefile generated by `coq_makefile`).
- If neither is found, ask the user for the build command.

Set a timeout of 5 minutes (300000ms) for the build.

## Step 7: Handle build result

**If the build succeeds:**
Report success and proceed to Step 8.

**If the build fails:**
1. Read the build error output.
2. Classify each error:
   - **Migration-related:** The error references a renamed identifier, a missing module path, or an unresolved name that corresponds to a rename applied in Step 5. These indicate a rename was incomplete or incorrect.
   - **Pre-existing:** The error references code or identifiers not touched by the migration. These were broken before the migration started.
3. For migration-related errors, suggest specific fixes (e.g., a missed rename, a module path that needs a different mapping).
4. Ask the user how to proceed:
   - "Fix" — apply the suggested fixes, then re-run the build
   - "Rollback" — revert all migration changes using `git checkout -- <files>` for each modified file
   - "Continue" — leave the current state for the user to fix manually

If the user chooses rollback, restore every file modified in Step 5 using `git checkout -- <filepath>` for each file. Confirm all files have been restored.

## Step 8: Report summary

Produce a final migration report with the following sections:

**Migration Summary**
- Files scanned: (count)
- Files modified: (count)
- Total renames applied: (count)
- Build status: success / failed (with error count)

**Changes by file**
List each modified file with the count of renames applied.

**Renames applied**
List the unique deprecated-to-Rocq mappings that were used (deduplicated), e.g.:
- `From Coq` --> `From Rocq` (applied N times)
- `Require Import Coq.` --> `Require Import Rocq.` (applied N times)

**Manual review items**
List any items that were flagged for manual review and not auto-renamed.

**Notes**
Include any observations relevant to the migration (e.g., "3 files still reference coq-stdlib in opam dependencies — update these when the upstream package is renamed").

Format this report so it can be used directly in a git commit message if the user wants.

## Edge cases

- **Mixed Coq and Rocq references:** A file may already have some Rocq references (partial prior migration). Only rename the remaining Coq references. Do not duplicate already-migrated names.
- **User namespaces starting with Coq:** If a project defines its own namespace starting with `Coq` (e.g., `Coq.MyProject.Utils`), flag this for manual review. Do not auto-rename user namespaces — only standard library references.
- **Third-party dependencies:** If `From Coq` references resolve to third-party libraries (not the standard library), flag them for manual review. The third-party library may not have migrated yet.
- **Large projects (>100 `.v` files):** Process all files but present the summary in condensed form. Group files by directory instead of listing every line-level change. Still require confirmation before applying.
- **No deprecated names found:** Report "No deprecated Coq names found — this project already uses Rocq naming or does not reference the standard library" and stop.
- **Vernacular commands using old names:** Some vernacular commands may embed Coq module paths (e.g., `Set Printing Coq Compat`). Flag these for manual review since they may be version-specific settings rather than namespace references.
