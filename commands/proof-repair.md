You are executing the `/proof-repair` workflow. This command automates repair of Coq proofs that broke after a version upgrade. You will build the project, diagnose each failure, apply targeted fixes, and iterate until all proofs compile or no further automatic progress can be made.

The user may provide optional arguments: a target scope (specific files or directories), and the Coq version pair (e.g., "8.18 to 8.19"). If version info is given, use it to inform diagnosis. If a scope is given, build the full project but only repair errors within the specified scope.

## Step 1: Detect the build system and run the initial build

Determine whether the project uses Dune or coq_makefile:

- Look for `dune-project` or `dune` files. If found, build with `dune build 2>&1`.
- Otherwise, look for a `Makefile` or `_CoqProject`. If found, build with `make 2>&1`.
- If neither is found, tell the user: "Could not detect a build system. This project needs a Makefile (from coq_makefile) or a dune-project file. Please configure the build system and re-run `/proof-repair`." Stop here.

Capture the full build output including all error messages. If the build succeeds with zero errors, tell the user: "The project compiles cleanly. No repairs needed." Stop here.

## Step 2: Parse and group errors

Parse each compilation error from the build output. Extract:
- File path
- Line number (and character range if available)
- The error message text
- The name of the proof or definition the error occurs in (read the file to determine this)

Group errors by file. Within each file, order errors by line number.

Determine file dependency order. Use the project's build system or scan `Require Import` / `From ... Require` statements to build a dependency graph. Sort files so that upstream files (those imported by others) are processed first. If there are circular dependencies, process those files in filesystem order.

## Step 3: Classify each error

Read the source file around each error location to understand the proof context. Classify each error into one of these categories:

**Renamed or removed lemma** — The error message contains "was not found in the current environment" or "No such entry" and the missing name looks like a lemma, theorem, or definition reference. Also covers "The reference ... was not found."

**Deprecated or removed tactic** — The error message contains "Unknown tactic", "Tactic failure", or references a tactic name that is known to have been removed or deprecated (e.g., `omega`, `romega`, `intuition` variants, `firstorder` changes).

**Type mismatch / implicit argument change** — The error message contains "has type ... while it is expected to have type" or "Unable to unify" and the types differ in ways consistent with changed implicit arguments, reordered parameters, or modified signatures.

**Universe inconsistency** — The error message mentions "Universe inconsistency" or "universe" constraints.

**Notation or parsing change** — The error message references parsing failures, notation scope changes, or syntactic issues.

**Unclassified** — Anything that does not fit the above categories. Preserve the raw error message.

## Step 4: Apply targeted repairs by category

Process files in dependency order. For each error, apply the strategy matching its classification. After applying a fix to a proof, use `open_proof_session` and `observe_proof_state` to verify the fix works before moving on.

### Renamed or removed lemma

1. Use `search_by_name` with variations of the old name (e.g., if `Nat.add_comm` is missing, search for `add_comm`, `Nat.add_comm'`, `PeanoNat.Nat.add_comm`).
2. Use `vernacular_query` with `Check` on the old name to confirm it is truly missing.
3. If the old name had a known type, use `search_by_type` or `search_by_structure` with that type signature to find candidates with the same type under a different name.
4. For each candidate, use `vernacular_query` with `Check` or `About` to verify its type is compatible with the call site.
5. Open a proof session with `open_proof_session`, navigate to the broken step, use `submit_tactic` to try the replacement, and `observe_proof_state` to confirm progress.
6. If the replacement works, apply the edit using `Edit`. Close the proof session with `close_proof_session`.
7. If no replacement is found after searching, escalate to the hammer fallback (Step 5).

### Deprecated or removed tactic

Apply known tactic replacements directly:

- `omega` -> `lia`
- `romega` -> `lia`
- `intuition` -> `intuition` (check if it needs to become `dintuition` or if the issue is a changed default solver)
- `auto with arith` -> check if the arith hint database was reorganized; try `auto with zarith` or `lia`
- `Require Import Omega` -> `Require Import Lia`

For each replacement:
1. Use `open_proof_session` and navigate to the failing tactic.
2. Use `submit_tactic` with the replacement tactic.
3. Use `observe_proof_state` to check if it made progress or closed the goal.
4. If successful, apply the edit with `Edit` and close the session.
5. If the known replacement does not work, escalate to hammer fallback (Step 5).

### Type mismatch / implicit argument change

1. Read the error carefully to identify which term has the wrong type.
2. Use `vernacular_query` with `About` on the relevant definition to inspect its current signature, particularly implicit arguments.
3. Compare with how it is used at the call site. Look for:
   - New implicit arguments that need to be provided explicitly with `@`
   - Removed implicit arguments that are now being misinterpreted as extra arguments
   - Reordered arguments
4. Open a proof session, attempt the adjusted call, and verify with `observe_proof_state`.
5. If the adjustment works, apply with `Edit`. Otherwise escalate to hammer.

### Universe inconsistency

1. Read the surrounding context to understand the universe constraint structure.
2. Try adding universe annotations or using `Set Universe Polymorphism` locally.
3. If simple adjustments do not resolve it, mark as unresolved — universe issues typically require human judgment.

### Notation or parsing change

1. Check if the notation scope or import has changed. Use `vernacular_query` with `Locate` to find the current location of notations.
2. Try adjusting `Import` or `Open Scope` statements.
3. If the notation itself was removed, rewrite the expression using the underlying definition.

### Unclassified errors

1. Read the full error context and surrounding proof.
2. Use `vernacular_query` with `Print`, `Check`, or `About` to investigate relevant definitions.
3. If the error seems related to a renamed or changed definition, treat it like a renamed lemma.
4. Otherwise, escalate to hammer fallback.

## Step 5: Hammer fallback

When targeted strategies fail for a proof goal:

1. Open a proof session with `open_proof_session` if one is not already open.
2. Navigate to the failing step. Use `step_forward` / `step_backward` and `observe_proof_state` to position at the goal that needs solving.
3. Try `submit_tactic` with `hammer.` first.
4. If `hammer` fails, try `sauto.` then `qauto.`
5. If any hammer variant succeeds, use `observe_proof_state` to confirm the goal is closed. Replace the broken tactic sequence with the successful hammer call using `Edit`. Close the session.
6. If all hammer variants fail, mark the proof as unresolved. Record which strategies were attempted. Close the session with `close_proof_session`.

## Step 6: Rebuild and iterate

After processing all errors in the current batch:

1. Rebuild the project using the same build command from Step 1.
2. Parse the new set of errors.
3. Compare against the previous set:
   - If zero errors remain, the repair is complete. Go to Step 7.
   - If the error count decreased, progress was made. Return to Step 3 with the new errors.
   - If a fix introduced a new error that was not present before, revert that fix using `Edit` (restore the original text) and mark it as a failed repair attempt.
   - If the error count did not decrease (no progress), stop iterating. Go to Step 7.

Do not exceed 10 iterations of this loop. If you reach 10 iterations without convergence, stop and go to Step 7.

## Step 7: Report results

Present a structured summary to the user:

```
## Proof Repair Report

**Summary:** X proofs broken, Y repaired, Z remaining

### Repaired Proofs
For each repaired proof:
- **File:** path/to/file.v, line N
- **Proof:** lemma_or_theorem_name
- **Error:** [original error message]
- **Fix:** [description of what was changed]
- **Strategy:** [renamed lemma / tactic migration / hammer / etc.]

### Unresolved Proofs
For each unresolved proof:
- **File:** path/to/file.v, line N
- **Proof:** lemma_or_theorem_name
- **Error:** [current error message]
- **Attempted:** [list of strategies tried and why each failed]
- **Suggestion:** [any hints for manual resolution]
```

After the report, remind the user: "All repairs should be reviewed before committing. Successful compilation does not guarantee semantic correctness — the repaired proofs may use different lemmas or strategies than intended."

## Important constraints

- Never delete proofs or admit goals. Every repair must produce a complete, valid proof or leave the original text unchanged.
- Always close proof sessions when done with them. Use `list_proof_sessions` to check for leaked sessions and close them with `close_proof_session`.
- When multiple errors occur in the same proof, fix them together in a single pass rather than one at a time.
- If the project has never compiled (not a version upgrade issue), tell the user this command is designed for version-upgrade breakages and suggest they fix compilation errors manually first.
- Keep the user informed of progress: announce which file you are processing, how many errors remain, and when each iteration of the feedback loop starts.
