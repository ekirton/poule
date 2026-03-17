# User Stories: Proof Explanation and Teaching

Derived from [doc/requirements/proof-explanation.md](../proof-explanation.md).

---

## Epic 1: Step-by-Step Proof Explanation

### 1.1 Step Through a Proof

**As a** Coq newcomer using Claude Code,
**I want to** invoke `/explain-proof` on a theorem and have Claude step through the proof tactic by tactic,
**so that** I can see exactly what happens at each step instead of staring at an opaque proof script.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq file containing a completed proof WHEN `/explain-proof` is invoked with the theorem name THEN each tactic in the proof is executed sequentially and the proof state before and after each tactic is captured
- GIVEN a proof with N tactics WHEN the explanation is generated THEN exactly N steps are presented, one per tactic application
- GIVEN a theorem name that does not exist in the current file WHEN `/explain-proof` is invoked THEN a clear error is returned indicating the theorem was not found

**Traces to:** RPE-P0-1, RPE-P0-5

### 1.2 Explain Each Tactic in Natural Language

**As a** student in a formal methods course,
**I want** each tactic in the proof to be explained in plain English,
**so that** I can understand what it does without memorizing the Coq tactic reference manual.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a tactic step in the proof WHEN its explanation is presented THEN it includes a general description of what the tactic does (e.g., "intros moves hypotheses from the goal into the context") and a specific description of what it accomplished here (e.g., "this introduced the hypothesis n : nat and the induction hypothesis IHn")
- GIVEN a tactic that changes the number of goals WHEN its explanation is presented THEN the explanation notes how many goals exist before and after
- GIVEN a tactic that closes a goal WHEN its explanation is presented THEN the explanation confirms the goal was discharged and explains why

**Traces to:** RPE-P0-2

### 1.3 Display Proof State Evolution

**As a** Coq newcomer,
**I want to** see the goals and hypotheses before and after each tactic,
**so that** I can observe how the proof state transforms and build intuition for how tactics work.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a tactic step WHEN its explanation is presented THEN the current goal(s) and hypotheses are displayed both before and after the tactic fires
- GIVEN a tactic that introduces new hypotheses WHEN the proof state is displayed THEN the new hypotheses are clearly identified
- GIVEN a tactic that modifies the goal (e.g., rewrite, simpl) WHEN the proof state is displayed THEN the change in the goal is evident from comparing the before and after states

**Traces to:** RPE-P0-3

### 1.4 Handle Compound Tactics

**As a** student reading a proof that uses semicolons or tactical combinators,
**I want** compound tactics to be broken down and explained as a unit,
**so that** I understand the composite behavior rather than being confused by syntax I have not seen before.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a tactic of the form `tac1; tac2` WHEN its explanation is presented THEN the explanation describes that `tac1` is applied first and `tac2` is applied to all resulting subgoals
- GIVEN a tactic using `try` WHEN its explanation is presented THEN the explanation notes that the inner tactic is attempted but failure is silently caught
- GIVEN a tactic using `repeat` WHEN its explanation is presented THEN the explanation describes how many times the inner tactic was applied before it stopped

**Traces to:** RPE-P0-4

---

## Epic 2: Mathematical Intuition

### 2.1 Connect Tactics to Mathematical Reasoning

**As a** student learning formal verification,
**I want** the explanation to connect each tactic to the mathematical proof strategy it implements,
**so that** I can see the correspondence between formal Coq proofs and the informal proofs I learned in mathematics courses.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a tactic that applies induction WHEN its explanation is presented THEN it references the mathematical principle of induction, identifies the base case and inductive step, and explains what the induction hypothesis says
- GIVEN a tactic that applies a rewrite using a known lemma WHEN its explanation is presented THEN it explains the mathematical fact that the lemma captures and why substituting equals for equals is valid here
- GIVEN a tactic that performs case analysis WHEN its explanation is presented THEN it explains the proof-by-cases strategy and identifies what the distinct cases are

**Traces to:** RPE-P1-1

### 2.2 Explain Automation Tactics

**As a** newcomer encountering `auto`, `omega`, or `lia` for the first time,
**I want** the explanation to describe what the automation found and why it succeeded,
**so that** I understand that automation is not magic but is applying specific lemmas and strategies.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a tactic like `auto` that succeeds WHEN its explanation is presented THEN it describes the general search strategy (`auto` tries applying hypotheses and lemmas from hint databases) and, where possible, identifies which lemma or hypothesis it applied
- GIVEN a decision procedure like `lia` WHEN its explanation is presented THEN it explains that `lia` solves goals in linear integer arithmetic and describes the shape of the goal that made it applicable
- GIVEN an automation tactic that solves multiple subgoals WHEN its explanation is presented THEN it notes how many subgoals were closed and summarizes the approach for each

**Traces to:** RPE-P1-3

---

## Epic 3: Adjustable Detail Level

### 3.1 Brief Explanation Mode

**As an** experienced developer reviewing an unfamiliar proof,
**I want** a brief mode that gives me a one-line summary per tactic,
**so that** I can quickly understand the proof structure without reading a lengthy walkthrough.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the brief detail level is selected WHEN the explanation is generated THEN each tactic step is summarized in a single line (e.g., "Introduces n and IHn" or "Rewrites goal using plus_comm")
- GIVEN the brief detail level WHEN the explanation is generated THEN proof states are not displayed between steps
- GIVEN the brief detail level WHEN the explanation completes THEN a one-paragraph summary of the overall proof strategy is provided

**Traces to:** RPE-P1-2

### 3.2 Verbose Explanation Mode

**As an** educator preparing lecture materials,
**I want** a verbose mode that includes full mathematical context, alternative approaches, and pedagogical notes,
**so that** I can use the output as a basis for teaching without significant additional work.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN the verbose detail level is selected WHEN the explanation is generated THEN each tactic step includes: general tactic description, context-specific explanation, full proof state before and after, mathematical intuition, and notes on why this tactic was chosen over alternatives
- GIVEN the verbose detail level WHEN a key proof step is reached (e.g., induction, case analysis) THEN the explanation includes a pedagogical note explaining the proof strategy to a student audience
- GIVEN the verbose detail level WHEN the explanation completes THEN a detailed summary is provided covering the overall proof strategy, key lemmas used, proof patterns employed, and the logical structure of the argument

**Traces to:** RPE-P1-2, RPE-P1-4

---

## Epic 4: Proof Summary and Structure

### 4.1 Summarize the Overall Proof

**As a** student who has just read through a step-by-step explanation,
**I want** a summary at the end that describes the overall proof strategy and key steps,
**so that** I can consolidate my understanding and see the forest rather than just the trees.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a completed proof walkthrough WHEN the summary is presented THEN it describes the high-level proof strategy in one to three sentences (e.g., "This proof proceeds by induction on n, with the base case solved by reflexivity and the inductive step by rewriting with the induction hypothesis and simplifying")
- GIVEN a proof that uses named lemmas WHEN the summary is presented THEN the key lemmas are listed with a brief description of each
- GIVEN a proof that employs a recognizable pattern WHEN the summary is presented THEN the pattern is named and described (e.g., "This follows a standard induction-then-rewrite pattern")

**Traces to:** RPE-P1-4, RPE-P2-3

### 4.2 Export Explanation as Document

**As an** educator,
**I want to** export the generated explanation as a structured markdown document,
**so that** I can include it in course materials, handouts, or online resources.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a completed proof explanation WHEN export is requested THEN a markdown document is generated with headings for each tactic step, formatted proof states in code blocks, and narrative explanations in body text
- GIVEN an exported document WHEN it is rendered in a standard markdown viewer THEN it is readable and well-formatted without further editing
- GIVEN an exported document WHEN it is reviewed by an educator THEN it can serve as a starting point for teaching materials with minimal modifications

**Traces to:** RPE-P2-2
