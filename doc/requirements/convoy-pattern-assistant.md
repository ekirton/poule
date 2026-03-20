# Convoy Pattern Assistant — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context; question 4.4 in [common-questions.md](../background/common-questions.md).

## 1. Business Goals

Dependent pattern matching is one of the most persistent sources of confusion for Coq users. When a user calls `destruct` on a term whose type index appears in other hypotheses or the goal, Coq silently discards the connection between the destructed term and the rest of the proof state. The user sees either a cryptic "Abstracting over ... leads to an ill-typed term" error, or — worse — a proof state where equalities have silently vanished. The fix requires one of several techniques (the convoy pattern, `dependent destruction`, `revert`-before-`destruct`, or the Equations plugin), but choosing the right one depends on context, axiom tolerance, and whether the user is in tactic mode or term mode. Knowledge about these techniques is scattered across CPDT, blog posts, Discourse threads, and Stack Overflow answers with no single authoritative guide.

This initiative provides an assistant that detects when `destruct` has lost dependent information, explains what went wrong, recommends the appropriate repair technique, and generates the required boilerplate. The value comes from bridging the gap between a confusing failure and the correct — but hard to discover — fix.

**Success metrics:**
- Users can obtain a diagnosis and recommended fix for a dependent-destruction failure through a single natural-language request to Claude, without needing to understand return-clause annotations or the convoy pattern
- Claude correctly classifies the failure mode (lost index equality, lost hypothesis dependency, ill-typed abstraction) and recommends an appropriate technique in at least 80% of cases in a test corpus
- When the convoy pattern or `revert`-before-`destruct` is recommended, Claude generates syntactically correct boilerplate that the user can paste into their proof script
- Claude warns about axiom implications (`JMeq_eq`) when recommending `dependent destruction`

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers working with indexed inductive types | Understand why `destruct` fails or loses information and get a working fix without manual research | Primary |
| Newcomers to dependent types in Coq | Get plain-language explanations of what dependent pattern matching is and why naive case analysis breaks | Primary |
| Users migrating from Agda or Lean | Understand why Coq does not automatically refine hypothesis types during pattern matching, and learn the Coq-specific workarounds | Secondary |
| Developers maintaining axiom-free developments | Know which techniques introduce axioms and which do not, so they can choose accordingly | Secondary |

---

## 3. Competitive Context

**Current state of Coq tooling:**
- `destruct` fails with "Abstracting over the terms ... leads to a term which is ill-typed" — the error references internal term transformations, not the user's intent
- `dependent destruction` (from `Program.Equality`) automates the fix but silently introduces the `JMeq_eq` axiom, which is unacceptable for axiom-free developments
- The Equations plugin provides clean dependent pattern matching via `depelim` but requires setup boilerplate (`Derive NoConfusion`, `Derive Signature`) that users do not know about
- `inversion` generates correct subgoals but produces cluttered proof states with spurious equalities and renamed variables

**Knowledge resources:**
- CPDT (Chlipala) covers the convoy pattern but is dense and example-driven
- Blog posts (unwoundstack.com, jamesrwilcox.com) explain the problem well but are hard to discover
- No existing tool diagnoses the problem from the proof state and recommends a technique

**Gap:** No existing tool — IDE, CLI, or MCP — detects a dependent-destruction failure, explains it, and generates the appropriate fix. Users must independently identify the problem category, choose a technique, and write the boilerplate.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R-CP-P0-1 | Given a proof state where `destruct` has failed or lost dependent information, diagnose the failure: identify which hypothesis types depend on the destructed term's indices and explain what information was lost |
| R-CP-P0-2 | Recommend the appropriate repair technique based on the user's situation: `revert`-before-`destruct` (axiom-free, tactic mode), `dependent destruction` (quick fix, introduces `JMeq_eq`), convoy pattern (term mode), or Equations `depelim` (axiom-free, requires plugin) |
| R-CP-P0-3 | When recommending `revert`-before-`destruct`, identify exactly which hypotheses need to be reverted — those whose types mention the indices of the destructed term |
| R-CP-P0-4 | When recommending `dependent destruction`, warn that the proof will depend on the `JMeq_eq` axiom and explain the implications for axiom-free developments |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R-CP-P1-1 | Generate convoy-pattern boilerplate: produce the `match ... as ... in ... return ...` term with correct return-clause annotations given the match target, dependent terms, and desired result type |
| R-CP-P1-2 | Generate the `revert`/`destruct` tactic sequence that implements the convoy pattern at the tactic level |
| R-CP-P1-3 | When the Equations plugin is available, generate the `Equations` function definition with appropriate `Derive` commands |
| R-CP-P1-4 | Explain the convoy pattern in plain language: what it is, why it works, and how the return clause threads type refinement through match arms |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R-CP-P2-1 | Detect the dependent-destruction problem proactively when observing a proof state — before the user asks — and suggest the fix |
| R-CP-P2-2 | For types with decidable equality on indices, suggest the axiom-free variant using `Eqdep_dec.eq_rect_eq_dec` instead of `JMeq_eq` |
| R-CP-P2-3 | Generate a reusable custom elimination lemma (e.g., `fin_case`) for recurring dependent-destruction patterns in the user's development |

---

## 5. Scope Boundaries

**In scope:**
- Diagnosing dependent-destruction failures from the proof state
- Recommending repair techniques with axiom-awareness
- Generating convoy-pattern boilerplate (tactic-level and term-level)
- Identifying which hypotheses to revert before destruction
- Plain-language explanation of the convoy pattern and dependent matching

**Out of scope:**
- Modifying Coq's `destruct` tactic or match compilation
- Implementing a new tactic or Coq plugin
- Automatically applying the fix to the user's proof script without confirmation
- IDE plugin development — capabilities are accessed via Claude Code's MCP integration
- Supporting Lean or Agda dependent pattern matching (Coq-specific only)
