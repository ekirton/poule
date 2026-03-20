# Setoid Rewriting Assistant

When `setoid_rewrite` fails with "Unable to satisfy Proper constraint", Coq dumps a wall of existential variables and substitution contexts that tells the user almost nothing about what went wrong. The actual problem is usually simple — a single function lacks a `Proper` instance for a specific relation — but extracting that answer from the error requires expert knowledge of three interacting systems: generalized rewriting, the `Proper`/`respectful` combinator vocabulary, and typeclass resolution. The Setoid Rewriting Assistant closes this gap: it identifies the missing morphism instance, generates the `Instance Proper ...` declaration with the correct signature, and checks whether existing instances make the declaration unnecessary. It also catches the common case where `rewrite` fails under a binder and the user does not know that `setoid_rewrite` exists.

**Stories:** [Epic 1: Failure Diagnosis](../requirements/stories/setoid-rewriting-assistant.md#epic-1-failure-diagnosis), [Epic 2: Instance Generation](../requirements/stories/setoid-rewriting-assistant.md#epic-2-instance-generation), [Epic 3: Explanation and Education](../requirements/stories/setoid-rewriting-assistant.md#epic-3-explanation-and-education), [Epic 4: Proof Assistance](../requirements/stories/setoid-rewriting-assistant.md#epic-4-proof-assistance)

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
