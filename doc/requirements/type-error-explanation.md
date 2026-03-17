# Type Error Explanation — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) §4 (Agentic Workflows) for ecosystem context.

## 1. Business Goals

Type errors are the single most common barrier for newcomers to Coq and a persistent source of friction even for experienced users. Coq's error messages for type mismatches are notoriously opaque: they report the expected and actual types in fully expanded, often universe-polymorphic form, with no indication of which part of a complex type diverged, what coercions were attempted and failed, or what the user likely intended. Users must manually invoke `Check`, `Print`, `About`, and `Print Coercions` to reconstruct the context the error message omits — a process that requires expert knowledge of the type system and Coq's vernacular commands.

This initiative provides a Claude Code slash command (`/explain-error`) that automates this entire diagnostic workflow. When a user encounters a type error, the slash command orchestrates multiple MCP tools — error parsing, type inspection, coercion lookup, universe constraint inspection — and delivers a plain-language explanation of what went wrong, why it went wrong, and what the user can do to fix it. No traditional IDE can offer this because it requires combining structured error output with multi-step contextual inspection and natural language reasoning.

**Success metrics:**
- Users can obtain a plain-language explanation of any type error through a single `/explain-error` invocation, without needing to know which Coq commands to run or how to interpret raw error output
- Time to understand and resolve a type error is reduced by at least 60% compared to manual diagnosis (qualitative user evaluation)
- The slash command correctly identifies the root cause of the type mismatch (wrong argument type, missing coercion, universe inconsistency, implicit argument mismatch, or notation confusion) in at least 80% of cases in a test corpus of common type errors
- Fix suggestions are actionable (the user can apply them without further research) in at least 70% of cases where a fix is suggested
- The full diagnostic workflow completes within 15 seconds for typical type errors

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Newcomers and students learning Coq | Plain-language explanations of type errors that would otherwise be impenetrable; guidance on what to do next | Primary |
| Intermediate Coq users | Faster diagnosis of type mismatches involving coercions, implicit arguments, or universe levels — errors they can eventually resolve but that consume significant time | Primary |
| Experienced Coq developers | Quick triage of complex type errors in large developments where the relevant definitions span multiple modules | Secondary |
| Educators and course instructors | A teaching aid that can explain type errors to students in real time during exercises | Secondary |

---

## 3. Competitive Context

**Coq's built-in error messages (current state):**
- Coq reports type mismatches by printing the expected type and the actual type. For complex types involving nested inductive families, universe polymorphism, or implicit arguments, these printouts can span dozens of lines with no highlighting of where the divergence occurs.
- Coq does not explain why a coercion was not applied, which coercions were attempted, or what coercion the user might need. Users must manually query `Print Coercions` and `Print Graph` to reconstruct this information.
- Universe constraint errors (`Universe inconsistency`) provide the conflicting constraint but no path explaining how that constraint arose or which definition introduced it.

**Lean ecosystem:**
- Lean 4 produces structured, colored error messages with better formatting than Coq. The language server provides hover-based type information. However, Lean does not provide multi-step diagnostic workflows that combine error parsing with contextual type inspection and fix suggestions.

**IDE tooling:**
- CoqIDE, VsCoq, and Proof General display Coq's raw error messages without additional interpretation. None provide contextual type inspection, coercion analysis, or fix suggestions as part of the error experience.
- See [../background/coq-ecosystem-tooling.md](../background/coq-ecosystem-tooling.md) for a detailed survey of the current Coq tooling landscape.

**Gap:** No existing tool — IDE, CLI, or language server — interprets Coq type errors in context, inspects relevant type definitions and coercions, and explains the error in plain language. This is an inherently agentic task: it requires orchestrating multiple inspection commands, reasoning about the results, and producing a tailored explanation. A slash command backed by an LLM is the natural implementation.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| RTE-P0-1 | Parse Coq type error messages to extract the expected type, actual type, location in the source, and any additional context Coq provides (e.g., "In environment ...") |
| RTE-P0-2 | Fetch and inspect the definitions of the expected and actual types using Coq vernacular commands (`Print`, `Check`, `About`) to provide context beyond what the error message contains |
| RTE-P0-3 | Produce a plain-language explanation of what went wrong: identify which part of the type diverges and explain the mismatch in terms the user can understand |
| RTE-P0-4 | Support the most common categories of type errors: simple type mismatches, application to wrong number of arguments, and inability to unify terms |
| RTE-P0-5 | Implement as a Claude Code slash command (`/explain-error`) that orchestrates MCP tools from the Poule server |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| RTE-P1-1 | Inspect coercion paths relevant to the type mismatch: query `Print Coercions` and `Print Graph` to determine what coercions exist between the expected and actual types, and explain why they were not applied |
| RTE-P1-2 | Suggest concrete fixes for the type error: propose type annotations, explicit coercions, argument reordering, or alternative lemmas/constructors that would resolve the mismatch |
| RTE-P1-3 | Handle implicit argument mismatches: identify when the error is caused by Coq's implicit argument inference filling in an unexpected type, and explain what implicit was inferred and why |
| RTE-P1-4 | Handle notation-related type confusion: detect when the error arises because a notation is being interpreted in an unexpected scope, and explain the notation's actual meaning |
| RTE-P1-5 | Provide contextual examples showing the correct usage pattern for the definition or tactic that produced the type error |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| RTE-P2-1 | Diagnose universe inconsistency errors: inspect universe constraints, identify the conflicting path, and explain in plain language what caused the inconsistency and how to resolve it |
| RTE-P2-2 | Handle errors involving canonical structures: explain when a canonical structure projection failed to trigger and why |
| RTE-P2-3 | Maintain a session context so that repeated `/explain-error` invocations on related errors can build on previous explanations rather than starting from scratch |

---

## 5. Scope Boundaries

**In scope:**
- A Claude Code slash command (`/explain-error`) that orchestrates existing MCP tools to diagnose type errors
- Parsing and interpreting Coq type error messages
- Contextual type inspection using Coq vernacular commands exposed as MCP tools
- Coercion path analysis using `Print Coercions` and `Print Graph`
- Plain-language explanation of type mismatches
- Fix suggestions for common type error patterns

**Out of scope:**
- Modifying Coq's error reporting or type checker
- Building new MCP tools — this initiative consumes tools built by other initiatives (vernacular introspection, universe inspection, notation inspection)
- IDE plugin development (VS Code, Emacs, etc.) — the slash command runs within Claude Code
- Automated error correction (applying fixes without user approval)
- Errors that are not type errors (tactic failures, syntax errors, universe inconsistencies beyond P2 scope)
