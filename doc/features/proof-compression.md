# Proof Compression

Proof scripts accumulate tactical debt over time: chains of rewrites that a single lemma application could replace, sequences of introductions and destructions that hammer dispatches in one step, intermediate assertions that a more direct path renders unnecessary. Proof Compression provides a `/compress-proof` slash command that takes a working proof and systematically searches for shorter or cleaner alternatives — trying hammer tactics, searching for more direct lemmas, and simplifying tactic chains — then presents ranked options for the user to review. The original proof is always preserved; the user decides whether to adopt any alternative.

---

## Problem

A proof that works is not necessarily a proof that is finished. In large formalizations, proof scripts grow verbose through natural development: the developer tries tactics until something works, builds up intermediate steps to navigate an unfamiliar goal, or pieces together rewrites without knowing a library lemma that handles the case directly. The result is proofs that are longer than they need to be — harder to read during review, harder to maintain when upstream definitions change, and harder for newcomers to learn from.

The tools to find shorter proofs already exist individually. CoqHammer can sometimes replace a multi-step proof with a single tactic call. Lemma search can surface library lemmas the developer did not know about. Tactic sequences can often be collapsed. But applying these tools to an existing proof is entirely manual: the developer must identify which proof might benefit, try each strategy by hand, verify the result, and compare alternatives. This is tedious enough that most developers skip it unless they are preparing a library for release.

What is missing is a way to say "this proof works — find me something shorter" and have the search happen automatically.

## Solution

The `/compress-proof` command takes a working proof and explores multiple compression strategies, presenting verified alternatives that the user can adopt or ignore.

### Multi-Strategy Exploration

When invoked on a proof, `/compress-proof` tries several approaches to find a shorter alternative. It attempts hammer tactics (`hammer`, `sauto`, `qauto`) as single-tactic replacements for the entire proof. It searches for library lemmas that close the goal directly, replacing multi-step reasoning with a single application. It looks for tactic chains that can be collapsed into fewer steps — consecutive introductions, redundant rewrites, sequences that a combined tactic handles. Each strategy runs independently, so a failure in one does not prevent the others from succeeding.

### Verified Alternatives Only

Every candidate alternative is checked by Coq before the user sees it. If a candidate does not compile, it is silently discarded. The user never has to wonder whether a suggested alternative actually works — if it appears in the results, it has been verified.

### Comparison and Ranking

When multiple alternatives are found, they are ranked and presented with a clear comparison against the original proof: how many tactic steps each uses, what strategy produced it, and the full proof script. The user can see at a glance whether the compressed version is worth adopting. When only one alternative is found, it is presented directly. When no compression is possible, the command says so and explains which strategies were tried.

### Safe by Default

The original proof is never modified without explicit user consent. `/compress-proof` is a read-only exploration — it analyzes, searches, and reports, but leaves the source file untouched until the user chooses to apply an alternative. If the user does select an alternative, it replaces the original proof in the source file, and standard editor undo or version control can restore the original at any time.

### Sub-Proof Targeting

Compression can target a specific proof step or subproof rather than the entire proof. This lets the user focus on the parts they know are verbose — a particular case in a case analysis, a long chain of rewrites in one branch — without waiting for the entire proof to be analyzed.

## Scope

Proof Compression provides:

- A `/compress-proof` slash command that orchestrates existing MCP tools
- Hammer-based compression: trying `hammer`, `sauto`, and `qauto` as single-tactic replacements
- Lemma-search-based compression: finding direct lemmas that close the goal without intermediate steps
- Tactic chain simplification: collapsing sequences of tactics into fewer steps
- Verification of every candidate alternative against the Coq kernel before presenting it
- Ranked comparison of alternatives against the original proof
- Safe replacement with explicit user consent
- Sub-proof and single-step targeting
- Batch mode for scanning all proofs in a file or module

Proof Compression does not provide:

- Modifications to any underlying MCP tools (hammer, proof interaction, lemma search) — it orchestrates them as-is
- Proof synthesis for unproven goals — this feature works only on proofs that already compile (see [Proof Search](proof-search.md) for proving open goals)
- Proof style enforcement beyond what informs compression ranking (see [Proof Style Linting](proof-style-linting.md) for style conventions)
- Semantic equivalence checking beyond Coq kernel acceptance
- Automated application without user review — the user always decides whether to adopt an alternative

---

## Design Rationale

### Why a slash command rather than an MCP tool

Proof compression is an inherently multi-step workflow: verify the original proof, extract the goal, try multiple strategies, verify candidates, compare results, and present options. This is orchestration over existing tools, not a single operation that belongs in the tool layer. A slash command lets Claude reason through the workflow, adapt to intermediate results (e.g., skip lemma search if hammer already found a one-tactic proof), and present results conversationally. Encoding this logic in a single MCP tool would make it rigid and opaque.

### Why try multiple strategies rather than picking one

No single compression strategy dominates. Hammer tactics excel at first-order goals but cannot simplify tactic chains. Lemma search finds direct library applications that hammer might miss because the lemma does not follow from first principles alone. Tactic chain simplification helps even when no fundamentally different proof exists. Trying all strategies and letting the user choose among verified alternatives produces better results than any single strategy could.

### Why verify before presenting

An unverified "shorter proof" is worse than no suggestion at all. If the user adopts an alternative that does not compile, they have lost the time spent reviewing it and must revert. By verifying every candidate against the Coq kernel, the command guarantees that any alternative the user sees is ready to use. The cost is additional Coq invocations, but this is far less expensive than the user's time debugging a broken proof.

### Why preserve the original proof by default

Proof compression is exploratory. The user may want to see what is possible without committing to any change. They may prefer the original proof for readability reasons even when a shorter alternative exists. They may want to review alternatives across multiple proofs before deciding which to adopt. Making the command read-only by default removes the risk of exploring compression and lets the user apply changes deliberately.

### Why shorter proofs matter

Shorter proofs are not just an aesthetic preference. A proof that uses fewer tactics has fewer points where an upstream change can cause breakage. A proof that applies a library lemma directly is more robust than one that re-derives the same result through intermediate steps — if the library changes its internal representation, the direct application still works while the re-derivation may not. Shorter proofs are also faster to review, easier for newcomers to understand, and quicker for Coq to check. In large formalizations, these advantages compound across hundreds or thousands of proofs.

---

## Acceptance Criteria

### Accept and Verify a Working Proof

**Priority:** P0
**Stability:** Stable

- GIVEN a theorem name that exists in the current Coq project WHEN `/compress-proof` is invoked THEN the command locates the proof and verifies it compiles before proceeding
- GIVEN a theorem name whose proof does not compile WHEN `/compress-proof` is invoked THEN a clear error is returned indicating that the proof must compile before compression can be attempted
- GIVEN a theorem name that does not exist in the project WHEN `/compress-proof` is invoked THEN a clear error is returned indicating that the theorem was not found

**Traces to:** RPC-P0-1

### Extract the Proof Goal and Context

**Priority:** P0
**Stability:** Stable

- GIVEN a valid proof WHEN the goal and context are extracted THEN the extracted goal matches the statement of the theorem
- GIVEN a proof with local hypotheses introduced in the proof script WHEN the goal is extracted at the proof start THEN the full unintroduced goal is captured
- GIVEN a proof with section variables in scope WHEN the goal and context are extracted THEN section variables are included in the context

**Traces to:** RPC-P0-2

### Attempt Hammer-Based Compression

**Priority:** P0
**Stability:** Stable

- GIVEN a valid proof WHEN hammer-based compression is attempted THEN `hammer`, `sauto`, and `qauto` are each tried against the proof goal
- GIVEN a goal that `sauto` can discharge WHEN hammer-based compression is attempted THEN the `sauto` solution is returned as a candidate alternative
- GIVEN a goal that none of the hammer tactics can discharge WHEN hammer-based compression is attempted THEN the command proceeds to other compression strategies without error

**Traces to:** RPC-P0-3

### Attempt Lemma-Search-Based Compression

**Priority:** P0
**Stability:** Stable

- GIVEN a valid proof WHEN lemma-search-based compression is attempted THEN a search for lemmas matching the goal type is performed
- GIVEN a lemma that directly proves the goal WHEN it is found THEN a candidate alternative using `exact` or `apply` with that lemma is generated
- GIVEN no directly applicable lemma WHEN the search completes THEN the command proceeds to other compression strategies without error

**Traces to:** RPC-P0-4

### Attempt Tactic Chain Simplification

**Priority:** P1
**Stability:** Draft

- GIVEN a proof containing `intros x; intros y; intros z` WHEN tactic chain simplification is attempted THEN a candidate replacing them with `intros x y z` is generated
- GIVEN a proof containing a sequence of `rewrite` steps that can be chained WHEN tactic chain simplification is attempted THEN a candidate with a combined rewrite is generated
- GIVEN a proof where no tactic sequences can be simplified WHEN tactic chain simplification is attempted THEN the command reports no simplification found for this strategy

**Traces to:** RPC-P1-1

### Compress a Sub-Proof or Single Step

**Priority:** P1
**Stability:** Draft

- GIVEN a proof with a bullet-delimited subproof WHEN `/compress-proof` is invoked targeting that subproof THEN only the targeted subproof is analyzed and compressed
- GIVEN a specific tactic step WHEN `/compress-proof` is invoked targeting that step THEN alternatives for that step are explored in the context of the surrounding proof state
- GIVEN a targeted sub-proof compression that succeeds WHEN the result is presented THEN the full proof with the compressed sub-proof substituted in is shown

**Traces to:** RPC-P1-4

### Verify All Candidate Alternatives

**Priority:** P0
**Stability:** Stable

- GIVEN a candidate alternative proof WHEN it is generated THEN it is submitted to Coq for verification before being presented to the user
- GIVEN a candidate that Coq rejects WHEN verification is performed THEN the candidate is silently discarded and not shown to the user
- GIVEN multiple candidate alternatives WHEN they are all verified THEN only those accepted by Coq are included in the results

**Traces to:** RPC-P0-5

### Compare and Present Results

**Priority:** P0
**Stability:** Stable

- GIVEN one or more verified alternatives WHEN results are presented THEN each alternative shows the tactic count of the original proof alongside the tactic count of the alternative
- GIVEN one or more verified alternatives WHEN results are presented THEN the full alternative proof script is shown so the user can review it
- GIVEN no verified alternatives were found WHEN results are presented THEN the command reports that no shorter alternative was found and the original proof is already concise

**Traces to:** RPC-P0-7

### Rank Multiple Alternatives

**Priority:** P1
**Stability:** Draft

- GIVEN multiple verified alternatives WHEN results are presented THEN they are ordered by a ranking that considers tactic count, estimated readability, and resilience to upstream changes
- GIVEN multiple verified alternatives WHEN results are presented THEN each includes a brief note explaining the compression strategy used (e.g., "hammer replacement", "direct lemma application", "tactic chain simplification")
- GIVEN a single verified alternative WHEN results are presented THEN it is shown without ranking metadata

**Traces to:** RPC-P1-2, RPC-P1-3

### Preserve the Original Proof

**Priority:** P0
**Stability:** Stable

- GIVEN a compression run that finds alternatives WHEN the command completes THEN the original source file is unchanged
- GIVEN a compression run WHEN it encounters an error at any stage THEN the original source file is unchanged
- GIVEN the user has not provided explicit consent to apply changes WHEN alternatives are presented THEN no file modifications are made

**Traces to:** RPC-P0-6

### Apply a Selected Alternative

**Priority:** P1
**Stability:** Draft

- GIVEN a set of compression results WHEN the user selects an alternative to apply THEN the original proof in the source file is replaced with the selected alternative
- GIVEN a replacement is applied WHEN the file is saved THEN the replaced proof compiles successfully (it was already verified in the comparison step)
- GIVEN a replacement is applied WHEN the user wants to undo THEN standard editor undo or version control can restore the original proof

**Traces to:** RPC-P1-5

### Batch Compression Report

**Priority:** P2
**Stability:** Draft

- GIVEN a file containing multiple theorems WHEN batch compression is invoked THEN each proof is analyzed and a summary report is produced
- GIVEN a batch compression run WHEN the report is produced THEN it lists theorems where compression was found, ordered by compression ratio (most compressible first)
- GIVEN a batch compression run WHEN some proofs cannot be compressed THEN they are listed separately with a note that no shorter alternative was found

**Traces to:** RPC-P2-1

### Report When No Compression Is Possible

**Priority:** P2
**Stability:** Draft

- GIVEN a proof that is already a single tactic call WHEN `/compress-proof` is invoked THEN the command reports that the proof is already minimal
- GIVEN a proof where all compression strategies were tried and none produced a shorter alternative WHEN the results are presented THEN the command reports which strategies were attempted and why none succeeded
- GIVEN a proof that cannot be compressed WHEN the result is presented THEN the original proof is confirmed as unchanged

**Traces to:** RPC-P2-4
