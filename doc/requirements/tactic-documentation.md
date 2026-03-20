# Tactic Documentation — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context.

## 1. Business Goals

Coq's tactic language is large and loosely organized. The standard library alone provides dozens of tactics (`auto`, `eauto`, `intuition`, `omega`, `lia`, `ring`, `field`, `congruence`, `firstorder`, `typeclasses eauto`, `solve_constraints`, and many more), each with distinct behavior, overlapping applicability, and non-obvious trade-offs. Users define additional Ltac tactics in their developments, compounding the problem. The result is that newcomers and intermediate users routinely face two questions they cannot answer efficiently: *"What does this tactic actually do?"* and *"Which tactic should I use here?"*

Existing resources — the Coq reference manual, Coq community wiki, and scattered blog posts — are static, disconnected from the user's proof state, and require context-switching out of the development workflow. Coq provides introspection commands (`Print Ltac`, `Print Strategy`, `Print HintDb`) that expose tactic definitions and automation databases, but their raw output is dense and assumes expert knowledge.

This initiative wraps Coq's tactic introspection capabilities into MCP tools that Claude Code can invoke, enabling Claude to explain what a tactic does, when to use it, how it compares to alternatives, and which tactics are applicable to the current proof state — all within the conversational workflow. The goal is to collapse the tactic knowledge gap so that users spend less time searching documentation and more time developing proofs.

**Success metrics:**
- Users report reduced time spent searching for tactic documentation outside the development workflow
- Claude produces accurate tactic explanations that match Coq reference manual semantics in ≥ 90% of evaluations
- Tactic suggestion for a given proof state returns at least one applicable tactic in ≥ 80% of non-trivial goals
- Response latency for tactic explanation and lookup queries < 3 seconds

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq newcomers using Claude Code | Plain-language explanations of unfamiliar tactics encountered in tutorials, textbooks, or existing proof scripts | Primary |
| Intermediate Coq developers using Claude Code | Comparison of related tactics to choose the right one for a given proof obligation; discovery of tactics they have not yet learned | Primary |
| Advanced Coq developers using Claude Code | Quick lookup of Ltac definitions from project-local or library tactics; inspection of hint databases and tactic strategies | Secondary |
| Coq instructors and mentors | A tool that students can use to self-serve tactic explanations during exercises, reducing repeated questions | Secondary |

---

## 3. Competitive Context

**Current Coq tooling:**
- `Print Ltac <tactic>`: prints the Ltac definition of a user-defined or standard library tactic. Output is raw Ltac code with no explanation.
- `Print HintDb <db>`: prints the contents of an auto hint database. Output is a flat list of hint entries.
- `Print Strategy`: prints the unfolding strategy for constants. Useful for understanding `simpl` and `cbn` behavior, but opaque to non-experts.
- Coq reference manual: comprehensive but static; no integration with the user's proof state or workflow.

**IDE integrations:**
- CoqIDE, Proof General, vscoq: provide access to `Print Ltac` and similar commands but do not interpret or explain the output.
- No existing tool provides contextual tactic suggestions based on the current proof state within a conversational interface.

**LLM-based tools:**
- General-purpose LLMs can answer tactic questions but lack access to the user's actual Coq environment, project-local definitions, and current proof state. Answers may be stale or hallucinated.
- This initiative grounds Claude's tactic knowledge in live Coq introspection, ensuring accuracy and project-specificity.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R-P0-1 | Given a tactic name, retrieve its Ltac definition from the running Coq session using `Print Ltac` and return the result |
| R-P0-2 | Given a tactic name, provide a plain-language explanation of the tactic's behavior, including what it does, what types of goals it applies to, and common use cases |
| R-P0-3 | Given two or more tactic names, produce a structured comparison covering: behavior differences, performance characteristics, applicability overlap, and guidance on when to prefer each |
| R-P0-4 | Expose tactic documentation tools as MCP tools compatible with Claude Code (stdio transport) |
| R-P0-5 | Tactic lookup must return structured metadata for all built-in primitive tactics (apply, destruct, simpl, etc.) — not only for Ltac-defined tactics. When Coq reports that a name is not an Ltac definition, the tool returns a valid result with kind "primitive" rather than propagating an error. |
| R-P0-6 | Tactic lookup must reject multi-word input (names containing whitespace) with a clear error message, since Coq's `Print Ltac` accepts only single identifiers |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R-P1-1 | Given a proof state (goal and local context), suggest a ranked list of tactics likely to make progress, with a brief rationale for each suggestion |
| R-P1-2 | Given a tactic name, retrieve and present usage examples drawn from the current project or standard library |
| R-P1-3 | Given a hint database name, retrieve its contents via `Print HintDb` and present a summary of registered hints, grouped by type |
| R-P1-4 | Given a tactic name, retrieve the unfolding strategy for related constants via `Print Strategy` when relevant to understanding the tactic's behavior |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R-P2-1 | Maintain a local index of tactic usage frequency across the current project to inform suggestion ranking |
| R-P2-2 | Provide a "tactic cheat sheet" tool that returns a curated overview of the most commonly used tactics organized by proof task (simplification, rewriting, case analysis, induction, automation) |
| R-P2-3 | Support querying tactic documentation by proof task rather than by name (e.g., "how do I simplify this expression?" or "how do I do case analysis?") |

---

## 5. Scope Boundaries

**In scope:**
- Wrapping Coq introspection commands (`Print Ltac`, `Print HintDb`, `Print Strategy`) as MCP tools
- Plain-language tactic explanation grounded in Coq's actual definitions
- Structured comparison of related tactics
- Contextual tactic suggestion based on the current proof state
- Tactic usage examples from the current project or standard library

**Out of scope:**
- Automated proof search (covered by the Proof Search & Automation initiative)
- Premise selection or lemma retrieval (covered by Semantic Lemma Search)
- Modifications to Coq's tactic language or tactic authoring tools
- IDE plugin development (tools are accessed via Claude Code's MCP integration)
- Training or fine-tuning models on tactic data
- Proof visualization (covered by Proof Visualization Widgets initiative)
