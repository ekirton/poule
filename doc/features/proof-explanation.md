# Proof Explanation and Teaching

Coq proofs are opaque by nature: a proof script is a sequence of tactic invocations that transform an invisible proof state, and the reader must mentally simulate each step to understand why the proof works. Proof Explanation and Teaching provides an `/explain-proof` slash command that walks through a completed proof tactic by tactic, explains each step in plain English, shows how the proof state evolves, and connects the formal manipulation to the underlying mathematical intuition. The result is a readable, pedagogically useful narrative that transforms "I can see it compiles, but I don't understand why it works" into genuine understanding.

---

## Problem

Today, understanding a Coq proof requires the very skills that newcomers have not yet developed. The user must know what each tactic does in general, infer what it accomplishes in the specific proof context, and mentally track how goals and hypotheses change at every step. Existing tools — CoqIDE, Proof General, Alectryon — can display the raw proof state at each point, but they offer no explanation. The user sees that `intros n IHn` was applied and that the goal changed, but nothing tells them *why* that tactic was chosen or how it relates to the mathematical argument being formalized.

This creates a steep learning curve for students, a tedious annotation burden for educators, and a comprehension barrier for developers reviewing unfamiliar proofs. The gap is not in proof state visibility — it is in the explanation layer that connects formal tactic applications to human-understandable reasoning. Filling that gap requires contextual interpretation of both the tactic and the proof state, which is exactly what an LLM excels at.

## Solution

The `/explain-proof` command takes a theorem or lemma name, steps through its proof, and produces a natural-language walkthrough that explains each tactic in context.

### Tactic-by-Tactic Explanation

For every tactic in the proof, the user sees what the tactic does in general ("intros moves hypotheses from the goal into the context"), what it accomplished in this specific proof ("this introduced the variable n and the induction hypothesis IHn"), and how the proof state changed as a result. Compound tactics — semicolons, `try`, `repeat` — are explained as composite operations so the user understands the combined effect rather than being confused by unfamiliar syntax.

### Proof State Evolution

Each step displays the goals and hypotheses before and after the tactic fires. New hypotheses are identified, changes to the goal are made evident, and goal creation or discharge is noted. The user can observe the proof state transforming step by step, building the same intuition that experienced Coq developers have internalized through years of practice.

### Mathematical Intuition

Beyond explaining what a tactic does mechanically, the command connects each step to the mathematical reasoning it implements. An induction tactic is not just "splitting the goal into subgoals" — it is applying the principle of mathematical induction on a specific variable, creating a base case and an inductive step with a named induction hypothesis. A rewrite is not just "substituting in the goal" — it is applying a known mathematical fact to transform one expression into an equivalent one. This bridges the gap between the formal proof and the informal mathematical argument that motivates it.

### Adjustable Detail Level

Different audiences need different levels of detail. A student working through a proof for the first time benefits from verbose explanations with full mathematical context and pedagogical notes. An experienced developer skimming an unfamiliar proof needs only a brief summary — one line per tactic — to understand the overall structure. The command supports multiple detail levels so the same proof can be explained at the depth that matches the reader.

### Proof Summary

After walking through every step, the command provides a high-level summary of the overall proof strategy: the approach taken (e.g., induction followed by rewriting), the key lemmas used, and any recognizable proof patterns employed. This helps the user see the forest after examining each tree, consolidating their step-by-step understanding into a coherent picture of the argument.

## Scope

Proof Explanation and Teaching provides:

- A `/explain-proof` slash command that walks through any completed Coq proof
- Natural-language explanation of each tactic, both in general and in context
- Proof state display (goals and hypotheses) before and after each step
- Mathematical intuition connecting tactics to the proof strategies they implement
- Explanation of automation tactics (`auto`, `omega`, `lia`) describing what they found and why they succeeded
- Adjustable detail levels from brief one-line summaries to verbose pedagogical walkthroughs
- A summary of overall proof strategy, key lemmas, and proof patterns after the walkthrough
- Export of the explanation as a structured document suitable for course materials

Proof Explanation and Teaching does not provide:

- Proof generation, repair, or search — it explains existing proofs, not write new ones
- Interactive tutoring with exercises, quizzes, or feedback loops
- Video or animated proof visualization
- Installation or management of Coq
- Modifications to Coq's proof engine or tactic language
- Translation of proofs between proof assistants

---

## Design Rationale

### Why a slash command rather than a tool

Explaining a proof is inherently a multi-step workflow: locate the theorem, step through its tactics one at a time, inspect the proof state at each point, and weave the results into a coherent narrative. This requires orchestration — the LLM must reason between each step about what to explain and how to frame it. A single MCP tool call cannot capture this kind of iterative, judgment-intensive process. A slash command lets Claude drive the workflow end to end, composing lower-level proof interaction tools as building blocks while applying its own reasoning to produce the explanation.

### Why this is a natural fit for an LLM

The raw information needed to explain a proof — the tactic name, the proof state before, the proof state after — is already available through proof interaction tools. What is missing is the interpretation: translating a formal state change into a sentence that a student can understand, connecting a tactic application to a mathematical concept, choosing the right level of detail for the audience. This is contextual language generation grounded in structured data, which is precisely where LLMs provide the most value. No static tool or template system can produce the same quality of contextual, adaptive explanation.

### Why adjustable detail matters

A single explanation style cannot serve all audiences. Newcomers need every step spelled out with mathematical context; experienced developers find that level of detail tedious and slow. Educators want verbose output they can edit into teaching materials; reviewers want brief output they can scan in seconds. Rather than choosing one audience and optimizing for it, adjustable detail levels let the same command serve the full spectrum of users. The default provides a balanced explanation suitable for most learners, while brief and verbose modes handle the ends of the spectrum.

### Why summarize at the end

Step-by-step explanations are valuable for understanding individual tactics, but they can obscure the overall proof strategy. A student who has just read through fifteen tactic explanations may understand each step but still not grasp the high-level argument. The closing summary addresses this by naming the proof strategy, listing the key lemmas, and identifying recognizable patterns — giving the user a mental framework to organize everything they just learned.

---

## Acceptance Criteria

### Step Through a Proof

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq file containing a completed proof WHEN `/explain-proof` is invoked with the theorem name THEN each tactic in the proof is executed sequentially and the proof state before and after each tactic is captured
- GIVEN a proof with N tactics WHEN the explanation is generated THEN exactly N steps are presented, one per tactic application
- GIVEN a theorem name that does not exist in the current file WHEN `/explain-proof` is invoked THEN a clear error is returned indicating the theorem was not found

**Traces to:** RPE-P0-1, RPE-P0-5

### Explain Each Tactic in Natural Language

**Priority:** P0
**Stability:** Stable

- GIVEN a tactic step in the proof WHEN its explanation is presented THEN it includes a general description of what the tactic does (e.g., "intros moves hypotheses from the goal into the context") and a specific description of what it accomplished here (e.g., "this introduced the hypothesis n : nat and the induction hypothesis IHn")
- GIVEN a tactic that changes the number of goals WHEN its explanation is presented THEN the explanation notes how many goals exist before and after
- GIVEN a tactic that closes a goal WHEN its explanation is presented THEN the explanation confirms the goal was discharged and explains why

**Traces to:** RPE-P0-2

### Display Proof State Evolution

**Priority:** P0
**Stability:** Stable

- GIVEN a tactic step WHEN its explanation is presented THEN the current goal(s) and hypotheses are displayed both before and after the tactic fires
- GIVEN a tactic that introduces new hypotheses WHEN the proof state is displayed THEN the new hypotheses are clearly identified
- GIVEN a tactic that modifies the goal (e.g., rewrite, simpl) WHEN the proof state is displayed THEN the change in the goal is evident from comparing the before and after states

**Traces to:** RPE-P0-3

### Handle Compound Tactics

**Priority:** P0
**Stability:** Stable

- GIVEN a tactic of the form `tac1; tac2` WHEN its explanation is presented THEN the explanation describes that `tac1` is applied first and `tac2` is applied to all resulting subgoals
- GIVEN a tactic using `try` WHEN its explanation is presented THEN the explanation notes that the inner tactic is attempted but failure is silently caught
- GIVEN a tactic using `repeat` WHEN its explanation is presented THEN the explanation describes how many times the inner tactic was applied before it stopped

**Traces to:** RPE-P0-4

### Connect Tactics to Mathematical Reasoning

**Priority:** P1
**Stability:** Stable

- GIVEN a tactic that applies induction WHEN its explanation is presented THEN it references the mathematical principle of induction, identifies the base case and inductive step, and explains what the induction hypothesis says
- GIVEN a tactic that applies a rewrite using a known lemma WHEN its explanation is presented THEN it explains the mathematical fact that the lemma captures and why substituting equals for equals is valid here
- GIVEN a tactic that performs case analysis WHEN its explanation is presented THEN it explains the proof-by-cases strategy and identifies what the distinct cases are

**Traces to:** RPE-P1-1

### Explain Automation Tactics

**Priority:** P1
**Stability:** Draft

- GIVEN a tactic like `auto` that succeeds WHEN its explanation is presented THEN it describes the general search strategy (`auto` tries applying hypotheses and lemmas from hint databases) and, where possible, identifies which lemma or hypothesis it applied
- GIVEN a decision procedure like `lia` WHEN its explanation is presented THEN it explains that `lia` solves goals in linear integer arithmetic and describes the shape of the goal that made it applicable
- GIVEN an automation tactic that solves multiple subgoals WHEN its explanation is presented THEN it notes how many subgoals were closed and summarizes the approach for each

**Traces to:** RPE-P1-3

### Brief Explanation Mode

**Priority:** P1
**Stability:** Stable

- GIVEN the brief detail level is selected WHEN the explanation is generated THEN each tactic step is summarized in a single line (e.g., "Introduces n and IHn" or "Rewrites goal using plus_comm")
- GIVEN the brief detail level WHEN the explanation is generated THEN proof states are not displayed between steps
- GIVEN the brief detail level WHEN the explanation completes THEN a one-paragraph summary of the overall proof strategy is provided

**Traces to:** RPE-P1-2

### Verbose Explanation Mode

**Priority:** P1
**Stability:** Draft

- GIVEN the verbose detail level is selected WHEN the explanation is generated THEN each tactic step includes: general tactic description, context-specific explanation, full proof state before and after, mathematical intuition, and notes on why this tactic was chosen over alternatives
- GIVEN the verbose detail level WHEN a key proof step is reached (e.g., induction, case analysis) THEN the explanation includes a pedagogical note explaining the proof strategy to a student audience
- GIVEN the verbose detail level WHEN the explanation completes THEN a detailed summary is provided covering the overall proof strategy, key lemmas used, proof patterns employed, and the logical structure of the argument

**Traces to:** RPE-P1-2, RPE-P1-4

### Summarize the Overall Proof

**Priority:** P1
**Stability:** Stable

- GIVEN a completed proof walkthrough WHEN the summary is presented THEN it describes the high-level proof strategy in one to three sentences (e.g., "This proof proceeds by induction on n, with the base case solved by reflexivity and the inductive step by rewriting with the induction hypothesis and simplifying")
- GIVEN a proof that uses named lemmas WHEN the summary is presented THEN the key lemmas are listed with a brief description of each
- GIVEN a proof that employs a recognizable pattern WHEN the summary is presented THEN the pattern is named and described (e.g., "This follows a standard induction-then-rewrite pattern")

**Traces to:** RPE-P1-4, RPE-P2-3

### Export Explanation as Document

**Priority:** P2
**Stability:** Draft

- GIVEN a completed proof explanation WHEN export is requested THEN a markdown document is generated with headings for each tactic step, formatted proof states in code blocks, and narrative explanations in body text
- GIVEN an exported document WHEN it is rendered in a standard markdown viewer THEN it is readable and well-formatted without further editing
- GIVEN an exported document WHEN it is reviewed by an educator THEN it can serve as a starting point for teaching materials with minimal modifications

**Traces to:** RPE-P2-2
