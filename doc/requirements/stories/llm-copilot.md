# User Stories: LLM Copilot

Derived from [doc/requirements/llm-copilot.md](../llm-copilot.md).

---

## Epic 1: Tactic Suggestion

### 1.1 Suggest Next Tactics for a Proof State

**As a** Coq developer using Claude Code,
**I want to** request tactic suggestions for my current proof state and receive a ranked list of candidate tactics that have been verified against Coq,
**so that** I can explore promising proof directions without manually guessing tactics.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof state with open goals and hypotheses WHEN tactic suggestion is requested THEN a ranked list of candidate tactics is returned
- GIVEN a list of candidate tactics WHEN it is presented to the user THEN every tactic in the list has been submitted to Coq and confirmed to produce a valid successor proof state
- GIVEN a proof state for which no valid tactics are found WHEN suggestion completes THEN a structured message indicates that no verified suggestions were produced

**Traces to:** R4-P0-1, R4-P0-2, R4-P0-11

### 1.2 Premise-Augmented Tactic Suggestion

**As a** Coq developer working with large libraries,
**I want** tactic suggestions to incorporate relevant lemmas retrieved from my indexed libraries,
**so that** suggestions can reference lemmas I might not know about, such as `apply` or `rewrite` with a retrieved lemma.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof state and an indexed library database WHEN tactic suggestion is requested THEN relevant premises are retrieved and included as context for tactic generation
- GIVEN retrieved premises WHEN candidate tactics are generated THEN some candidates reference retrieved lemmas (e.g., `apply retrieved_lemma`, `rewrite retrieved_lemma`)
- GIVEN no indexed library database is available WHEN tactic suggestion is requested THEN suggestions are still generated using only the local proof context

**Traces to:** R4-P0-3

### 1.3 Tactic Suggestion MCP Tool

**As a** Coq developer using Claude Code,
**I want** tactic suggestion exposed as an MCP tool,
**so that** Claude can invoke it during our conversational proof workflow.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a running MCP server WHEN the tactic suggestion tool is invoked with a proof session ID THEN it returns verified tactic suggestions for the current proof state in that session
- GIVEN the tactic suggestion tool WHEN it is invoked THEN the response is returned within 5 seconds
- GIVEN the MCP server WHEN its tool list is inspected THEN a tactic suggestion tool is present with a documented schema

**Traces to:** R4-P0-4, R4-P0-9

### 1.4 Tactic Explanations

**As a** Coq newcomer or student,
**I want** each suggested tactic to include a brief natural-language explanation of what it does and why it may help,
**so that** I can learn from the suggestions rather than blindly applying them.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a list of suggested tactics WHEN they are presented THEN each tactic includes a natural-language explanation
- GIVEN an explanation WHEN it is read THEN it describes the tactic's effect on the proof state and why it is relevant to the current goal

**Traces to:** R4-P1-6

---

## Epic 2: Proof Search

### 2.1 Multi-Step Proof Search

**As a** Coq developer facing a proof obligation,
**I want to** request a multi-step proof search that attempts to find a complete, Coq-verified proof,
**so that** routine proof obligations can be discharged automatically.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof state WHEN proof search is requested THEN the system explores multiple tactic sequences attempting to close all goals
- GIVEN a successful proof search WHEN the result is returned THEN it includes the complete verified proof script
- GIVEN a proof search that does not find a complete proof within the timeout WHEN the result is returned THEN it includes structured failure information and the best partial progress achieved
- GIVEN a proof search WHEN it runs THEN each tactic in explored sequences is verified against Coq before further exploration

**Traces to:** R4-P0-5, R4-P0-7, R4-P0-8, R4-P0-11

### 2.2 Proof Search MCP Tool

**As a** Coq developer using Claude Code,
**I want** proof search exposed as an MCP tool,
**so that** Claude can attempt to find complete proofs during our conversational workflow.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a running MCP server WHEN the proof search tool is invoked with a proof session ID THEN it attempts to find a complete proof for the current proof state
- GIVEN the proof search tool WHEN it is invoked without a timeout parameter THEN the default timeout of 30 seconds is applied
- GIVEN the proof search tool WHEN it is invoked with a custom timeout THEN that timeout is respected
- GIVEN the MCP server WHEN its tool list is inspected THEN a proof search tool is present with a documented schema

**Traces to:** R4-P0-6, R4-P0-10

### 2.3 Configurable Search Parameters

**As a** Coq developer or AI researcher,
**I want to** configure search depth, breadth limits, and timeout for proof search,
**so that** I can trade off between search thoroughness and time budget.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof search request with a specified maximum search depth WHEN search runs THEN it does not explore tactic sequences longer than the specified depth
- GIVEN a proof search request with a specified breadth limit WHEN search runs THEN it does not explore more than the specified number of candidate tactics at each step
- GIVEN a proof search request with a specified timeout WHEN the timeout elapses THEN search terminates and returns the best partial progress

**Traces to:** R4-P1-7

### 2.4 Search State Caching

**As a** Coq developer waiting for proof search results,
**I want** the search to cache proof states and avoid redundant Coq interactions for previously explored states,
**so that** search completes faster by not re-verifying the same tactic in the same state.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof search WHEN two different tactic sequences lead to the same proof state THEN the system recognizes the duplicate and does not re-explore from that state
- GIVEN a proof search with caching enabled WHEN it completes THEN the total number of Coq interactions is less than or equal to the number without caching

**Traces to:** R4-P1-8

---

## Epic 3: Premise Selection

### 3.1 Goal-Directed Premise Selection

**As a** Coq developer looking for relevant lemmas,
**I want to** request a ranked list of potentially useful lemmas for my current proof goal,
**so that** I can discover applicable lemmas from indexed libraries without manually searching.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof goal WHEN premise selection is requested THEN a ranked list of potentially useful lemmas from indexed libraries is returned
- GIVEN the ranked list WHEN it is inspected THEN each entry includes the lemma's fully qualified name, type, and a relevance score
- GIVEN a proof goal involving concepts from an indexed library WHEN premise selection is requested THEN lemmas from that library appear in the results

**Traces to:** R4-P1-5

---

## Epic 4: Advanced Proof Strategies

### 4.1 Few-Shot Context from Training Data

**As a** Coq developer,
**I want** tactic suggestions to incorporate few-shot examples from similar proofs in the extracted training data,
**so that** suggestions benefit from patterns seen in existing Coq proof developments.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN extracted training data for a Coq project WHEN tactic suggestion is requested THEN similar proof states and their successful tactics are retrieved and included as few-shot context for the LLM
- GIVEN few-shot examples WHEN they are used THEN suggestion quality improves compared to suggestions without few-shot context (measured on a held-out evaluation set)

**Traces to:** R4-P1-1

### 4.2 Sketch-Then-Prove

**As a** Coq developer working on a complex proof,
**I want** the copilot to generate a proof plan as a sketch with intermediate lemmas as admit stubs, then attempt to fill each stub independently,
**so that** complex proofs can be decomposed into manageable sub-problems.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof goal WHEN sketch-then-prove is requested THEN the system generates a proof script with intermediate lemmas as `admit` stubs
- GIVEN a proof sketch with admit stubs WHEN filling is attempted THEN each stub is attempted independently using proof search
- GIVEN a partially filled sketch WHEN filling completes THEN the result indicates which stubs were successfully filled and which remain open

**Traces to:** R4-P1-2

### 4.3 Neuro-Symbolic Interleaving

**As a** Coq developer,
**I want** proof search to interleave LLM-generated tactics with symbolic automation (CoqHammer, `auto`, `omega`),
**so that** the LLM provides high-level strategy while solvers handle mechanical sub-goals.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof search WHEN candidate tactics are generated THEN the candidate set includes both LLM-generated tactics and invocations of symbolic solvers
- GIVEN a proof state that is dischargeable by `omega` or `auto` WHEN proof search encounters it THEN the solver tactic is tried and, if successful, used to close the sub-goal
- GIVEN a completed proof found by search WHEN it is inspected THEN it may contain a mix of LLM-suggested and solver-suggested tactics

**Traces to:** R4-P1-3

### 4.4 Diversity-Aware Tactic Selection

**As a** Coq developer waiting for proof search results,
**I want** the search to avoid exploring near-duplicate tactic candidates,
**so that** the search budget is spent on genuinely different proof directions.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof state with multiple candidate tactics WHEN candidates are selected for exploration THEN near-duplicate candidates (syntactically or semantically equivalent) are filtered or de-prioritized
- GIVEN diversity-aware selection WHEN proof search completes THEN the explored tactic sequences cover a broader range of proof strategies compared to non-diverse selection

**Traces to:** R4-P1-4

---

## Epic 5: Fill Admits and Difficulty Estimation

### 5.1 Fill-Admits Mode

**As a** Coq developer with a partially complete proof,
**I want** the copilot to scan my proof script for `admit` calls and attempt to discharge each one,
**so that** I can sketch a proof with placeholders and let the copilot fill in the details.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof script containing `admit` calls WHEN fill-admits mode is invoked THEN the copilot identifies each `admit` and attempts to replace it with a verified proof
- GIVEN a fill-admits run WHEN it completes THEN the result indicates which admits were successfully filled and which remain open
- GIVEN a successfully filled admit WHEN the replacement is inspected THEN it is a Coq-verified tactic sequence that closes the sub-goal

**Traces to:** R4-P2-2

### 5.2 Proof Difficulty Estimation

**As a** Coq developer deciding whether to invoke proof search,
**I want** the copilot to estimate the difficulty and likely proof distance for a goal,
**so that** I can make informed decisions about whether to attempt automated proving or proceed manually.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof state WHEN difficulty estimation is requested THEN the system returns an estimated difficulty level and approximate number of remaining proof steps
- GIVEN the estimation WHEN it is presented THEN it includes a confidence indicator

**Traces to:** R4-P2-5

### 5.3 Subgoal Decomposition

**As a** Coq developer working on a complex goal,
**I want** the copilot to break the goal into a sequence of intermediate subgoals and attempt each independently,
**so that** complex goals can be tackled incrementally.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a complex proof goal WHEN subgoal decomposition is requested THEN the system proposes a sequence of intermediate subgoals
- GIVEN proposed subgoals WHEN they are attempted THEN each is attempted independently using proof search
- GIVEN a decomposition attempt WHEN it completes THEN the result indicates which subgoals were discharged and which remain open

**Traces to:** R4-P2-4

---

## Epic 6: Pluggable Backends and Session Learning

### 6.1 Pluggable LLM Backends

**As an** AI researcher evaluating different models for Coq proof assistance,
**I want** the copilot to support pluggable LLM backends beyond Claude,
**so that** I can compare model performance or use open-source models for offline proving.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a copilot configuration WHEN a non-default LLM backend is specified THEN the copilot uses that backend for tactic generation
- GIVEN a pluggable backend WHEN it is used THEN the verification and premise retrieval pipeline remains the same

**Traces to:** R4-P2-1

### 6.2 Session-Level Learning

**As a** Coq developer working on a long proof development session,
**I want** the copilot to learn from my acceptance and rejection of suggestions within the session,
**so that** subsequent suggestions better match my proof style and the current development context.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a session where the user has accepted or rejected suggestions WHEN subsequent suggestions are generated THEN they incorporate feedback from prior acceptances and rejections in the session
- GIVEN session-level learning WHEN a new session starts THEN no state from previous sessions is carried over

**Traces to:** R4-P2-3
