# User Stories: Setoid Rewriting Assistant

Derived from [doc/requirements/setoid-rewriting-assistant.md](../setoid-rewriting-assistant.md).

---

## Epic 1: Failure Diagnosis

### 1.1 Identify Missing Proper Instance

**As a** Coq developer whose `setoid_rewrite` failed with "Unable to satisfy Proper constraint",
**I want** Claude to identify which function lacks a `Proper` instance and for which relation,
**so that** I know exactly what instance to declare without parsing cryptic evar output.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a `setoid_rewrite` failure message referencing unsatisfied `Proper` constraints WHEN diagnosis is requested THEN it identifies the specific function and the expected relation signature in plain language (e.g., "Function `union` needs a `Proper` instance mapping `eq_set`-related arguments to `eq_set`-related results")
- GIVEN a failure involving multiple missing instances WHEN diagnosis is requested THEN it lists all missing instances, not just the first one
- GIVEN a failure where the base relation itself is not registered WHEN diagnosis is requested THEN it identifies that the relation lacks an `Equivalence` (or `PreOrder`) instance and flags this as the root cause

**Traces to:** R-SR-P0-1

### 1.2 Suggest setoid_rewrite for Under-Binder Failures

**As a** Coq developer whose `rewrite` failed with "Found no subterm matching ..." inside a quantifier,
**I want** Claude to suggest switching to `setoid_rewrite` and explain why,
**so that** I learn about `setoid_rewrite` at the moment I need it rather than through documentation search.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a `rewrite` failure where the target subterm appears under a `forall`, `exists`, or `fun` WHEN diagnosis is requested THEN it explains that `rewrite` cannot look inside binders and suggests `setoid_rewrite` as the alternative
- GIVEN the suggestion to use `setoid_rewrite` WHEN it is presented THEN it notes any `Proper` instances that may be needed and checks whether the standard library already provides them (via `Morphisms_Prop`)
- GIVEN a `rewrite` failure where the subterm genuinely does not appear in the goal WHEN diagnosis is requested THEN it does not incorrectly suggest `setoid_rewrite`

**Traces to:** R-SR-P0-4

---

## Epic 2: Instance Generation

### 2.1 Generate Proper Instance Declaration

**As a** Coq developer who needs to declare a `Proper` instance for a custom function,
**I want** Claude to generate the `Instance Proper ...` declaration with the correct `respectful` signature,
**so that** I do not have to manually construct the `==>` chain — the hardest part of the declaration.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the function name, its type signature, and the target relation WHEN generation is requested THEN it produces a syntactically correct `Instance Proper (R1 ==> R2 ==> ... ==> Rout) f` declaration
- GIVEN a function with `n` arguments WHEN the signature is generated THEN each argument position has the correct relation (matching the user's equivalence relation for the relevant type)
- GIVEN the generated declaration WHEN the user pastes it into their development THEN it is accepted by Coq and opens the correct proof obligation

**Traces to:** R-SR-P0-2

### 2.2 Check Existing Instances Before Suggesting New Ones

**As a** Coq developer who may already have the needed `Proper` instance in scope,
**I want** Claude to check whether a suitable instance already exists before suggesting I write a new one,
**so that** I do not duplicate work or miss a standard-library instance.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a missing `Proper` instance for a standard-library function (e.g., `and`, `or`, `forall`) WHEN diagnosis is requested THEN it identifies the existing instance in `Coq.Classes.Morphisms_Prop` or `Coq.Classes.Morphisms` and suggests importing it
- GIVEN a missing `Proper` instance for a user-defined function WHEN no existing instance is found THEN it confirms that a new instance must be declared
- GIVEN an existing instance with a compatible but not identical signature WHEN it is found THEN it explains the relationship and whether it suffices

**Traces to:** R-SR-P0-3

---

## Epic 3: Explanation and Education

### 3.1 Explain Proper/Respectful Signature

**As a** Coq developer encountering `Proper` and `respectful` for the first time,
**I want** Claude to translate a `Proper` signature into plain English,
**so that** I understand what the instance means without studying the `Morphisms` module.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a `Proper` signature like `Proper (eq ==> eq_set ==> eq_set) union` WHEN explanation is requested THEN it translates to: "If the first arguments are Leibniz-equal and the second arguments are `eq_set`-related, then the results are `eq_set`-related"
- GIVEN a signature involving `-->` (contravariant) WHEN explanation is requested THEN it correctly explains the direction reversal
- GIVEN a signature involving `pointwise_relation` WHEN explanation is requested THEN it explains that the relation is lifted pointwise to function types

**Traces to:** R-SR-P1-1

### 3.2 Explain Binder Rewriting Infrastructure

**As a** Coq developer who needs to rewrite under a `forall` or `exists`,
**I want** Claude to explain the `pointwise_relation` and `forall_relation` mechanism,
**so that** I understand what infrastructure is needed and can declare it.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a rewrite target under `forall` WHEN explanation is requested THEN it explains that `forall` is a morphism from `pointwise_relation A iff` to `iff` and shows the standard-library instance `all_iff_morphism`
- GIVEN a rewrite target under a dependent product WHEN explanation is requested THEN it explains the need for `forall_relation` instead of `pointwise_relation` and shows the signature pattern
- GIVEN a rewrite target under a custom binder (e.g., monadic bind) WHEN explanation is requested THEN it explains how to declare a `Proper` instance for the binder using `pointwise_relation`

**Traces to:** R-SR-P1-2

---

## Epic 4: Proof Assistance

### 4.1 Suggest Proof Strategy for Proper Obligation

**As a** Coq developer who has the `Proper` declaration but must prove the obligation,
**I want** Claude to suggest a proof strategy,
**so that** I can complete the proof efficiently.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a `Proper` proof obligation WHEN strategy is requested THEN it suggests the standard opening (`unfold Proper, respectful; intros`) and identifies whether `solve_proper` or `f_equiv` can close the goal automatically
- GIVEN a `Proper` obligation that `solve_proper` cannot handle WHEN strategy is requested THEN it suggests manual proof steps based on the structure of the function (e.g., "unfold `f`, then use the `Proper` instances of the functions it calls")
- GIVEN a simple compositional `Proper` obligation WHEN `solve_proper` succeeds THEN it recommends using `solve_proper` as the complete proof

**Traces to:** R-SR-P1-3

### 4.2 Detect Missing Equivalence Instance

**As a** Coq developer whose `setoid_rewrite` fails because the base relation is not registered,
**I want** Claude to detect that the relation lacks an `Equivalence` (or `PreOrder`) instance and generate it,
**so that** I fix the root cause before attempting to declare `Proper` instances.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a relation used in a `Proper` context that has no `Equivalence` or `PreOrder` instance WHEN diagnosis is requested THEN it identifies the missing relational instance as the root cause
- GIVEN the missing relational instance WHEN generation is requested THEN it produces an `Instance Equivalence my_rel` (or `PreOrder`) declaration skeleton with `reflexivity`, `symmetry`, and `transitivity` obligations
- GIVEN a relation that is only a preorder (not symmetric) WHEN diagnosis is requested THEN it suggests `PreOrder` rather than `Equivalence` and notes the implications for rewrite direction

**Traces to:** R-SR-P1-4

---

## Epic 5: Bulk Analysis

### 5.1 Audit Morphism Coverage

**As a** Coq library author maintaining a development with custom equivalence relations,
**I want** Claude to audit my module for functions that appear in rewrite contexts but lack `Proper` instances,
**so that** I can proactively declare all needed instances rather than discovering them one-at-a-time through errors.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a Coq module or file WHEN morphism audit is requested THEN it identifies all functions used in contexts where `setoid_rewrite` might be applied and reports which ones lack `Proper` instances
- GIVEN the audit report WHEN it lists missing instances THEN each entry includes the function name, the expected relation signature, and the location where the function is used in a rewrite context

**Traces to:** R-SR-P2-1

### 5.2 Suggest Variance Annotations

**As a** Coq developer declaring a `Proper` instance for a function used in both covariant and contravariant positions,
**I want** Claude to suggest the correct variance (`==>`, `-->`, or `<==>`) for each argument,
**so that** the instance works in all the contexts where the function appears.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a function used in a contravariant position (e.g., as a hypothesis in an implication) WHEN instance generation is requested THEN it uses `-->` for the contravariant argument rather than defaulting to `==>`
- GIVEN a function used in both covariant and contravariant positions WHEN instance generation is requested THEN it suggests the most general variance that works in both contexts, or recommends declaring separate instances

**Traces to:** R-SR-P2-2

### 5.3 Detect Mismatched Existing Instance

**As a** Coq developer whose `setoid_rewrite` fails despite a `Proper` instance existing,
**I want** Claude to detect that the existing instance has the wrong relation or variance,
**so that** I can fix or supplement it rather than spending time on a wild-goose chase.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a `Proper` instance for the right function but wrong relation WHEN diagnosis is requested THEN it identifies the mismatch (e.g., "Instance exists for `eq` but the rewrite context needs `equiv`")
- GIVEN a variance mismatch WHEN diagnosis is requested THEN it explains the expected variance and suggests declaring an additional instance with the correct variance

**Traces to:** R-SR-P2-3
