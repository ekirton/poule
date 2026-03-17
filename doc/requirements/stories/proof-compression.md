# User Stories: Proof Compression

Derived from [doc/requirements/proof-compression.md](../proof-compression.md).

---

## Epic 1: Proof Analysis

### 1.1 Accept and Verify a Working Proof

**As a** formalization developer,
**I want to** invoke `/compress-proof` on a theorem in my project and have it verify that the proof currently compiles,
**so that** compression is only attempted on valid proofs, avoiding wasted effort on broken proof scripts.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a theorem name that exists in the current Coq project WHEN `/compress-proof` is invoked THEN the command locates the proof and verifies it compiles before proceeding
- GIVEN a theorem name whose proof does not compile WHEN `/compress-proof` is invoked THEN a clear error is returned indicating that the proof must compile before compression can be attempted
- GIVEN a theorem name that does not exist in the project WHEN `/compress-proof` is invoked THEN a clear error is returned indicating that the theorem was not found

**Traces to:** RPC-P0-1

### 1.2 Extract the Proof Goal and Context

**As a** formalization developer,
**I want** `/compress-proof` to extract the proof goal and hypothesis context from the start of the proof,
**so that** alternative strategies can target the same goal with full knowledge of available hypotheses.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid proof WHEN the goal and context are extracted THEN the extracted goal matches the statement of the theorem
- GIVEN a proof with local hypotheses introduced in the proof script WHEN the goal is extracted at the proof start THEN the full unintroduced goal is captured
- GIVEN a proof with section variables in scope WHEN the goal and context are extracted THEN section variables are included in the context

**Traces to:** RPC-P0-2

---

## Epic 2: Alternative Strategy Attempts

### 2.1 Attempt Hammer-Based Compression

**As a** formalization developer,
**I want** `/compress-proof` to try `hammer`, `sauto`, and `qauto` as single-tactic replacements for my entire proof,
**so that** proofs that can be discharged by automation are reduced to a single tactic call.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid proof WHEN hammer-based compression is attempted THEN `hammer`, `sauto`, and `qauto` are each tried against the proof goal
- GIVEN a goal that `sauto` can discharge WHEN hammer-based compression is attempted THEN the `sauto` solution is returned as a candidate alternative
- GIVEN a goal that none of the hammer tactics can discharge WHEN hammer-based compression is attempted THEN the command proceeds to other compression strategies without error

**Traces to:** RPC-P0-3

### 2.2 Attempt Lemma-Search-Based Compression

**As a** formalization developer,
**I want** `/compress-proof` to search for direct lemmas that close the goal without the intermediate steps in my original proof,
**so that** I can discover existing library lemmas that make my proof unnecessary.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a valid proof WHEN lemma-search-based compression is attempted THEN a search for lemmas matching the goal type is performed
- GIVEN a lemma that directly proves the goal WHEN it is found THEN a candidate alternative using `exact` or `apply` with that lemma is generated
- GIVEN no directly applicable lemma WHEN the search completes THEN the command proceeds to other compression strategies without error

**Traces to:** RPC-P0-4

### 2.3 Attempt Tactic Chain Simplification

**As a** formalization developer,
**I want** `/compress-proof` to identify sequences of tactics in my proof that can be collapsed into fewer steps,
**so that** my proof is cleaned up even when a completely different strategy is not available.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof containing `intros x; intros y; intros z` WHEN tactic chain simplification is attempted THEN a candidate replacing them with `intros x y z` is generated
- GIVEN a proof containing a sequence of `rewrite` steps that can be chained WHEN tactic chain simplification is attempted THEN a candidate with a combined rewrite is generated
- GIVEN a proof where no tactic sequences can be simplified WHEN tactic chain simplification is attempted THEN the command reports no simplification found for this strategy

**Traces to:** RPC-P1-1

### 2.4 Compress a Sub-Proof or Single Step

**As a** formalization developer,
**I want to** target compression at a specific proof step or subproof rather than the entire proof,
**so that** I can focus on the parts of a proof I know are verbose without waiting for the entire proof to be analyzed.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof with a bullet-delimited subproof WHEN `/compress-proof` is invoked targeting that subproof THEN only the targeted subproof is analyzed and compressed
- GIVEN a specific tactic step WHEN `/compress-proof` is invoked targeting that step THEN alternatives for that step are explored in the context of the surrounding proof state
- GIVEN a targeted sub-proof compression that succeeds WHEN the result is presented THEN the full proof with the compressed sub-proof substituted in is shown

**Traces to:** RPC-P1-4

---

## Epic 3: Verification and Comparison

### 3.1 Verify All Candidate Alternatives

**As a** formalization developer,
**I want** every candidate alternative proof to be checked by Coq before it is presented to me,
**so that** I can trust that any alternative I adopt is a valid proof.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a candidate alternative proof WHEN it is generated THEN it is submitted to Coq for verification before being presented to the user
- GIVEN a candidate that Coq rejects WHEN verification is performed THEN the candidate is silently discarded and not shown to the user
- GIVEN multiple candidate alternatives WHEN they are all verified THEN only those accepted by Coq are included in the results

**Traces to:** RPC-P0-5

### 3.2 Compare and Present Results

**As a** formalization developer,
**I want** compression results to include a clear comparison between my original proof and each alternative,
**so that** I can make an informed decision about whether to adopt an alternative.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN one or more verified alternatives WHEN results are presented THEN each alternative shows the tactic count of the original proof alongside the tactic count of the alternative
- GIVEN one or more verified alternatives WHEN results are presented THEN the full alternative proof script is shown so the user can review it
- GIVEN no verified alternatives were found WHEN results are presented THEN the command reports that no shorter alternative was found and the original proof is already concise

**Traces to:** RPC-P0-7

### 3.3 Rank Multiple Alternatives

**As a** formalization developer,
**I want** multiple compression alternatives to be ranked by quality,
**so that** the best option is presented first and I do not need to evaluate all candidates manually.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN multiple verified alternatives WHEN results are presented THEN they are ordered by a ranking that considers tactic count, estimated readability, and resilience to upstream changes
- GIVEN multiple verified alternatives WHEN results are presented THEN each includes a brief note explaining the compression strategy used (e.g., "hammer replacement", "direct lemma application", "tactic chain simplification")
- GIVEN a single verified alternative WHEN results are presented THEN it is shown without ranking metadata

**Traces to:** RPC-P1-2, RPC-P1-3

---

## Epic 4: Safe Replacement

### 4.1 Preserve the Original Proof

**As a** formalization developer,
**I want** `/compress-proof` to never modify my source file without my explicit consent,
**so that** I can safely explore compression without risking loss of my working proof.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a compression run that finds alternatives WHEN the command completes THEN the original source file is unchanged
- GIVEN a compression run WHEN it encounters an error at any stage THEN the original source file is unchanged
- GIVEN the user has not provided explicit consent to apply changes WHEN alternatives are presented THEN no file modifications are made

**Traces to:** RPC-P0-6

### 4.2 Apply a Selected Alternative

**As a** formalization developer,
**I want to** select one of the suggested alternatives and have it applied to my source file in place of the original proof,
**so that** I can adopt compressed proofs without manual copy-paste.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a set of compression results WHEN the user selects an alternative to apply THEN the original proof in the source file is replaced with the selected alternative
- GIVEN a replacement is applied WHEN the file is saved THEN the replaced proof compiles successfully (it was already verified in the comparison step)
- GIVEN a replacement is applied WHEN the user wants to undo THEN standard editor undo or version control can restore the original proof

**Traces to:** RPC-P1-5

---

## Epic 5: Reporting

### 5.1 Batch Compression Report

**As a** library maintainer,
**I want to** run `/compress-proof` across all proofs in a file or module and receive a summary report,
**so that** I can identify the highest-impact compression opportunities in my codebase.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a file containing multiple theorems WHEN batch compression is invoked THEN each proof is analyzed and a summary report is produced
- GIVEN a batch compression run WHEN the report is produced THEN it lists theorems where compression was found, ordered by compression ratio (most compressible first)
- GIVEN a batch compression run WHEN some proofs cannot be compressed THEN they are listed separately with a note that no shorter alternative was found

**Traces to:** RPC-P2-1

### 5.2 Report When No Compression Is Possible

**As a** formalization developer,
**I want** `/compress-proof` to tell me when a proof is already concise and explain why no compression was found,
**so that** I have confidence that the proof is in good shape rather than wondering if the tool failed silently.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof that is already a single tactic call WHEN `/compress-proof` is invoked THEN the command reports that the proof is already minimal
- GIVEN a proof where all compression strategies were tried and none produced a shorter alternative WHEN the results are presented THEN the command reports which strategies were attempted and why none succeeded
- GIVEN a proof that cannot be compressed WHEN the result is presented THEN the original proof is confirmed as unchanged

**Traces to:** RPC-P2-4
