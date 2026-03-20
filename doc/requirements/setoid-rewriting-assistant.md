# Setoid Rewriting Assistant — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context; question 4.7 in [common-questions.md](../background/common-questions.md).

## 1. Business Goals

Setoid rewriting is essential for Coq developments that use custom equivalence relations — sets represented as lists, constructive reals, quotient types, or any domain where Leibniz equality is too fine. When `setoid_rewrite` fails, users see cryptic error messages referencing undefined evars and unsatisfied `Proper` constraints that give no indication of which function is missing a morphism instance or what that instance should look like. Even experienced users spend significant time parsing error output, cross-referencing `Print Instances Proper`, and writing `Instance Proper ...` declarations with correct `respectful` (`==>`) signatures. The boilerplate burden is high and the concepts (Proper, respectful, pointwise_relation, forall_relation) are poorly documented outside a few blog posts and the reference manual.

A separate but related problem: users expect `rewrite` to work everywhere, but it cannot rewrite under binders (`forall`, `exists`, `fun`). The solution — switching to `setoid_rewrite` — is not discoverable from the error message "Found no subterm matching ...".

This initiative provides an assistant that diagnoses `setoid_rewrite` failures, identifies which morphism instance is missing, generates the `Instance Proper ...` declaration, and suggests existing standard-library instances when they suffice. The development cost is low because the underlying Coq commands (`Print Instances`, `Search Proper`, typeclass debugging) are mature; the value comes from interpreting their output and generating correct boilerplate.

**Success metrics:**
- Users can obtain a diagnosis and generated `Proper` instance for a setoid-rewriting failure through a single natural-language request to Claude
- Claude correctly identifies the missing morphism instance (function name and relation signature) in at least 80% of cases in a test corpus of common setoid-rewriting errors
- Generated `Instance Proper ...` declarations are syntactically correct and have the right `respectful` signature, leaving only the proof obligation for the user
- When existing standard-library instances suffice, Claude identifies them instead of suggesting the user write a new one

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers using custom equivalence relations | Diagnose `setoid_rewrite` failures and get the correct `Proper` instance without manual error parsing | Primary |
| Developers working with mathematical structures (MathComp, Coquelicot, CoRN) | Understand which morphism instances their library provides and which they need to declare | Primary |
| Newcomers encountering setoid rewriting for the first time | Get plain-language explanations of what `Proper`, `respectful`, and `pointwise_relation` mean | Secondary |
| Users whose `rewrite` fails under binders | Learn that `setoid_rewrite` exists and what infrastructure it requires | Secondary |

---

## 3. Competitive Context

**Current state of Coq tooling:**
- `setoid_rewrite` error messages show raw evar contexts (`?X13==[A B H |- relation Prop]`) that are meaningless to most users. GitHub issue #6141 proposed improvements but the messages remain largely opaque.
- `Print Instances Proper` lists all registered `Proper` instances but produces a flat, unstructured list with no filtering. Users must manually scan for the relevant function and relation.
- `Set Typeclasses Debug` shows the full resolution trace but produces deeply nested, verbose output that requires expert knowledge to interpret.
- `solve_proper` and `f_equiv` automate proving `Proper` goals but do not help with diagnosing which instance is missing.

**Standard library coverage:**
- `Coq.Classes.Morphisms_Prop` provides `Proper` instances for logical connectives (`and`, `or`, `not`, `impl`) and quantifiers (`all`, `ex`) with `iff`
- `Coq.Classes.Morphisms` provides generic infrastructure but no domain-specific instances
- Users must write their own instances for domain-specific functions — this is the primary pain point

**Gap:** No existing tool diagnoses a setoid-rewriting failure, identifies the specific missing `Proper` instance, and generates the declaration. The error-to-fix path requires expert knowledge of three interacting systems (setoid rewriting, `Proper`/`respectful`, and typeclass resolution).

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R-SR-P0-1 | Given a `setoid_rewrite` failure, identify which function lacks a `Proper` instance and for which relation, presenting the answer in plain language (e.g., "Function `f` needs a `Proper` instance for relation `R` in its first argument and `S` in its output") |
| R-SR-P0-2 | Generate the `Instance Proper ...` declaration skeleton with the correct `respectful` (`==>`) signature, leaving the proof obligation for the user to complete |
| R-SR-P0-3 | Before suggesting a new instance, check whether a suitable `Proper` instance already exists in the environment (via `Print Instances` or `Search`) and recommend importing or using it instead |
| R-SR-P0-4 | When `rewrite` fails with "Found no subterm matching ..." inside a `forall`, `exists`, or `fun`, suggest switching to `setoid_rewrite` and explain why regular `rewrite` cannot look inside binders |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R-SR-P1-1 | Explain the `Proper`/`respectful` signature in plain language: translate `Proper (R1 ==> R2 ==> R3) f` into "f maps R1-related first arguments and R2-related second arguments to R3-related results" |
| R-SR-P1-2 | When the rewrite target is under a binder, explain the need for `pointwise_relation` or `forall_relation` and generate the appropriate instance with the correct signature |
| R-SR-P1-3 | Suggest proof strategies for the `Proper` obligation: `unfold Proper, respectful; intros`, or when applicable, `solve_proper` or `f_equiv` |
| R-SR-P1-4 | When the base relation is not registered as an equivalence, detect this and suggest declaring an `Equivalence` or `PreOrder` instance before the `Proper` instance |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R-SR-P2-1 | Given a module or file, audit all functions used in rewrite contexts and report which ones lack `Proper` instances — a bulk "morphism coverage" check |
| R-SR-P2-2 | Suggest contravariant (`-->`) or symmetric (`<==>`) signatures when the rewrite context requires them, not just the default covariant (`==>`) |
| R-SR-P2-3 | Detect when a `Proper` instance exists but with the wrong relation or variance, and suggest adjusting the instance or using `Proper` instance composition |

---

## 5. Scope Boundaries

**In scope:**
- Diagnosing `setoid_rewrite` failures and identifying missing `Proper` instances
- Generating `Instance Proper ...` declaration skeletons with correct signatures
- Checking existing instances before suggesting new ones
- Suggesting `setoid_rewrite` when `rewrite` fails under binders
- Explaining the `Proper`/`respectful`/`pointwise_relation` vocabulary in plain language
- Suggesting proof strategies for `Proper` obligations

**Out of scope:**
- Modifying Coq's setoid rewriting engine or error messages
- Automatically completing the `Proper` proof obligation (generating the skeleton is in scope; filling in the proof body is not)
- Building a standalone morphism database or registry beyond what Coq's typeclass system provides
- IDE plugin development — capabilities are accessed via Claude Code's MCP integration
- Supporting rewriting frameworks outside Coq's generalized rewriting (e.g., Lean's `simp` or `calc`)
