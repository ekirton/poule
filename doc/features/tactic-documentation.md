# Tactic Documentation

Contextual tactic documentation that draws on Coq's own introspection commands to explain what tactics do, compare alternatives side-by-side, and suggest which tactics to try next — all grounded in the user's live proof state and project definitions. Claude Code invokes these capabilities as MCP tools during conversational proof development, replacing the cycle of context-switching to the reference manual, searching blog posts, and guessing.

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

## Acceptance Criteria

### Tactic Lookup and Explanation

**Priority:** P0
**Stability:** Stable

- GIVEN a valid tactic name WHEN the tactic lookup tool is invoked THEN it returns the Ltac definition as produced by `Print Ltac` in the running Coq session
- GIVEN a tactic name that does not exist in the current session WHEN the tool is invoked THEN it returns a clear error indicating the tactic was not found
- GIVEN an Ltac2 tactic or a primitive tactic with no Ltac definition WHEN the tool is invoked THEN it returns an appropriate message indicating the tactic is not defined in Ltac
- GIVEN a built-in primitive tactic name (e.g., `apply`, `destruct`, `simpl`, `setoid_rewrite`) WHEN the tactic lookup tool is invoked and Coq returns an error such as "not an Ltac definition" or "not a user defined tactic" THEN the tool returns a valid TacticInfo with `kind = "primitive"`, `body = null`, and the appropriate `category` — not an error
- GIVEN a multi-word input containing whitespace (e.g., "convoy pattern", "dependent destruction") WHEN the tactic lookup tool is invoked THEN it returns an `INVALID_ARGUMENT` error indicating that tactic names must be single identifiers
- GIVEN a tactic name WHEN an explanation is requested THEN Claude returns a plain-language description covering what the tactic does, what types of goals it applies to, and common use cases
- GIVEN a tactic with optional arguments or variants WHEN an explanation is requested THEN the explanation describes the effect of key arguments and common invocation patterns
- GIVEN a project-local Ltac tactic WHEN an explanation is requested THEN the explanation is grounded in the actual Ltac definition retrieved from the Coq session, not solely from general knowledge

**Traces to:** R-P0-1, R-P0-2, R-P0-5, R-P0-6

### Tactic Documentation MCP Tools

**Priority:** P0
**Stability:** Stable

- GIVEN a running MCP server WHEN its tool list is inspected THEN tactic lookup and explanation tools are present with documented schemas
- GIVEN an MCP tool invocation WHEN the Coq session is active THEN the tool executes against the live session and returns results within 3 seconds
- GIVEN an MCP tool invocation WHEN no Coq session is active THEN the tool returns a clear error indicating a session is required

**Traces to:** R-P0-4

### Tactic Comparison

**Priority:** P0
**Stability:** Stable

- GIVEN two or more tactic names WHEN a comparison is requested THEN Claude returns a structured comparison covering behavior differences, performance characteristics, applicability overlap, and guidance on when to prefer each
- GIVEN tactics `auto` and `eauto` WHEN compared THEN the comparison explains that `eauto` can apply lemmas with existential variables in their conclusions while `auto` cannot, and notes the performance trade-off
- GIVEN tactics `auto`, `eauto`, and `typeclasses eauto` WHEN compared THEN the comparison distinguishes the hint databases each consults and the search strategies each employs
- GIVEN a tactic name that does not exist WHEN included in a comparison request THEN the comparison indicates which tactic was not found and proceeds with the remaining valid tactics

**Traces to:** R-P0-3

### Contextual Tactic Suggestion

**Priority:** P1
**Stability:** Stable

- GIVEN an active proof state with at least one open goal WHEN tactic suggestion is invoked THEN it returns a ranked list of tactics likely to make progress, each with a brief rationale explaining why it may apply
- GIVEN a goal that is a propositional logic formula WHEN tactic suggestion is invoked THEN the suggestions include tactics such as `intuition`, `tauto`, or `firstorder` with an explanation of their relevance
- GIVEN a goal involving arithmetic WHEN tactic suggestion is invoked THEN the suggestions include decision procedures such as `lia`, `omega`, or `ring` as appropriate
- GIVEN a goal with no obvious applicable tactic WHEN tactic suggestion is invoked THEN the result indicates that no strong candidates were identified and suggests general strategies (e.g., "try unfolding definitions" or "consider case analysis on a hypothesis")

**Traces to:** R-P1-1

### Tactic Usage Examples and Reference

**Priority:** P1
**Stability:** Stable

- GIVEN a tactic name and a project with indexed source files WHEN usage examples are requested THEN the tool returns excerpts from the current project showing the tactic in use, including the surrounding proof context
- GIVEN a tactic name with no occurrences in the current project WHEN usage examples are requested THEN the tool falls back to standard library examples or indicates that no project-local examples were found
- GIVEN a tactic with multiple usage patterns WHEN usage examples are requested THEN the examples cover distinct patterns (e.g., `rewrite ->` vs `rewrite <-` vs `rewrite ... in ...`)
- GIVEN a valid hint database name WHEN the hint database inspection tool is invoked THEN it returns the contents of the database as produced by `Print HintDb`, grouped by hint type (Resolve, Unfold, Constructors, Extern)
- GIVEN a hint database name that does not exist WHEN the tool is invoked THEN it returns a clear error indicating the database was not found
- GIVEN a large hint database WHEN the tool is invoked THEN the output includes a summary count of hints by type before the detailed listing

**Traces to:** R-P1-2, R-P1-3

### Unfolding Strategy Inspection

**Priority:** P1
**Stability:** Draft

- GIVEN a constant name WHEN the strategy inspection tool is invoked THEN it returns the current unfolding strategy (opaque, transparent, or level) as produced by `Print Strategy`
- GIVEN a tactic name such as `simpl` or `cbn` WHEN strategy inspection is requested in the context of explaining that tactic THEN the tool retrieves strategies for constants relevant to the current goal

**Traces to:** R-P1-4
