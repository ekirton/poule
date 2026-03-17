# User Stories: Formalization Assistance

Derived from [doc/requirements/formalization-assistance.md](../formalization-assistance.md).

---

## Epic 1: Natural Language Input and Statement Suggestion

### 1.1 Describe a Theorem in Natural Language

**As a** Coq user,
**I want to** describe a theorem in plain English (or mathematical prose),
**so that** Claude can help me formalize it without requiring me to know Coq syntax upfront.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the `/formalize` command is invoked WHEN the user provides a natural language description of a theorem THEN Claude acknowledges the intent and begins the formalization workflow
- GIVEN a natural language description WHEN it is ambiguous or underspecified THEN Claude asks clarifying questions before suggesting a formal statement
- GIVEN a natural language description that references standard mathematical concepts WHEN Claude processes it THEN Claude correctly identifies the relevant Coq types, propositions, and quantifiers

**Traces to:** RFA-P0-1

### 1.2 Receive a Candidate Formal Statement

**As a** Coq user,
**I want to** receive a candidate formal Coq statement based on my natural language description,
**so that** I have a concrete starting point for my formalization.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a natural language theorem description WHEN Claude generates a candidate statement THEN the statement is syntactically valid Coq
- GIVEN a generated candidate statement WHEN it is checked against the active Coq environment THEN it is well-typed (no unresolved references or type errors)
- GIVEN a candidate statement WHEN it is presented to the user THEN Claude explains how each part of the formal statement corresponds to the natural language description

**Traces to:** RFA-P0-1, RFA-P0-5

### 1.3 Validate the Formal Statement Against the Coq Environment

**As a** Coq user,
**I want** the suggested formal statement to be type-checked before it is presented to me,
**so that** I do not waste time on statements that Coq will reject.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a candidate formal statement WHEN Claude generates it THEN Claude submits it to the Coq environment via the proof interaction protocol for type-checking before presenting it
- GIVEN a candidate statement that fails type-checking WHEN the error is returned THEN Claude revises the statement and retries, or explains the issue to the user
- GIVEN a candidate statement that passes type-checking WHEN it is presented to the user THEN it is marked as verified well-typed

**Traces to:** RFA-P0-5

### 1.4 Refine the Statement Through Dialogue

**As a** Coq user,
**I want to** tell Claude how the suggested statement differs from my intent and have it revise the statement,
**so that** I can converge on the correct formalization without editing Coq syntax directly.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a candidate statement that does not match the user's intent WHEN the user describes the needed correction in natural language THEN Claude produces a revised statement incorporating the feedback
- GIVEN an iterative refinement dialogue WHEN the user provides multiple rounds of feedback THEN Claude maintains context across rounds and does not regress on previously resolved issues
- GIVEN a refinement request WHEN the revised statement is generated THEN it is type-checked before being presented, just like the initial suggestion

**Traces to:** RFA-P1-1

---

## Epic 2: Lemma Search and Discovery

### 2.1 Search for Relevant Existing Lemmas

**As a** Coq user,
**I want** Claude to search for existing lemmas relevant to my described theorem,
**so that** I can reuse what is already formalized rather than reproving known results.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a natural language theorem description WHEN the `/formalize` workflow begins THEN Claude searches loaded libraries and the current project for relevant lemmas before suggesting a formal statement
- GIVEN a search for relevant lemmas WHEN results are found THEN at least the top 5 most relevant results are presented
- GIVEN a search for relevant lemmas WHEN no relevant results are found THEN Claude explicitly states that no existing formalization was found and proceeds to suggest a new statement

**Traces to:** RFA-P0-2

### 2.2 Explain Relevance of Search Results

**As a** Coq user,
**I want** each search result to include an explanation of why it is relevant to my theorem,
**so that** I can quickly assess which existing lemmas are useful without reading their full definitions.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a set of lemma search results WHEN they are presented to the user THEN each result includes a natural language explanation of its relevance to the described theorem
- GIVEN a search result WHEN the lemma is a direct match or generalization of the user's theorem THEN Claude highlights this explicitly (e.g., "this lemma already states your theorem" or "this is a more general version")
- GIVEN a search result WHEN the lemma is a supporting result needed in the proof THEN Claude explains how it could be used

**Traces to:** RFA-P0-6

### 2.3 Suggest Required Imports

**As a** Coq user,
**I want** Claude to suggest the `Require Import` statements needed for my formalization,
**so that** I do not have to manually track down which libraries provide the types, lemmas, and notations I need.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a candidate formal statement that references library definitions WHEN the statement is presented THEN Claude includes the necessary `Require Import` statements
- GIVEN relevant lemmas found during search WHEN they come from specific libraries THEN the import statements for those libraries are included in the suggestion
- GIVEN suggested imports WHEN they are applied to the Coq environment THEN the formal statement type-checks successfully

**Traces to:** RFA-P1-2

---

## Epic 3: Interactive Proof Building

### 3.1 Initiate a Proof Session for the Accepted Statement

**As a** Coq user,
**I want to** begin an interactive proof session once I accept the formal statement,
**so that** I can build the proof with Claude's guidance.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a formal statement that the user has accepted WHEN the user indicates they want to prove it THEN Claude opens a proof session for that statement via the proof interaction protocol
- GIVEN a proof session is opened WHEN the initial proof state is available THEN Claude displays the goal and context to the user
- GIVEN a formal statement with required imports WHEN the proof session is initiated THEN the imports are loaded before the statement is introduced

**Traces to:** RFA-P0-3

### 3.2 Suggest Tactic Steps Based on Proof State and Intent

**As a** Coq user,
**I want** Claude to suggest tactic steps based on the current proof state and my original mathematical description,
**so that** I can make progress on the proof without memorizing the tactic library.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an open proof goal WHEN Claude suggests a tactic step THEN the suggestion is accompanied by a natural language explanation of what the tactic does and why it is appropriate
- GIVEN an open proof goal WHEN Claude suggests a tactic THEN the tactic is informed by both the current proof state and the user's original natural language description of the theorem
- GIVEN a suggested tactic that the user applies WHEN it produces subgoals THEN Claude explains the resulting subgoals in terms of the overall proof strategy

**Traces to:** RFA-P0-4

### 3.3 Attempt Automated Proof Strategies

**As a** Coq user,
**I want** Claude to try automated tactics (hammer, auto, omega, etc.) on proof goals before suggesting manual steps,
**so that** routine goals are discharged quickly without my intervention.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an open proof goal during the proof-building phase WHEN Claude evaluates the goal THEN it first attempts automated strategies (e.g., `hammer`, `sauto`, `auto`, `omega`) before suggesting manual tactic steps
- GIVEN an automated strategy that succeeds WHEN the result is returned THEN Claude reports the proof script and explains what it does
- GIVEN automated strategies that all fail WHEN Claude falls back to manual suggestions THEN it explains briefly why automation did not work (e.g., "this goal appears to require case analysis that the automated tactics cannot discover")

**Traces to:** RFA-P1-3

### 3.4 Explain Proof Failures in Mathematical Terms

**As a** Coq user,
**I want** proof step failures to be explained in terms of the mathematical content rather than raw Coq error messages,
**so that** I can understand what went wrong and adjust my approach.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a tactic that fails WHEN the Coq error is returned THEN Claude translates the error into a natural language explanation referencing the mathematical concepts involved
- GIVEN a tactic failure due to a type mismatch WHEN Claude explains the failure THEN it identifies which mathematical objects have incompatible types and why
- GIVEN a tactic failure WHEN Claude explains it THEN Claude also suggests an alternative tactic or approach

**Traces to:** RFA-P1-4

---

## Epic 4: Partial and Alternative Formalizations

### 4.1 Complete a Partial Theorem Description

**As a** Coq user,
**I want to** describe part of a theorem and have Claude infer the rest from context,
**so that** I can work incrementally without specifying every detail upfront.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a partial natural language description (e.g., "the associativity of append for lists") WHEN Claude processes it THEN Claude infers the full statement including the universally quantified variables and the correct types
- GIVEN a partial description WHEN Claude completes it THEN Claude explains what was inferred and asks the user to confirm before proceeding
- GIVEN a partial description in the context of a Coq file WHEN Claude processes it THEN Claude uses the file's existing definitions and imports to guide the completion

**Traces to:** RFA-P1-5

### 4.2 Suggest Alternative Formalizations

**As a** Coq user,
**I want** Claude to present alternative ways to formalize my theorem when multiple reasonable options exist,
**so that** I can choose the formalization that best fits my proof development.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a natural language theorem description WHEN there are multiple reasonable formalizations (e.g., using `Prop` vs `bool`, bundled vs unbundled structures, classical vs constructive) THEN Claude presents at least two alternatives with trade-off explanations
- GIVEN multiple formalization alternatives WHEN the user selects one THEN the workflow proceeds with the selected formalization
- GIVEN alternatives WHEN they are presented THEN Claude explains the practical consequences of each choice (e.g., "the classical version requires the excluded middle axiom")

**Traces to:** RFA-P2-1
