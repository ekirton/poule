# Proof Repair on Version Upgrade

Upgrading Coq versions is one of the most painful recurring tasks in the ecosystem. Between major releases, lemmas are renamed, tactics are deprecated, type inference changes, and implicit argument defaults shift — breaking dozens to hundreds of proofs across a project. Developers spend days to weeks on manual repair, and some projects simply stop upgrading. Proof Repair on Version Upgrade delivers a `/proof-repair` slash command that automates the core upgrade repair loop: build the project, diagnose what broke, find replacements, attempt fixes, and retry — iterating until all proofs compile or a clear report tells the user exactly where human judgment is needed.

---

## Problem

When a Coq project upgrades to a new version of the compiler, proofs break for reasons that are mechanical but tedious to fix. A lemma the proof relied on has been renamed. A tactic it used has been deprecated or removed. A type signature changed in a way that shifts implicit arguments. Each broken proof requires the developer to read the error, consult the changelog, search the standard library for the replacement name, try a fix, rebuild, and see if it worked — then repeat for the next proof. Multiply this across a large formalization and the cost becomes prohibitive.

No existing tool automates this process. The Coq changelog documents breaking changes, but applying them is entirely manual. CoqHammer can sometimes re-prove goals that broke due to minor changes, but someone must manually identify each broken goal and invoke it. Community migration guides provide rename maps but require manual application. The result is that version upgrades are a leading cause of project abandonment in the Coq ecosystem.

## Solution

The `/proof-repair` command takes a Coq project that fails to compile after a version upgrade and works through the breakages systematically. The user invokes the command, optionally specifying the target Coq version, and the workflow handles the rest — building the project, diagnosing each failure, attempting the appropriate fix, and repeating until it converges.

### Error Diagnosis

The workflow begins by building the project and capturing every compilation error along with its location and surrounding proof context. Each error is classified by its likely cause: a renamed lemma, a removed or deprecated tactic, a changed type signature, an implicit argument shift, or something else entirely. This classification determines which repair strategy is applied. When the user specifies the Coq version pair (e.g., 8.18 to 8.19), the workflow consults version-specific migration knowledge to make more precise diagnoses.

### Targeted Repair Strategies

Different categories of breakage call for different fixes. When a lemma has been renamed, the workflow searches for the replacement by name similarity and type signature, verifying that the candidate has a compatible type before substituting it. When a tactic has been deprecated, the workflow applies the known replacement (e.g., `omega` becomes `lia`). When implicit arguments have changed, the workflow inspects the old and new signatures and adjusts call sites accordingly. Each strategy is matched to the error category so that simple, high-confidence fixes are applied first.

### Automated Re-Proving as Fallback

Some proof breakages resist targeted fixes — the change is too subtle, the replacement is not a simple rename, or the proof strategy itself needs to change. For these cases, the workflow falls back to CoqHammer, attempting to re-prove the goal from scratch using automated theorem proving. If the goal is within reach of automation, the user gets a working proof without having to understand what changed.

### Iterative Feedback Loop

Proof repair is not a single pass. Fixing one file can resolve cascading errors in files that depend on it, and a fix attempt that seemed correct might introduce new problems. The workflow rebuilds the project after each batch of fixes, re-diagnoses remaining errors, and iterates. It processes files in dependency order so that upstream fixes eliminate downstream cascading failures naturally. The loop continues as long as progress is being made, and stops when all proofs compile or no further automatic fixes succeed.

### Repair Report

At the end of the process, the user receives a structured report. For each automatically repaired proof, the report shows what was broken, what fix was applied, and the diff. For each proof that could not be repaired, the report shows the current error, every strategy that was attempted, and why each failed. The user can focus manual effort precisely where it is needed rather than wading through hundreds of errors to find the ones that actually require human judgment.

## Scope

Proof Repair on Version Upgrade provides:

- A `/proof-repair` slash command that orchestrates the full repair loop
- Build error capture and classification by cause (renamed lemma, deprecated tactic, changed signature, implicit argument shift)
- Automated search for replacement lemmas by name and type signature
- Application of known tactic migrations across Coq version pairs
- CoqHammer fallback for goals that resist targeted fixes
- Iterative build-diagnose-fix-rebuild loop with convergence detection
- Dependency-ordered processing so upstream fixes resolve downstream cascading errors
- A structured report of repair outcomes with diffs for user review
- Support for `coq_makefile` and Dune build systems
- Partial repair mode for targeting a subset of files or directories
- Real-time progress display during the repair process

Proof Repair on Version Upgrade does not provide:

- Repair of errors unrelated to version upgrades (e.g., logic errors in new developments)
- Modifications to the Coq compiler or its error reporting
- A standalone tool outside the Claude Code environment
- Correctness guarantees beyond successful compilation — the user must review all changes
- Support for proof assistants other than Coq (Lean, Isabelle, Agda)
- Handling of OCaml plugin API changes or Coq plugin compatibility
- Automation of opam switch creation or Coq installation

---

## Design Rationale

### Why a slash command rather than individual tool calls

Version-upgrade repair is inherently a multi-step, multi-tool workflow: build the project, parse errors, search for replacements, interact with proofs, invoke hammer, rebuild. Asking the user to manually orchestrate these steps defeats the purpose — the whole point is to automate the tedious loop. A slash command lets the user express a single intent ("repair my project after this upgrade") and have the workflow manage the orchestration, tool selection, and iteration internally. The individual MCP tools remain available for users who want fine-grained control over a specific proof, but the common case of "fix everything that broke" should be a single action.

### Why classify errors before attempting repairs

Not all version-upgrade breakages are the same, and applying the wrong repair strategy wastes time and can introduce new errors. A renamed lemma calls for a search-and-replace. A deprecated tactic calls for a known substitution. A changed type signature might require adjusting implicit arguments. Attempting CoqHammer on a renamed-lemma error is wasteful when a simple name substitution would work in seconds. Classification lets the workflow apply the cheapest, highest-confidence fix first and reserve expensive strategies like automated re-proving for cases that genuinely need them.

### Why iterate rather than fix everything in one pass

Coq projects have deep dependency chains. An error in an early file can cause dozens of cascading errors in files that import it. Attempting to fix every error in a single pass would waste effort on errors that are mere symptoms rather than root causes. By rebuilding after each batch of fixes and re-diagnosing, the workflow discovers which errors were cascading consequences that resolved on their own, and which are independent breakages that need their own repairs. This also provides a natural convergence check: if an iteration makes no progress, the workflow knows to stop.

### Why process files in dependency order

When file B imports file A, errors in B may be caused by unfixed errors in A rather than by anything wrong in B itself. Processing files in dependency order — upstream first — ensures that cascading errors are eliminated at their source. This avoids wasted repair attempts on symptoms that disappear once the root cause is fixed, and reduces the total number of iterations the feedback loop needs to converge.

### Why fall back to CoqHammer

Some version-upgrade breakages are not simple renames or tactic substitutions. A proof strategy that worked in one version may fail in the next because of subtle changes to unification, type inference, or reduction behavior. In these cases, the most effective approach is often to re-prove the goal from scratch using automation. CoqHammer covers a large fraction of first-order goals and can frequently find alternative proofs that work under the new version's semantics, even when the original proof strategy no longer applies.

## Acceptance Criteria

### Build Error Detection and Classification

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project that compiled under Coq 8.18 but fails under Coq 8.19 WHEN `/proof-repair` is invoked THEN the command runs the project's build system and captures every compilation error with its source file path, line number, and the error message
- GIVEN a project using `coq_makefile` WHEN `/proof-repair` is invoked THEN the build is executed via the Makefile generated by `coq_makefile`
- GIVEN a project using Dune WHEN `/proof-repair` is invoked THEN the build is executed via `dune build`
- GIVEN a project with errors in multiple files WHEN the build errors are captured THEN errors are grouped by file and ordered by their position within each file
- GIVEN a build error containing "The reference X was not found in the current environment" WHEN classification is performed THEN the error is classified as a renamed-or-removed-lemma error
- GIVEN a build error containing "Unknown tactic" or "Tactic failure" for a tactic that existed in the previous version WHEN classification is performed THEN the error is classified as a deprecated-tactic error
- GIVEN a build error containing "The term has type X while it is expected to have type Y" where X and Y differ only in implicit arguments WHEN classification is performed THEN the error is classified as an implicit-argument-change error
- GIVEN a build error that does not match any known pattern WHEN classification is performed THEN the error is classified as unclassified with the raw error message preserved

**Traces to:** RPR-P0-1, RPR-P0-2, RPR-P0-9, RPR-P0-10

### Renamed Lemma Search and Replacement

**Priority:** P0
**Stability:** Stable

- GIVEN a renamed-lemma error referencing `Nat.add_comm` (removed in the hypothetical new version) WHEN a replacement search is performed THEN the search queries semantic lemma search with the old name and the expected type signature and returns candidate replacements ranked by relevance
- GIVEN a renamed lemma where the new name exists in the same module with the same type WHEN the search is performed THEN the correct replacement is ranked first among candidates
- GIVEN a renamed lemma where no replacement exists with a compatible type WHEN the search is performed THEN the search reports that no suitable replacement was found

**Traces to:** RPR-P0-3

### Lemma Substitution Verification

**Priority:** P1
**Stability:** Stable

- GIVEN a candidate replacement lemma WHEN verification is performed THEN the type of the replacement is compared against the expected type at the call site using vernacular introspection (`Check`, `About`)
- GIVEN a verified replacement with a compatible type WHEN the substitution is applied THEN the old lemma name is replaced with the new name in the proof script
- GIVEN a candidate replacement whose type is incompatible with the call site WHEN verification is performed THEN the candidate is rejected and the next candidate is tried

**Traces to:** RPR-P0-3, RPR-P1-7

### Deprecated Tactic and Migration Pattern Fixes

**Priority:** P0
**Stability:** Stable

- GIVEN a proof that uses the `omega` tactic and targets a Coq version where `omega` was removed WHEN the repair workflow processes this error THEN `omega` is replaced with `lia` in the proof script
- GIVEN a proof that uses a deprecated tactic with a known replacement WHEN the tactic migration is applied THEN the replacement tactic is syntactically valid in the target Coq version
- GIVEN a deprecated tactic with no known direct replacement WHEN the repair workflow processes this error THEN the error is escalated to the hammer fallback strategy rather than left unaddressed

**Traces to:** RPR-P0-4

### Version-Specific Migration Patterns

**Priority:** P1
**Stability:** Draft

- GIVEN the user specifies upgrading from Coq 8.18 to 8.19 WHEN the repair workflow runs THEN version-specific migration patterns for the 8.18-to-8.19 transition are consulted before generic strategies
- GIVEN a migration knowledge base entry mapping `old_name` to `new_name` for a specific version pair WHEN the corresponding error is encountered THEN the replacement is applied directly without requiring a search step
- GIVEN a version pair for which no specific migration knowledge exists WHEN the repair workflow runs THEN the workflow falls back to generic search and hammer strategies without failing

**Traces to:** RPR-P0-10, RPR-P1-1

### Hammer Fallback

**Priority:** P0
**Stability:** Stable

- GIVEN a proof goal that remains broken after applying targeted fixes (renamed lemma, tactic migration) WHEN the hammer fallback is invoked THEN `hammer` is attempted on the goal, followed by `sauto` and `qauto` if `hammer` fails
- GIVEN a goal that CoqHammer proves successfully WHEN the repair is recorded THEN the original tactic sequence is replaced with the hammer-generated proof script
- GIVEN a goal that CoqHammer cannot prove WHEN all hammer variants have been tried THEN the goal is marked as unresolved in the repair report with a record of all attempted strategies

**Traces to:** RPR-P0-5

### Iterative Feedback Loop

**Priority:** P0
**Stability:** Stable

- GIVEN a batch of fixes has been applied to one or more files WHEN the rebuild step runs THEN the project is built again and the new set of errors is captured
- GIVEN that fixing a proof in file A eliminates a cascading error in file B WHEN the rebuild produces no error for file B THEN file B is not processed for repair
- GIVEN that a fix attempt introduced a new error WHEN the rebuild detects the new error THEN the fix is reverted and the original error is retained for alternative repair strategies
- GIVEN a repair iteration that resolves at least one previously broken proof WHEN the iteration completes THEN another iteration is started
- GIVEN a repair iteration that resolves zero new proofs WHEN the iteration completes THEN the loop terminates and a final report is produced
- GIVEN all proofs compile successfully after an iteration WHEN the rebuild produces zero errors THEN the loop terminates immediately with a success report

**Traces to:** RPR-P0-6, RPR-P0-7

### Dependency-Ordered Processing

**Priority:** P1
**Stability:** Stable

- GIVEN a project where file B imports file A and both have errors WHEN the repair workflow selects files to process THEN file A is processed before file B
- GIVEN that repairing file A eliminates all errors in file B WHEN the rebuild is performed THEN file B is marked as resolved without direct repair attempts
- GIVEN a project with circular dependencies WHEN dependency order is computed THEN the workflow falls back to file-system order for the cycle and continues without error

**Traces to:** RPR-P1-3

### Reporting and User Review

**Priority:** P0
**Stability:** Stable

- GIVEN a completed repair run WHEN the report is generated THEN it lists every automatically repaired proof with the file path, proof name, original error, and the fix that was applied
- GIVEN a completed repair run with unresolved proofs WHEN the report is generated THEN each unresolved proof includes the file path, proof name, current error message, and a list of all strategies that were attempted and why they failed
- GIVEN a completed repair run WHEN the report is generated THEN it includes a summary line with the total number of proofs broken, number repaired, and number remaining

**Traces to:** RPR-P0-8

### Diff Review Before Committing

**Priority:** P1
**Stability:** Stable

- GIVEN an automatically repaired proof WHEN the repair is ready to be applied THEN the diff showing the original and replacement proof text is presented to the user
- GIVEN a presented diff WHEN the user approves it THEN the repair is written to the source file
- GIVEN a presented diff WHEN the user rejects it THEN the original proof text is preserved and the proof is moved to the unresolved list in the report

**Traces to:** RPR-P1-6

### Real-Time Progress

**Priority:** P1
**Stability:** Stable

- GIVEN the repair workflow is running WHEN a new file begins processing THEN the file name and its position in the processing order are displayed
- GIVEN the repair workflow is running WHEN a proof is successfully repaired THEN the running count of repaired proofs and total broken proofs is updated
- GIVEN the repair workflow is running WHEN an iteration of the feedback loop completes THEN a summary of the iteration (proofs fixed in this pass, proofs remaining) is displayed

**Traces to:** RPR-P1-5

### Partial and Targeted Repair

**Priority:** P1
**Stability:** Stable

- GIVEN the user specifies a list of files or a directory WHEN `/proof-repair` is invoked THEN only errors in the specified files or directory are processed for repair
- GIVEN a partial repair scope WHEN the build is run THEN the entire project is still built (to detect all errors) but only errors within the specified scope are targeted for repair
- GIVEN a partial repair scope that includes files with no errors WHEN the workflow runs THEN those files are skipped without error

**Traces to:** RPR-P1-4
