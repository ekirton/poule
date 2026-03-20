# User Stories: Convoy Pattern Assistant

Derived from [doc/requirements/convoy-pattern-assistant.md](../convoy-pattern-assistant.md).

---

## Epic 1: Failure Diagnosis

### 1.1 Diagnose Lost Dependent Equality

**As a** Coq developer whose `destruct` produced a proof state with missing equalities,
**I want** Claude to identify that index equalities were lost during case analysis,
**so that** I understand why my proof state is weaker than expected and can apply the correct fix.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof state where `destruct` was applied to a term of an indexed inductive type (e.g., `Fin n`, `vec T n`) WHEN diagnosis is requested THEN it identifies which index values were abstracted away and which hypotheses lost their connection to the destructed term
- GIVEN a proof state where `destruct` succeeded but a subsequent tactic fails because an expected equality is missing WHEN diagnosis is requested THEN it explains that `destruct` does not refine the types of free variables in scope and that the missing equality must be preserved explicitly
- GIVEN a proof state where no dependent-destruction issue exists WHEN diagnosis is requested THEN it reports that the proof state does not exhibit the dependent-matching problem

**Traces to:** R-CP-P0-1

### 1.2 Diagnose Ill-Typed Abstraction Error

**As a** Coq developer who received "Abstracting over ... leads to a term which is ill-typed",
**I want** Claude to explain what this error means in terms of my proof,
**so that** I understand the problem without needing to know Coq's internal match compilation.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the error message "Abstracting over the terms ... leads to a term which is ill-typed" WHEN explanation is requested THEN it identifies the match target, the abstracted indices, and the hypothesis or goal whose type became ill-typed after abstraction
- GIVEN the explanation WHEN it is read THEN it uses the names from the user's proof state (not internal variable names) and explains the problem in terms of the user's types and hypotheses

**Traces to:** R-CP-P0-1

---

## Epic 2: Technique Recommendation

### 2.1 Recommend Repair Technique

**As a** Coq developer who has been diagnosed with a dependent-destruction problem,
**I want** Claude to recommend the most appropriate repair technique for my situation,
**so that** I can fix my proof without researching the available options.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a dependent-destruction failure in tactic mode where the user has no axiom constraints WHEN a recommendation is requested THEN it recommends `revert`-before-`destruct` as the primary option and mentions `dependent destruction` as a quick alternative
- GIVEN a dependent-destruction failure where the user requires an axiom-free proof WHEN a recommendation is requested THEN it recommends `revert`-before-`destruct` or Equations `depelim` and does not recommend `dependent destruction`
- GIVEN a dependent-destruction failure in term mode (writing a `match` expression) WHEN a recommendation is requested THEN it recommends the convoy pattern with return-clause annotations
- GIVEN a simple inversion scenario with concrete constructor indices WHEN a recommendation is requested THEN it recommends `inversion` as the simplest option

**Traces to:** R-CP-P0-2

### 2.2 Identify Hypotheses to Revert

**As a** Coq developer who has been told to use `revert`-before-`destruct`,
**I want** Claude to tell me exactly which hypotheses I need to revert,
**so that** I can apply the technique without manually inspecting type dependencies.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a proof state with a term to destruct and other hypotheses whose types mention its indices WHEN revert analysis is requested THEN it lists exactly the hypotheses that must be reverted, in the correct order (innermost dependencies first)
- GIVEN a proof state where the goal itself depends on the destructed term's indices WHEN revert analysis is requested THEN it notes that the goal dependency is handled automatically by `destruct` and only lists hypotheses that need explicit `revert`
- GIVEN the list of hypotheses to revert WHEN the tactic sequence is generated THEN it produces a valid `revert H1 H2. destruct x.` command

**Traces to:** R-CP-P0-3

### 2.3 Warn About Axiom Dependencies

**As a** Coq developer maintaining an axiom-free development,
**I want** Claude to warn me when a suggested technique introduces axioms,
**so that** I can make an informed choice and preserve my development's axiom profile.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a recommendation of `dependent destruction` WHEN it is presented THEN it includes a warning that the proof will depend on `JMeq_eq` from `Coq.Logic.JMeq`
- GIVEN the axiom warning WHEN it is read THEN it explains that `JMeq_eq` is consistent but is not provable in Coq's core theory, and that `Print Assumptions` will show it
- GIVEN a recommendation of `revert`-before-`destruct` or Equations `depelim` WHEN it is presented THEN it confirms that the technique is axiom-free

**Traces to:** R-CP-P0-4

---

## Epic 3: Boilerplate Generation

### 3.1 Generate Convoy Pattern Term

**As a** Coq developer writing a dependent match expression,
**I want** Claude to generate the `match ... as ... in ... return ...` boilerplate with correct return-clause annotations,
**so that** I do not have to manually construct the return clause — the hardest part of the convoy pattern.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a match target, the dependent terms that must be "convoyed", and the desired result type WHEN generation is requested THEN it produces a syntactically valid `match` expression with `as`, `in`, and `return` clauses
- GIVEN the generated match expression WHEN it includes equality evidence THEN it applies the match to `eq_refl` to discharge the equality obligation
- GIVEN a generated convoy-pattern term WHEN the user pastes it into their development THEN it type-checks (assuming the user fills in the branch bodies correctly)

**Traces to:** R-CP-P1-1

### 3.2 Generate Revert/Destruct Tactic Sequence

**As a** Coq developer in tactic mode,
**I want** Claude to generate the complete `revert`/`destruct` tactic sequence,
**so that** I can apply the tactic-level convoy pattern without figuring out the right revert order.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the proof state analysis from story 2.2 WHEN tactic generation is requested THEN it produces a complete tactic sequence (e.g., `revert H1 H2. destruct x. intros H1 H2.`) that preserves all dependent information
- GIVEN the generated tactic sequence WHEN it is applied THEN the resulting subgoals contain properly refined types in each branch

**Traces to:** R-CP-P1-2

### 3.3 Generate Equations Definition

**As a** Coq developer who has the Equations plugin available,
**I want** Claude to generate an `Equations` function definition with the necessary `Derive` commands,
**so that** I can use clean dependent pattern matching without manual return-clause annotations.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a function that requires dependent pattern matching and the types involved WHEN generation is requested THEN it produces an `Equations` definition with correct pattern clauses
- GIVEN the generated definition WHEN it is inspected THEN it includes the necessary `Derive NoConfusion` and `Derive Signature` commands for the relevant inductive types
- GIVEN the Equations plugin is not available WHEN generation is requested THEN it reports that the plugin is required and suggests how to install it

**Traces to:** R-CP-P1-3

---

## Epic 4: Explanation

### 4.1 Explain the Convoy Pattern

**As a** Coq newcomer encountering dependent pattern matching for the first time,
**I want** Claude to explain the convoy pattern in plain language with a concrete example,
**so that** I understand the underlying mechanism rather than just applying a recipe.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a request to explain the convoy pattern WHEN the explanation is returned THEN it covers: why Coq's `match` only refines the return type (not free variables), what the `as`/`in`/`return` annotations do, and how adding dependent terms as function arguments in the return clause causes them to be refined in each branch
- GIVEN the explanation WHEN it includes an example THEN the example uses a concrete indexed type (e.g., `Fin n` or `vec T n`) and shows both the failing naive `destruct` and the working convoy-pattern fix
- GIVEN a user who knows Agda WHEN the explanation is returned THEN it notes that Agda performs this refinement automatically via unification, which is why the technique is not needed there

**Traces to:** R-CP-P1-4

---

## Epic 5: Proactive Detection

### 5.1 Detect Dependent-Destruction Problems Proactively

**As a** Coq developer stepping through a proof,
**I want** Claude to detect when my proof state shows signs of a dependent-destruction problem before I ask,
**so that** I am warned early and can apply the fix before going down a dead-end path.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof state where a `destruct` was just applied to a term of an indexed inductive type and the resulting subgoals contain hypotheses with freshly abstracted index variables WHEN the proof state is observed THEN Claude proactively suggests that dependent information may have been lost
- GIVEN a proactive suggestion WHEN the user dismisses it THEN Claude does not repeat the suggestion for the same proof state

**Traces to:** R-CP-P2-1

### 5.2 Suggest Decidable-Equality Optimization

**As a** Coq developer whose indices have decidable equality (e.g., `nat`, `bool`, `positive`),
**I want** Claude to suggest the axiom-free `Eqdep_dec` variant instead of `JMeq_eq`,
**so that** I can use `dependent destruction`-style automation without introducing axioms.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a dependent-destruction scenario where the index type has a decidable equality instance WHEN recommendations are presented THEN it mentions that `Eqdep_dec.eq_rect_eq_dec` can be used to avoid the `JMeq_eq` axiom
- GIVEN the suggestion WHEN it is applied THEN it produces an axiom-free proof (verified by `Print Assumptions`)

**Traces to:** R-CP-P2-2

### 5.3 Generate Reusable Elimination Lemma

**As a** Coq developer who frequently destructs the same indexed type,
**I want** Claude to generate a custom elimination lemma (e.g., `fin_case`) that I can reuse,
**so that** I avoid repeating the convoy-pattern boilerplate in every proof.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an indexed inductive type and a recurring destruction pattern WHEN generation is requested THEN it produces a standalone lemma with the appropriate dependent return type
- GIVEN the generated lemma WHEN it is used via `apply` or a thin Ltac wrapper THEN it provides the same benefit as the convoy pattern in a single tactic step

**Traces to:** R-CP-P2-3
