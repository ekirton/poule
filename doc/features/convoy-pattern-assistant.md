# Convoy Pattern Assistant

When a Coq user calls `destruct` on a term of an indexed inductive type, Coq silently abstracts over the indices — and any hypothesis whose type mentions those indices loses its connection to the destructed term. The user either gets a cryptic "Abstracting over ... leads to an ill-typed term" error, or worse, a proof state where equalities have vanished without explanation. The Convoy Pattern Assistant diagnoses these dependent-destruction failures, recommends the appropriate repair technique from the four available options (each with different tradeoffs), and generates the boilerplate that users find hardest to write by hand.

**Stories:** [Epic 1: Failure Diagnosis](../requirements/stories/convoy-pattern-assistant.md#epic-1-failure-diagnosis), [Epic 2: Technique Recommendation](../requirements/stories/convoy-pattern-assistant.md#epic-2-technique-recommendation), [Epic 3: Boilerplate Generation](../requirements/stories/convoy-pattern-assistant.md#epic-3-boilerplate-generation), [Epic 4: Explanation](../requirements/stories/convoy-pattern-assistant.md#epic-4-explanation)

---

## Problem

Coq's `match` construct only refines the return type of the match expression. It does not automatically refine the types of free variables in scope. When a user writes `destruct v` where `v : Fin n` and another hypothesis `H : P n` exists, Coq internally replaces `n` with a fresh variable in the return type but leaves `H` unchanged. The result is a proof state where `H` still says `P n` but `n` has been replaced by a constructor-specific value — the connection is severed. In Agda, pattern matching automatically specializes all variables in scope via unification. In Coq, the user must do this manually.

This leads to two observable failure modes:

- **Ill-typed abstraction error.** `destruct` refuses to proceed because abstracting over the index would produce an ill-typed term. The error message references internal term transformations ("Abstracting over the terms `n` and `y` leads to a term which is ill-typed") with no indication of what the user should do differently.

- **Silent information loss.** `destruct` succeeds but the resulting proof state is weaker than expected. Hypotheses that depended on the destructed term's indices now reference fresh variables with no record of their relationship to the original constructors. Subsequent tactics fail for reasons that are not obvious from the proof state.

The fix exists — in fact, four fixes exist — but choosing the right one requires understanding the tradeoffs between them, and writing the boilerplate for any of them requires knowledge that is scattered across CPDT, blog posts, and mailing-list archives with no single authoritative guide. This is not a rare problem: it occurs routinely in any development that uses length-indexed vectors, finite types, well-typed syntax trees, or inductive relations with non-trivial index structure.

## Solution

Claude acts as a guide through the entire diagnostic and repair process. The user describes the problem — an error message, a surprising proof state, or a `destruct` that "lost something" — and Claude identifies the failure mode, recommends a technique, and generates the code.

### Failure Diagnosis

When the user reports a dependent-destruction problem, Claude inspects the proof state to identify which hypotheses have types that mention the indices of the term being destructed. It explains, in the user's own terms, what information was lost and why — that `destruct` abstracts over the indices without updating dependent hypotheses. When the error is "Abstracting over ... leads to an ill-typed term", Claude translates the error from Coq's internal representation into a description using the user's hypothesis names and types.

### Technique Recommendation

Four repair techniques exist, and no single one is universally best. Claude recommends based on the user's situation:

- **`revert`-before-`destruct`** is the default recommendation for tactic-mode proofs. It is axiom-free and idiomatic: the user reverts the dependent hypotheses before destructing, so they become part of the return type and are refined in each branch. The key value Claude provides is identifying exactly which hypotheses to revert and in what order — this requires analyzing type dependencies that are tedious to trace by hand.

- **`dependent destruction`** (from `Program.Equality`) is recommended as a quick alternative when the user has no axiom constraints. It automates the revert-destruct pattern but introduces the `JMeq_eq` axiom. Claude always discloses this tradeoff: `JMeq_eq` is consistent but not provable in Coq's core theory, and `Print Assumptions` will show it.

- **The convoy pattern** is recommended when the user is writing a `match` expression in term mode rather than using tactics. Claude generates the `match ... as ... in ... return ...` boilerplate with the correct return-clause annotations — the part users find hardest to construct.

- **Equations `depelim`** is recommended when the Equations plugin is available and the user wants clean dependent pattern matching without axioms. Claude generates the `Equations` definition with the required `Derive NoConfusion` and `Derive Signature` commands.

The recommendation is not a menu — Claude picks the best option for the situation and explains why, while noting alternatives.

### Boilerplate Generation

The highest-friction part of each technique is the boilerplate. For `revert`-before-`destruct`, it is knowing which hypotheses to revert. For the convoy pattern, it is writing the return clause — a `match ... as x in T a1 a2 return (... -> ...)` annotation that threads dependent terms as function arguments so they are refined in each branch. For Equations, it is the `Derive` commands for the relevant types. Claude generates all of this from the proof state, producing code the user can paste directly into their development.

### Explanation

For users who want to understand the mechanism rather than just apply a recipe, Claude explains the convoy pattern in plain language: why Coq's `match` only refines the return type, what the `as`/`in`/`return` annotations do, and how adding dependent terms as function arguments in the return clause causes Coq to refine them in each branch. The explanation uses a concrete example from the user's proof when possible, falling back to a canonical example (e.g., `Fin n`) when not.

## Scope

The Convoy Pattern Assistant provides:

- Diagnosis of dependent-destruction failures from the proof state, translating cryptic errors into plain-language explanations
- Technique recommendation with axiom-awareness: which technique to use and why, with disclosure of axiom implications
- Identification of exactly which hypotheses to revert before destruction
- Generation of convoy-pattern return clauses, `revert`/`destruct` tactic sequences, and Equations definitions
- Plain-language explanation of the convoy pattern for users who want to understand the mechanism

The Convoy Pattern Assistant does not provide:

- Modifications to Coq's `destruct` tactic, match compilation, or error messages
- New Coq tactics or plugins — it works within the existing Coq and MCP tool surface
- Automatic application of fixes without user confirmation
- Support for Lean or Agda dependent pattern matching — it is Coq-specific

---

## Design Rationale

### Why recommend multiple techniques rather than always one

No single technique is universally best. `revert`-before-`destruct` is axiom-free and tactic-mode-native, but requires the user to identify dependency chains. `dependent destruction` is convenient but introduces `JMeq_eq`. The convoy pattern works in term mode but is syntactically heavy. Equations provides the cleanest solution but requires a plugin. An assistant that always recommends the same technique would be wrong in a significant fraction of cases. The value is in matching the technique to the situation — axiom tolerance, proof mode, plugin availability — which requires exactly the kind of contextual judgment that an LLM excels at.

### Why axiom disclosure is a first-class concern

In Coq's culture, axiom-freedom is a meaningful property of a development. Many users and projects (especially in verified software and certified compilation) track which axioms their proofs depend on via `Print Assumptions`. A tool that silently introduces `JMeq_eq` via `dependent destruction` would undermine this property without the user's knowledge. Making axiom implications explicit and offering axiom-free alternatives is not a nice-to-have — it is a correctness requirement for the tool to be trustworthy.

### Why boilerplate generation targets the return clause specifically

The convoy pattern's return clause is the single hardest piece of Coq syntax for users to write correctly. It requires understanding how the `as` binder, the `in` pattern, and the `return` type interact, and getting the dependent-function-argument threading right on the first try. Users who understand the concept still struggle with the syntax. Generating this boilerplate is high-leverage because the cognitive bottleneck is syntactic, not conceptual — exactly the kind of task where code generation saves disproportionate effort.

### Why this feature consumes existing MCP tools

Diagnosing a dependent-destruction failure requires inspecting the proof state (`observe_proof_state`), checking hypothesis types, and understanding the inductive type being destructed. These are capabilities already provided by the proof session and vernacular introspection tools. Building on the existing tool surface avoids duplication and ensures the assistant benefits from improvements to the underlying inspection infrastructure.
