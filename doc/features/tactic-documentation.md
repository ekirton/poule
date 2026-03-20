# Tactic Documentation

Contextual tactic documentation that draws on Coq's own introspection commands to explain what tactics do, compare alternatives side-by-side, and suggest which tactics to try next — all grounded in the user's live proof state and project definitions. Claude Code invokes these capabilities as MCP tools during conversational proof development, replacing the cycle of context-switching to the reference manual, searching blog posts, and guessing.

**Stories:** [Epic 1: Tactic Lookup and Explanation](../requirements/stories/tactic-documentation.md#epic-1-tactic-lookup-and-explanation), [Epic 2: Tactic Comparison](../requirements/stories/tactic-documentation.md#epic-2-tactic-comparison), [Epic 3: Contextual Tactic Suggestion](../requirements/stories/tactic-documentation.md#epic-3-contextual-tactic-suggestion), [Epic 4: Tactic Usage Examples and Reference](../requirements/stories/tactic-documentation.md#epic-4-tactic-usage-examples-and-reference)

---

## Problem

Coq's tactic language is large, loosely organized, and unevenly documented. The standard library alone provides dozens of tactics — `auto`, `eauto`, `intuition`, `lia`, `ring`, `congruence`, `firstorder`, `typeclasses eauto`, and many more — each with distinct behavior, overlapping applicability, and non-obvious trade-offs. Users extend this set with project-local Ltac definitions that have no documentation at all.

Newcomers encounter unfamiliar tactics in textbooks and existing proof scripts with no efficient way to understand them. Intermediate users know several tactics but struggle to choose the right one for a given proof obligation — is `auto` sufficient, or do they need `eauto`? Should they use `lia` or `omega`? Advanced users need quick access to Ltac definitions, hint database contents, and unfolding strategies, but the raw output of Coq's introspection commands assumes expert knowledge.

The resources that exist — the Coq reference manual, community wiki, scattered blog posts — are static and reference-style. They describe tactics in isolation, disconnected from the user's actual proof state, project definitions, and development context. Using them requires leaving the development workflow, finding the right page, and mentally mapping the generic description back to the specific situation at hand.

## Solution

### Tactic Lookup

Given a tactic name, retrieve its definition from the running Coq session. For Ltac tactics this returns the source as Coq itself reports it via `Print Ltac`; for primitive tactics or Ltac2 tactics with no Ltac definition, it reports that clearly rather than failing silently. The lookup works for both standard library tactics and project-local definitions, so users see exactly what their session knows about a tactic — not a stale reference page, but the live definition.

Primitive tactics — `apply`, `destruct`, `simpl`, `cbn`, `eapply`, `setoid_rewrite`, and the full set of Coq built-ins — are returned as valid results with their functional category (rewriting, case analysis, automation, etc.), not as errors. The tool intercepts the Coq error that `Print Ltac` produces for non-Ltac names and translates it into a structured `kind = "primitive"` response. This ensures that the LLM receives usable metadata for every tactic the user asks about, regardless of how Coq implements it internally.

Multi-word inputs (e.g., "convoy pattern", "dependent destruction") are rejected with a clear error, since `Print Ltac` accepts only single Coq identifiers. The LLM is expected to recognize that these are proof techniques or tactic notations and address the user's question from general knowledge rather than attempting introspection.

### Tactic Explanation

Given a tactic name, produce a plain-language explanation of what the tactic does, what types of goals it applies to, and when to reach for it. For project-local tactics, the explanation is grounded in the actual Ltac definition retrieved from the session, not solely in general knowledge. For tactics with optional arguments or variants (e.g., `rewrite ->` vs. `rewrite <-` vs. `rewrite ... in ...`), the explanation covers the key invocation patterns. The result is a description a newcomer can act on immediately, without needing to read Ltac syntax or trace through Coq internals.

### Tactic Comparison

Given two or more tactic names, produce a structured comparison covering behavior differences, performance characteristics, applicability overlap, and guidance on when to prefer each. For example, comparing `auto` and `eauto` explains that `eauto` can apply lemmas with existential variables while `auto` cannot, and notes the performance trade-off. Comparing `auto`, `eauto`, and `typeclasses eauto` distinguishes the hint databases each consults and the search strategies each employs. If a requested tactic does not exist in the current session, the comparison says so and proceeds with the remaining tactics.

### Contextual Suggestion

Given an active proof state, suggest a ranked list of tactics likely to make progress on the current goal, each with a brief rationale. For a propositional logic formula, the suggestions include `intuition`, `tauto`, or `firstorder` with an explanation of their relevance. For a goal involving arithmetic, they include decision procedures such as `lia` or `ring`. When no strong candidates are identified, the result says so and suggests general strategies — unfolding definitions, case analysis on a hypothesis, or trying a different approach entirely. The suggestions are informed by the goal structure, the local context, and (when available) the contents of relevant hint databases and the unfolding strategies of constants appearing in the goal.

## Design Rationale

### Why contextual documentation over reference documentation

Static reference documentation describes tactics in isolation. An LLM with access to the user's proof state can do something fundamentally different: explain a tactic in the context of the goal the user is currently trying to prove, using the actual hypotheses and definitions in scope. "This tactic would work here because your goal is a conjunction and `split` breaks conjunctions into two sub-goals" is more useful than "The `split` tactic applies to inductive types with exactly one constructor." Contextual explanation collapses the mental mapping step that makes reference documentation slow to use.

### Relationship to proof search

Tactic documentation and proof search are complementary. Proof search automates: it tries many tactics silently and returns a verified proof script. Tactic documentation teaches: it explains what tactics do, why one is preferred over another, and which ones apply to the current situation. A user who wants to understand their proof uses tactic documentation; a user who wants to discharge a routine obligation uses proof search. The two share infrastructure — both need access to the proof state and the running Coq session — but serve different goals. Tactic documentation builds the user's knowledge; proof search applies knowledge the user may not need to acquire.

### Relationship to vernacular introspection

Tactic documentation builds on the same Coq introspection commands that vernacular introspection exposes — `Print Ltac`, `Print Strategy`, `Print HintDb`. The difference is in purpose: vernacular introspection provides raw access to Coq's internal state for users who know what they are looking for; tactic documentation interprets that raw output, adding explanation, comparison, and contextual relevance. A user can always fall back to vernacular introspection for the unfiltered output, but tactic documentation is the higher-level interface that most users will reach for first.
