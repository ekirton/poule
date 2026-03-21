# Fill Admits

A batch automation tool that scans a Coq proof script for `admit` calls, invokes proof search on each one, and returns the script with successfully filled admits replaced by verified tactic sequences.

---

## Problem

Coq developers frequently sketch proofs with `admit` placeholders — establishing the high-level proof structure while deferring routine sub-obligations. Filling these admits is tedious: each requires understanding the local proof context, finding relevant lemmas, and writing the right tactic sequence. This is precisely the kind of work that proof search handles well, but invoking search manually on each admit one at a time is cumbersome.

## Solution

A tool that, given a proof script file:

1. Identifies all `admit` calls in the file
2. For each admit, opens a proof session at that point, observes the sub-goal, and invokes proof search
3. When search succeeds, replaces the `admit` with the verified tactic sequence
4. Returns the modified script with a summary: which admits were filled, which remain open

The result is a concrete, verifiable script — not suggestions. Every replacement has been checked by Coq.

## Sketch-Then-Prove

Fill-admits enables a powerful workflow when combined with Claude Code's natural reasoning:

1. The user describes a proof goal to Claude
2. Claude produces a proof sketch with `admit` stubs as intermediate subgoals — establishing the high-level strategy
3. The user (or Claude) invokes fill-admits on the sketch
4. Proof search independently attacks each stub
5. The result shows which stubs were discharged and which need manual attention

This decomposition is effective because high-level proof strategy is where Claude's reasoning excels (choosing the induction scheme, identifying the key lemma), while filling individual sub-goals is where algorithmic search excels (trying combinations of tactics and solver invocations systematically).

## Partial Success

Fill-admits does not require all admits to be filled. When some admits resist proof search:

- Successfully filled admits are replaced with verified tactic sequences
- Unfilled admits remain as `admit` in the output
- The summary indicates which admits were filled and which remain, with the failure information from proof search for each unfilled admit

This partial-success model matches how developers work: fill what can be filled automatically, then focus manual effort on the remaining obligations.

## Design Rationale

### Why a separate tool rather than invoking proof search in a loop

Claude Code could loop over admits conversationally — opening a session for each, invoking proof search, collecting results. But this produces a long, noisy conversation for what is fundamentally a batch operation. A dedicated tool runs the entire batch internally and returns a single consolidated result. It also enables optimizations that a conversational loop cannot: sharing proof state context across admits in the same file, parallelizing search across independent admits, and producing an atomic output script.

### Why not auto-fill admits during proof search

Proof search operates on a single goal at a time. Fill-admits is an orchestration layer that coordinates multiple proof searches within the context of a single file. Keeping them separate preserves a clean tool boundary: proof search is stateless (goal in, proof out), fill-admits manages the file-level workflow.

### Why return a modified script rather than a list of replacements

Developers want to see the complete proof, not a patch file. A modified script can be directly loaded into Coq for verification, pasted into the source file, or diffed against the original. A list of (location, replacement) pairs requires the user to apply changes manually — an unnecessary friction point.

## Acceptance Criteria

### Fill-Admits Tool

**Priority:** P1
**Stability:** Stable

- GIVEN a proof script file containing `admit` calls WHEN fill-admits is invoked THEN it identifies each `admit` and invokes proof search on the corresponding sub-goal
- GIVEN a fill-admits run WHEN it completes THEN the result indicates which admits were successfully filled and which remain open
- GIVEN a successfully filled admit WHEN the replacement is inspected THEN it is a Coq-verified tactic sequence that closes the sub-goal

**Traces to:** R4-P1-5

### Sketch-Then-Prove

**Priority:** P1
**Stability:** Draft

- GIVEN a proof script with `admit` stubs as intermediate subgoals WHEN sketch-then-prove is invoked THEN proof search is applied independently to each stub
- GIVEN a partially filled sketch WHEN the result is returned THEN it indicates which stubs were successfully filled and which remain open
- GIVEN all stubs successfully filled WHEN the combined script is inspected THEN the complete proof is valid according to Coq

**Traces to:** R4-P1-7
