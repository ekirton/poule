# Setoid Rewriting Assistant

When `setoid_rewrite` fails with "Unable to satisfy Proper constraint", Coq dumps a wall of existential variables and substitution contexts that tells the user almost nothing about what went wrong. The actual problem is usually simple — a single function lacks a `Proper` instance for a specific relation — but extracting that answer from the error requires expert knowledge of three interacting systems: generalized rewriting, the `Proper`/`respectful` combinator vocabulary, and typeclass resolution. The Setoid Rewriting Assistant closes this gap: it identifies the missing morphism instance, generates the `Instance Proper ...` declaration with the correct signature, and checks whether existing instances make the declaration unnecessary. It also catches the common case where `rewrite` fails under a binder and the user does not know that `setoid_rewrite` exists.

---

## Problem

Coq's generalized rewriting framework lets users rewrite with custom equivalence relations — not just Leibniz equality — by requiring that every function in the rewrite context is a proper morphism: it maps related inputs to related outputs. This is declared via `Instance Proper (R1 ==> R2 ==> ... ==> Rout) f`, where `==>` (`respectful`) builds the relation signature. When an instance is missing, `setoid_rewrite` fails. The error message is the first problem: it shows raw evar contexts like `?X13==[A B H |- relation Prop]` that are meaningless to most users, with no plain-language indication of which function needs an instance or what the instance signature should be.

Even when users understand that a `Proper` instance is needed, writing the declaration is hard. The `respectful` combinator is not intuitive: `Proper (R ==> S ==> T) f` means "if the first arguments are R-related and the second arguments are S-related, then the results are T-related", but this reading is not obvious from the syntax. Users must determine the correct relation for each argument position and the output, get the variance right (covariant `==>` vs. contravariant `-->`), and handle higher-order cases involving `pointwise_relation` or `forall_relation`. The boilerplate burden scales with the number of custom functions in the development.

A separate but related trap: users whose `rewrite` fails inside a `forall`, `exists`, or `fun` do not know that `rewrite` fundamentally cannot look inside binders. The error — "Found no subterm matching ..." — gives no hint that `setoid_rewrite` is the right tool. This is a pure discoverability problem, and it trips up even experienced Coq users who have never needed to rewrite under a binder before.

## Solution

Claude interprets the error, identifies the missing piece, generates the fix, and explains the concepts — turning a multi-step diagnostic task that requires expert knowledge into a single conversational exchange.

### Failure Diagnosis

When the user reports a `setoid_rewrite` failure, Claude parses the error to identify the specific function that lacks a `Proper` instance and the relation signature it needs. The answer is presented in plain language: "Function `union` needs a `Proper` instance mapping `eq_set`-related arguments to `eq_set`-related results." When multiple instances are missing, Claude lists all of them. When the root cause is not a missing `Proper` instance but a missing `Equivalence` or `PreOrder` declaration for the base relation itself, Claude identifies that as the root cause — there is no point declaring `Proper` instances if the relation is not registered.

Claude also catches the binder case: when `rewrite` fails with "Found no subterm matching ..." and the target appears under a quantifier, Claude suggests `setoid_rewrite` and explains why `rewrite` cannot look inside binders. It checks whether the standard library already provides the necessary `Proper` instances for the enclosing binder (e.g., `all_iff_morphism` for `forall` with `iff`) so the user knows whether `setoid_rewrite` will work immediately or whether additional instances are needed.

### Instance Generation

Once the missing instance is identified, Claude generates the `Instance Proper ...` declaration with the correct `respectful` signature. The declaration is a skeleton — it opens the proof obligation for the user to complete — because the proof depends on the function's semantics, which Claude cannot verify. The signature, however, is the hard part: getting the right number of `==>` arrows, the right relation at each position, and the right variance. Claude handles this mechanically from the function's type and the context's relation requirements.

Before suggesting a new instance, Claude checks whether one already exists. Many `setoid_rewrite` failures are caused by missing imports rather than genuinely missing instances. The standard library provides `Proper` instances for logical connectives and quantifiers in `Coq.Classes.Morphisms_Prop`; MathComp, std++, and other libraries provide domain-specific instances. Claude queries the environment (via `Print Instances`, `Search Proper`) and recommends importing an existing instance when one is available, saving the user from writing a duplicate declaration.

### Explanation

The `Proper`/`respectful` vocabulary is a prerequisite for users to understand what the assistant generates and to write their own instances in the future. Claude translates signatures into plain English on request: `Proper (eq ==> eq_set ==> eq_set) union` becomes "if the first arguments are Leibniz-equal and the second arguments are `eq_set`-related, then the results are `eq_set`-related." For binder cases, Claude explains `pointwise_relation` ("the relation is lifted pointwise: two functions are related if they produce related results for every input") and `forall_relation` (the dependent variant for dependent products).

### Proof Assistance

After generating the instance declaration, Claude suggests how to prove the obligation. For simple compositional cases, `solve_proper` or `f_equiv` often works automatically — Claude tries these first. For cases that require manual proof, Claude suggests the standard opening (`unfold Proper, respectful; intros`) and identifies whether the proof reduces to applying `Proper` instances of the functions called by the function being declared. This does not extend to completing the proof — only to suggesting a strategy that gets the user started.

## Scope

The Setoid Rewriting Assistant provides:

- Diagnosis of `setoid_rewrite` failures: identifying the missing `Proper` instance by function name and relation signature
- Suggestion of `setoid_rewrite` when `rewrite` fails under binders, with explanation
- Generation of `Instance Proper ...` declaration skeletons with correct `respectful` signatures
- Checking existing instances (standard library and loaded modules) before suggesting new declarations
- Detection of missing `Equivalence`/`PreOrder` instances as root causes
- Plain-language explanation of `Proper`, `respectful`, `pointwise_relation`, and `forall_relation`
- Proof strategy suggestions for `Proper` obligations (`solve_proper`, `f_equiv`, manual unfolding)

The Setoid Rewriting Assistant does not provide:

- Modifications to Coq's setoid rewriting engine or error messages
- Automatic completion of `Proper` proof obligations — it generates the skeleton and suggests a strategy, not the proof body
- A standalone morphism database — it queries Coq's typeclass system at runtime
- IDE plugins — capabilities are accessed via Claude Code's MCP integration
- Support for rewriting frameworks outside Coq's generalized rewriting (e.g., Lean's `simp`, Isabelle's transfer)

---

## Design Rationale

### Why check existing instances before generating new ones

A significant fraction of `setoid_rewrite` failures are import problems, not genuinely missing instances. The standard library provides `Proper` instances for all logical connectives and quantifiers via `Morphisms_Prop`; mature libraries like std++ and MathComp provide hundreds more. Generating a new instance when one already exists wastes the user's time and creates a duplicate that may conflict with the original. Checking first is the difference between "add `Require Import Coq.Classes.Morphisms_Prop`" and "write and prove a 15-line instance declaration" — an order-of-magnitude reduction in effort for the common case.

### Why generate skeletons rather than complete proofs

The `Proper` proof obligation depends on the function's semantics: it requires showing that the function preserves the relation, which is a domain-specific fact that cannot be verified without understanding what the function does. Generating a complete proof would require Claude to reason about the function's implementation, which is error-prone and could produce proofs that type-check only by accident. The skeleton-plus-strategy approach is honest: it does the mechanical part (the signature) correctly and gives the user a starting point for the semantic part (the proof) without pretending to know something it does not.

### Why catch the `rewrite`-under-binders case

This is arguably the highest-leverage single intervention in the feature. The "Found no subterm matching ..." error under a `forall` is a pure discoverability problem: the fix is trivial (`setoid_rewrite` instead of `rewrite`) but the error message gives absolutely no hint. Users report searching for hours, trying `simpl`, `unfold`, `change`, and manual `assert` before discovering `setoid_rewrite` exists. Catching this pattern and suggesting the right tactic costs almost nothing to implement and saves disproportionate user frustration.

### Why explain the vocabulary rather than hide it

An assistant that generates `Proper` instances without ever explaining what `Proper` and `respectful` mean would make users dependent on the tool. Explaining the vocabulary — even briefly — builds the user's ability to read and write instances independently. This matters because real developments need dozens of `Proper` instances, and the user will inevitably encounter cases the assistant does not handle perfectly. The goal is to make the user fluent, not to create a permanent dependency.

### Why this feature synergizes with typeclass debugging

Setoid rewriting failures are, at their core, typeclass resolution failures: `setoid_rewrite` asks the typeclass engine to find a `Proper` instance, and the engine fails. The typeclass debugging feature (resolution tracing, instance listing, failure explanation) provides the diagnostic infrastructure that this feature builds on. When the setoid rewriting assistant needs to determine why a `Proper` instance was not found — was it missing, was it present but with the wrong signature, did resolution try it but fail on a sub-goal? — it can leverage the typeclass debugging tools for the answer.

## Acceptance Criteria

### Failure Diagnosis

**Priority:** P0
**Stability:** Stable

- GIVEN a `setoid_rewrite` failure message referencing unsatisfied `Proper` constraints WHEN diagnosis is requested THEN it identifies the specific function and the expected relation signature in plain language (e.g., "Function `union` needs a `Proper` instance mapping `eq_set`-related arguments to `eq_set`-related results")
- GIVEN a failure involving multiple missing instances WHEN diagnosis is requested THEN it lists all missing instances, not just the first one
- GIVEN a failure where the base relation itself is not registered WHEN diagnosis is requested THEN it identifies that the relation lacks an `Equivalence` (or `PreOrder`) instance and flags this as the root cause
- GIVEN a `rewrite` failure where the target subterm appears under a `forall`, `exists`, or `fun` WHEN diagnosis is requested THEN it explains that `rewrite` cannot look inside binders and suggests `setoid_rewrite` as the alternative
- GIVEN the suggestion to use `setoid_rewrite` WHEN it is presented THEN it notes any `Proper` instances that may be needed and checks whether the standard library already provides them (via `Morphisms_Prop`)
- GIVEN a `rewrite` failure where the subterm genuinely does not appear in the goal WHEN diagnosis is requested THEN it does not incorrectly suggest `setoid_rewrite`

**Traces to:** R-SR-P0-1, R-SR-P0-4

### Instance Generation

**Priority:** P0
**Stability:** Stable

- GIVEN the function name, its type signature, and the target relation WHEN generation is requested THEN it produces a syntactically correct `Instance Proper (R1 ==> R2 ==> ... ==> Rout) f` declaration
- GIVEN a function with `n` arguments WHEN the signature is generated THEN each argument position has the correct relation (matching the user's equivalence relation for the relevant type)
- GIVEN the generated declaration WHEN the user pastes it into their development THEN it is accepted by Coq and opens the correct proof obligation
- GIVEN a missing `Proper` instance for a standard-library function (e.g., `and`, `or`, `forall`) WHEN diagnosis is requested THEN it identifies the existing instance in `Coq.Classes.Morphisms_Prop` or `Coq.Classes.Morphisms` and suggests importing it
- GIVEN a missing `Proper` instance for a user-defined function WHEN no existing instance is found THEN it confirms that a new instance must be declared
- GIVEN an existing instance with a compatible but not identical signature WHEN it is found THEN it explains the relationship and whether it suffices

**Traces to:** R-SR-P0-2, R-SR-P0-3

### Explanation and Education

**Priority:** P1
**Stability:** Stable

- GIVEN a `Proper` signature like `Proper (eq ==> eq_set ==> eq_set) union` WHEN explanation is requested THEN it translates to: "If the first arguments are Leibniz-equal and the second arguments are `eq_set`-related, then the results are `eq_set`-related"
- GIVEN a signature involving `-->` (contravariant) WHEN explanation is requested THEN it correctly explains the direction reversal
- GIVEN a signature involving `pointwise_relation` WHEN explanation is requested THEN it explains that the relation is lifted pointwise to function types
- GIVEN a rewrite target under `forall` WHEN explanation is requested THEN it explains that `forall` is a morphism from `pointwise_relation A iff` to `iff` and shows the standard-library instance `all_iff_morphism`
- GIVEN a rewrite target under a dependent product WHEN explanation is requested THEN it explains the need for `forall_relation` instead of `pointwise_relation` and shows the signature pattern
- GIVEN a rewrite target under a custom binder (e.g., monadic bind) WHEN explanation is requested THEN it explains how to declare a `Proper` instance for the binder using `pointwise_relation`

**Traces to:** R-SR-P1-1, R-SR-P1-2

### Proof Assistance

**Priority:** P1
**Stability:** Stable

- GIVEN a `Proper` proof obligation WHEN strategy is requested THEN it suggests the standard opening (`unfold Proper, respectful; intros`) and identifies whether `solve_proper` or `f_equiv` can close the goal automatically
- GIVEN a `Proper` obligation that `solve_proper` cannot handle WHEN strategy is requested THEN it suggests manual proof steps based on the structure of the function (e.g., "unfold `f`, then use the `Proper` instances of the functions it calls")
- GIVEN a simple compositional `Proper` obligation WHEN `solve_proper` succeeds THEN it recommends using `solve_proper` as the complete proof
- GIVEN a relation used in a `Proper` context that has no `Equivalence` or `PreOrder` instance WHEN diagnosis is requested THEN it identifies the missing relational instance as the root cause
- GIVEN the missing relational instance WHEN generation is requested THEN it produces an `Instance Equivalence my_rel` (or `PreOrder`) declaration skeleton with `reflexivity`, `symmetry`, and `transitivity` obligations
- GIVEN a relation that is only a preorder (not symmetric) WHEN diagnosis is requested THEN it suggests `PreOrder` rather than `Equivalence` and notes the implications for rewrite direction

**Traces to:** R-SR-P1-3, R-SR-P1-4

### Bulk Analysis

**Priority:** P2
**Stability:** Draft

- GIVEN a Coq module or file WHEN morphism audit is requested THEN it identifies all functions used in contexts where `setoid_rewrite` might be applied and reports which ones lack `Proper` instances
- GIVEN the audit report WHEN it lists missing instances THEN each entry includes the function name, the expected relation signature, and the location where the function is used in a rewrite context
- GIVEN a function used in a contravariant position (e.g., as a hypothesis in an implication) WHEN instance generation is requested THEN it uses `-->` for the contravariant argument rather than defaulting to `==>`
- GIVEN a function used in both covariant and contravariant positions WHEN instance generation is requested THEN it suggests the most general variance that works in both contexts, or recommends declaring separate instances
- GIVEN a `Proper` instance for the right function but wrong relation WHEN diagnosis is requested THEN it identifies the mismatch (e.g., "Instance exists for `eq` but the rewrite context needs `equiv`")
- GIVEN a variance mismatch WHEN diagnosis is requested THEN it explains the expected variance and suggests declaring an additional instance with the correct variance

**Traces to:** R-SR-P2-1, R-SR-P2-2, R-SR-P2-3
