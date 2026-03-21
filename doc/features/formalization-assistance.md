# Formalization Assistance

The gap between mathematical intuition and formal proof is the single largest barrier to Coq adoption. Users know what they want to prove — they can state it on a whiteboard or in a textbook — but translating that understanding into Coq's type theory requires navigating unfamiliar syntax, locating the right library lemmas, and managing an interactive proof session where each step depends on the evolving proof state. Formalization Assistance is a `/formalize` slash command that guides the user through the entire journey from a natural language description of a theorem to a completed, type-checked Coq proof, turning what is normally a multi-hour struggle into a single guided dialogue.

---

## Problem

Formalizing a mathematical result in Coq today requires three distinct skills that are rarely found together: understanding the mathematics well enough to state the result precisely, knowing Coq's type theory and library landscape well enough to express that statement formally, and navigating the interactive proof process to build a proof term. Each skill is individually demanding. Together, they make formalization inaccessible to most mathematicians and students, and tedious even for experienced Coq developers.

Existing tools address fragments of the problem but never the whole thing. Coq's `Search` and `SearchPattern` commands can find lemmas, but only if the user already knows the right query syntax and can sift through unranked results. CoqHammer can discharge goals, but only after the user has stated the theorem and opened a proof session. No existing tool accepts a natural language description and helps the user arrive at a well-typed formal statement. The critical first step — getting from "I want to prove that every continuous function on a compact set is bounded" to a valid Coq `Theorem` declaration with the right types, quantifiers, and imports — has no tool support at all.

The result is that users who know exactly what they want to prove still cannot get started. The formalization process feels like translating between two foreign languages at once, and most people give up before they produce a single well-typed statement.

## Solution

Formalization Assistance provides a `/formalize` command that accepts a natural language description of a theorem and walks the user through the complete formalization process in a single conversational session.

### From Natural Language to Formal Statement

The user describes what they want to prove in plain English or mathematical prose. Claude interprets the mathematical intent, identifies the relevant Coq types and propositions, and produces a candidate formal statement. Before presenting it, Claude checks the statement against the active Coq environment to ensure it is syntactically valid and well-typed. The user never sees a suggestion that Coq would reject.

When the description is ambiguous or underspecified, Claude asks clarifying questions rather than guessing. When the user has only a partial description — "associativity of append for lists" rather than a fully elaborated theorem — Claude infers the missing pieces from context and explains what was inferred so the user can confirm or correct.

### Lemma Discovery

Before suggesting a formal statement, Claude searches the loaded libraries and the current project for existing lemmas relevant to the user's described theorem. Each result comes with an explanation of why it is relevant: whether it already states the user's theorem, generalizes it, or would be useful as a building block in the proof. If the theorem has already been formalized, the user learns this immediately rather than re-deriving a known result.

The search also identifies which libraries and imports are needed, so the user does not have to track down dependencies manually.

### Interactive Proof Building

Once the user accepts a formal statement, Claude opens a proof session and helps build the proof interactively. At each step, Claude suggests tactics informed by both the current proof state and the user's original mathematical description of the theorem. Suggestions come with explanations of what each tactic does and why it is appropriate — the user learns proof technique alongside the specific proof.

For routine goals, Claude attempts automated strategies first so that mechanical subgoals are discharged without the user's intervention. When a proof step fails, Claude explains the failure in terms of the mathematical content rather than presenting a raw Coq error message, and suggests alternative approaches.

### Iterative Refinement

The suggested formal statement will not always match the user's intent on the first try. When it does not, the user describes the needed correction in natural language and Claude produces a revised statement, maintaining context across multiple rounds of feedback. Every revision is type-checked before it is presented. The conversation converges on the correct formalization without the user needing to edit Coq syntax directly.

## Scope

Formalization Assistance provides:

- A `/formalize` slash command that orchestrates the formalization workflow as a guided dialogue
- Natural language input for describing theorems, lemmas, and definitions
- Search for existing relevant lemmas with explanations of relevance
- Candidate formal Coq statements that are type-checked before being presented
- Iterative refinement of the formal statement through natural language feedback
- Interactive proof building with tactic suggestions grounded in the mathematical intent
- Automated proving attempts on goals amenable to existing automation
- Import and dependency suggestions based on the libraries where relevant lemmas were found
- Explanations of proof failures in mathematical terms

Formalization Assistance does not provide:

- Batch formalization of entire papers or textbooks — each session focuses on a single theorem
- Formal verification that the natural language description and the formal statement are semantically equivalent — the user is the arbiter of correctness
- New Coq tactics or automation procedures — it composes existing tools
- Proof visualization (see [Proof Visualization Widgets](proof-visualization-widgets.md))
- Training or fine-tuning of ML models for formalization tasks

---

## Design Rationale

### Why a slash command rather than a new tool

The formalization workflow is inherently multi-step and conversational: interpret the user's intent, search for relevant results, propose a statement, refine it, then build the proof. No single tool invocation can capture this sequence. A slash command lets Claude orchestrate multiple existing tools — lemma search, vernacular introspection, proof interaction, hammer automation — in a guided dialogue that adapts to the user's responses at each stage. The tools provide the primitives; the slash command provides the script that ties them together into a coherent experience.

### Why search before suggesting a statement

Searching for existing lemmas before generating a candidate statement serves two purposes. First, it prevents the user from re-formalizing a result that already exists in their loaded libraries. Second, the search results give Claude better context for constructing the formal statement — knowing what types, naming conventions, and proof patterns the relevant libraries use leads to suggestions that integrate naturally with the user's development rather than standing apart from it.

### Why type-check before presenting

A formal statement that Coq rejects is worse than no suggestion at all: it wastes the user's time and erodes trust. By checking every candidate statement against the active Coq environment before presenting it, the workflow guarantees that the user's first interaction with the formal statement is productive — they evaluate whether it captures their intent, not whether it compiles. This is especially important for newcomers who cannot easily diagnose type errors on their own.

### Why explain in mathematical terms

The target audience includes mathematicians, students, and developers who think in mathematical concepts rather than Coq internals. When a tactic fails because of a universe inconsistency or a missing coercion, the raw Coq error message is opaque to most users. Translating errors and proof steps into the language of the user's original description keeps the conversation grounded in the domain the user understands. The user learns what went wrong mathematically, not just syntactically, and can adjust their approach accordingly.

### Why support partial descriptions

Mathematicians rarely state theorems in full formal detail in conversation. They say "associativity of append" and expect the listener to fill in the quantifiers, types, and variable names. Requiring a complete and precise natural language description before Claude can help would impose a formality burden that defeats the purpose of the tool. By accepting partial descriptions and inferring the rest from context — the current file, loaded libraries, naming conventions — the workflow meets users where they are and makes the first interaction as low-friction as possible.

---

## Acceptance Criteria

### Describe a Theorem in Natural Language

**Priority:** P0
**Stability:** Stable

- GIVEN the `/formalize` command is invoked WHEN the user provides a natural language description of a theorem THEN Claude acknowledges the intent and begins the formalization workflow
- GIVEN a natural language description WHEN it is ambiguous or underspecified THEN Claude asks clarifying questions before suggesting a formal statement
- GIVEN a natural language description that references standard mathematical concepts WHEN Claude processes it THEN Claude correctly identifies the relevant Coq types, propositions, and quantifiers

**Traces to:** RFA-P0-1

### Receive a Candidate Formal Statement

**Priority:** P0
**Stability:** Stable

- GIVEN a natural language theorem description WHEN Claude generates a candidate statement THEN the statement is syntactically valid Coq
- GIVEN a generated candidate statement WHEN it is checked against the active Coq environment THEN it is well-typed (no unresolved references or type errors)
- GIVEN a candidate statement WHEN it is presented to the user THEN Claude explains how each part of the formal statement corresponds to the natural language description

**Traces to:** RFA-P0-1, RFA-P0-5

### Validate the Formal Statement Against the Coq Environment

**Priority:** P0
**Stability:** Stable

- GIVEN a candidate formal statement WHEN Claude generates it THEN Claude submits it to the Coq environment via the proof interaction protocol for type-checking before presenting it
- GIVEN a candidate statement that fails type-checking WHEN the error is returned THEN Claude revises the statement and retries, or explains the issue to the user
- GIVEN a candidate statement that passes type-checking WHEN it is presented to the user THEN it is marked as verified well-typed

**Traces to:** RFA-P0-5

### Refine the Statement Through Dialogue

**Priority:** P1
**Stability:** Stable

- GIVEN a candidate statement that does not match the user's intent WHEN the user describes the needed correction in natural language THEN Claude produces a revised statement incorporating the feedback
- GIVEN an iterative refinement dialogue WHEN the user provides multiple rounds of feedback THEN Claude maintains context across rounds and does not regress on previously resolved issues
- GIVEN a refinement request WHEN the revised statement is generated THEN it is type-checked before being presented, just like the initial suggestion

**Traces to:** RFA-P1-1

### Search for Relevant Existing Lemmas

**Priority:** P0
**Stability:** Stable

- GIVEN a natural language theorem description WHEN the `/formalize` workflow begins THEN Claude searches loaded libraries and the current project for relevant lemmas before suggesting a formal statement
- GIVEN a search for relevant lemmas WHEN results are found THEN at least the top 5 most relevant results are presented
- GIVEN a search for relevant lemmas WHEN no relevant results are found THEN Claude explicitly states that no existing formalization was found and proceeds to suggest a new statement

**Traces to:** RFA-P0-2

### Explain Relevance of Search Results

**Priority:** P0
**Stability:** Stable

- GIVEN a set of lemma search results WHEN they are presented to the user THEN each result includes a natural language explanation of its relevance to the described theorem
- GIVEN a search result WHEN the lemma is a direct match or generalization of the user's theorem THEN Claude highlights this explicitly (e.g., "this lemma already states your theorem" or "this is a more general version")
- GIVEN a search result WHEN the lemma is a supporting result needed in the proof THEN Claude explains how it could be used

**Traces to:** RFA-P0-6

### Suggest Required Imports

**Priority:** P1
**Stability:** Stable

- GIVEN a candidate formal statement that references library definitions WHEN the statement is presented THEN Claude includes the necessary `Require Import` statements
- GIVEN relevant lemmas found during search WHEN they come from specific libraries THEN the import statements for those libraries are included in the suggestion
- GIVEN suggested imports WHEN they are applied to the Coq environment THEN the formal statement type-checks successfully

**Traces to:** RFA-P1-2

### Initiate a Proof Session for the Accepted Statement

**Priority:** P0
**Stability:** Stable

- GIVEN a formal statement that the user has accepted WHEN the user indicates they want to prove it THEN Claude opens a proof session for that statement via the proof interaction protocol
- GIVEN a proof session is opened WHEN the initial proof state is available THEN Claude displays the goal and context to the user
- GIVEN a formal statement with required imports WHEN the proof session is initiated THEN the imports are loaded before the statement is introduced

**Traces to:** RFA-P0-3

### Suggest Tactic Steps Based on Proof State and Intent

**Priority:** P0
**Stability:** Stable

- GIVEN an open proof goal WHEN Claude suggests a tactic step THEN the suggestion is accompanied by a natural language explanation of what the tactic does and why it is appropriate
- GIVEN an open proof goal WHEN Claude suggests a tactic THEN the tactic is informed by both the current proof state and the user's original natural language description of the theorem
- GIVEN a suggested tactic that the user applies WHEN it produces subgoals THEN Claude explains the resulting subgoals in terms of the overall proof strategy

**Traces to:** RFA-P0-4

### Attempt Automated Proof Strategies

**Priority:** P1
**Stability:** Stable

- GIVEN an open proof goal during the proof-building phase WHEN Claude evaluates the goal THEN it first attempts automated strategies (e.g., `hammer`, `sauto`, `auto`, `omega`) before suggesting manual tactic steps
- GIVEN an automated strategy that succeeds WHEN the result is returned THEN Claude reports the proof script and explains what it does
- GIVEN automated strategies that all fail WHEN Claude falls back to manual suggestions THEN it explains briefly why automation did not work (e.g., "this goal appears to require case analysis that the automated tactics cannot discover")

**Traces to:** RFA-P1-3

### Explain Proof Failures in Mathematical Terms

**Priority:** P1
**Stability:** Draft

- GIVEN a tactic that fails WHEN the Coq error is returned THEN Claude translates the error into a natural language explanation referencing the mathematical concepts involved
- GIVEN a tactic failure due to a type mismatch WHEN Claude explains the failure THEN it identifies which mathematical objects have incompatible types and why
- GIVEN a tactic failure WHEN Claude explains it THEN Claude also suggests an alternative tactic or approach

**Traces to:** RFA-P1-4

### Complete a Partial Theorem Description

**Priority:** P1
**Stability:** Draft

- GIVEN a partial natural language description (e.g., "the associativity of append for lists") WHEN Claude processes it THEN Claude infers the full statement including the universally quantified variables and the correct types
- GIVEN a partial description WHEN Claude completes it THEN Claude explains what was inferred and asks the user to confirm before proceeding
- GIVEN a partial description in the context of a Coq file WHEN Claude processes it THEN Claude uses the file's existing definitions and imports to guide the completion

**Traces to:** RFA-P1-5

### Suggest Alternative Formalizations

**Priority:** P2
**Stability:** Draft

- GIVEN a natural language theorem description WHEN there are multiple reasonable formalizations (e.g., using `Prop` vs `bool`, bundled vs unbundled structures, classical vs constructive) THEN Claude presents at least two alternatives with trade-off explanations
- GIVEN multiple formalization alternatives WHEN the user selects one THEN the workflow proceeds with the selected formalization
- GIVEN alternatives WHEN they are presented THEN Claude explains the practical consequences of each choice (e.g., "the classical version requires the excluded middle axiom")

**Traces to:** RFA-P2-1
