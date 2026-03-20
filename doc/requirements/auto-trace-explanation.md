# Auto/Eauto Trace Explanation — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context; see [common-questions.md](../background/common-questions.md) §8.1 (why does auto not solve this goal?) for the motivating user pain point; see [tactic-documentation.md](tactic-documentation.md) for the existing tactic documentation initiative that this extends.

## 1. Business Goals

When Coq's `auto` or `eauto` tactics fail to solve a goal — or solve it in an unexpected way — users face a wall of silence. The tactic either succeeds or fails with no explanation. This is one of the most frequently asked questions across all Coq community channels: *"Why doesn't `auto` solve this goal when the lemma is right there in the hint database?"*

The answer is rarely simple. There are at least nine distinct reasons a hint can be skipped, and users have no efficient way to determine which one applies:

1. **Weak unification:** `auto` uses `simple apply`, which is weaker than `apply`. A hint that works with `apply` can fail silently under `auto`. Worse, `auto using foo` uses a *different, more powerful* unification than `Hint Resolve foo` followed by `auto`, so the two paths are not equivalent.
2. **Existential variables:** `auto` refuses hints whose application would leave existential variables — that requires `eauto`. But there is no message telling the user this.
3. **Depth limit:** The default depth of 5 is often insufficient, and exceeding it produces no diagnostic.
4. **Wrong hint database:** `auto` with no `with` clause only searches `core`. Users forget to specify their custom database and get silence instead of an error.
5. **Head symbol mismatch:** `auto` only considers hints whose conclusion matches the goal's head predicate. If the goal is `~ P x` (i.e., `P x -> False`), hints about `False` won't match because `auto` doesn't unfold the negation.
6. **Opacity and transparency:** Implicitly created hint databases default to opaque transparency, silently preventing unification that works in other contexts.
7. **Resolve vs. Extern inconsistency:** `Hint Resolve` simplifies goals before pattern matching (using unification), while `Hint Extern` does syntactic matching without simplification — the same hint can match or fail depending on its registration form.
8. **Quantified variables not in conclusion:** `auto` does not instantiate universally quantified variables that do not appear in the conclusion. A hint `forall n m p, n = p -> n = m` won't fire if `p` is absent from the goal.
9. **Priority ordering between databases:** `auto` exhausts all hints in the first database before trying the second, regardless of cost — priority numbers are ignored across database boundaries.

Coq provides debugging tools, but they are inadequate:

- **`debug auto`** has *different semantics* from `auto` itself — it wraps `Hint Extern` entries with `once`, preventing backtracking. A goal that `auto` solves can fail under `debug auto`, making the debugging tool actively misleading (Coq issue #4064).
- **`Info auto`** shows only the successful proof script, not failed attempts. When auto fails, `Info auto` provides no diagnostic value.
- **`Info 1 auto`** outputs `<unknown>;<unknown>` — literally useless. The issue was closed as "won't fix" because "Nobody is interested in working on Info."
- **`Set Debug "tactic-unification"`** produces a flat stream of unification problems with no tree structure, no summary, and no indication of which problems correspond to which hints.
- **Timeout destroys debug output:** When `eauto` runs too long and the user adds `Timeout`, the error message overwrites the trace in CoqIDE.

This initiative provides an MCP tool that answers the question users are actually asking: *"Here is my goal. Here are the hints that were considered. Here is why each one was accepted or rejected."* Rather than asking users to interpret raw debug traces, Claude parses the trace, cross-references it with the hint database contents and the goal state, and produces a structured, actionable explanation.

This builds on Poule's existing `inspect_hint_db`, `suggest_tactics`, and `tactic_lookup` tools from the Tactic Documentation initiative, extending them from "what hints exist" to "why didn't they fire."

**Success metrics:**
- Given a goal where `auto` or `eauto` fails, the tool correctly identifies the reason the expected hint was skipped in ≥ 85% of cases (measured against a curated set of 50+ real-world examples drawn from Stack Overflow, Discourse, and Zulip)
- Users can diagnose a failed `auto`/`eauto` invocation within a single interaction, without resorting to manual `debug auto` or `Info` commands
- The explanation includes an actionable fix suggestion (switch to `eauto`, increase depth, add `with db`, use explicit `apply`, etc.) in ≥ 90% of diagnosed cases
- Response latency < 5 seconds for proofs with ≤ 200 hints in scope
- ≥ 80% of users who invoke the tool report that the explanation helped them resolve their issue

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Intermediate Coq developers using Claude Code | Understand why `auto`/`eauto` skips a hint that "should" work; receive a concrete fix without learning debug trace syntax | Primary |
| Coq newcomers using Claude Code | Grasp the distinction between `auto`, `eauto`, `typeclasses eauto`, and `intuition` through concrete examples of what each does differently on their actual goal | Primary |
| Advanced Coq developers using Claude Code | Quickly diagnose subtle failures (opacity settings, priority ordering, Resolve vs. Extern semantics) that even experts find tedious to track down manually | Secondary |
| Coq instructors and mentors | A diagnostic tool students can use to self-diagnose automation failures during exercises, reducing instructor intervention | Secondary |

---

## 3. Competitive Context

**Current Coq tooling:**
- `debug auto` / `debug eauto`: Flat, depth-annotated trace log. No tree structure, no failure reasons, no summary. Known to have different semantics from the non-debug variant (issue #4064). Timeout can overwrite trace output (issue #4115).
- `Info auto` / `info_auto`: Shows successful proof path only. Zero diagnostic value when `auto` fails. `Info 1 auto` outputs `<unknown>` (issue #4587, closed won't-fix).
- `Set Debug "tactic-unification"`: Flat stream of unification problems. No hierarchy, no backtracking annotations, no correlation to specific hints. Community has requested tree-like output since 2016 (issue #3771); unimplemented.
- `Print HintDb <db>`: Lists hints but does not show transparency settings, does not indicate which hints match the current goal, and does not show Hint Mode configuration. No provenance information (which file registered the hint).
- `Print Hint <symbol>`: Queries hints for a symbol, not a database. Users confuse it with `Print HintDb` (issue #9020).

**Lean ecosystem:**
- Lean 4's `exact?` and `apply?` report which lemma matches or explain why none do. `trace.Meta.Tactic.solveByElim` provides hierarchical trace output for `solve_by_elim` (Lean's closest analogue to `auto`). The Lean community has better trace UX but a narrower automation surface.

**Poule's existing tools (extend, don't duplicate):**
- `inspect_hint_db`: Shows database contents — what hints exist. This initiative adds *why a hint was not used*.
- `suggest_tactics`: Suggests tactics for a goal. This initiative adds *why a specific tactic/hint failed*.
- `tactic_lookup` / `compare_tactics`: Explains tactic behavior in general. This initiative adds goal-specific diagnostic.
- `trace_resolution`: Traces typeclass resolution. This initiative covers `auto`/`eauto` hint resolution, which uses a different (though related) mechanism.

**Key insight:** No existing tool in any proof assistant ecosystem answers the specific question "why did auto skip this hint on this goal?" in a single, structured response. The raw information is available (debug traces, hint databases, unification logs) but is fragmented across multiple commands with incompatible output formats. An MCP tool that fuses these sources and presents a unified diagnosis fills a gap that the Coq project itself has not prioritized.

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| AT-P0-1 | Given a goal state and a failed `auto` or `eauto` invocation, identify which hints were considered and classify each as matched (applied successfully), attempted-but-failed (tried and rejected), or not-considered (filtered before attempt) |
| AT-P0-2 | For each attempted-but-failed hint, explain the specific reason for rejection: unification failure, existential variable left, depth exhausted, wrong database, head symbol mismatch, opacity mismatch, or other classified reason |
| AT-P0-3 | For each not-considered hint, explain why it was filtered: not in the consulted database(s), head symbol did not match, or Hint Mode prevented consideration |
| AT-P0-4 | When a hint would succeed with `eauto` but not `auto` (because it leaves evars), explicitly state this and suggest switching to `eauto` |
| AT-P0-5 | When the depth limit is the bottleneck, report the minimum depth required and suggest `auto N` or `eauto N` with the appropriate depth |
| AT-P0-6 | Provide an actionable fix suggestion for each diagnosed failure: switch to `eauto`, increase depth, specify `with db`, use explicit `apply`, adjust opacity, or add a missing hint |
| AT-P0-7 | Expose the diagnostic as an MCP tool compatible with Claude Code (stdio transport), operable within an active proof session |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| AT-P1-1 | Given a specific hint name (or lemma name) and a goal, explain specifically why that hint was or was not used — a "why not this hint?" query |
| AT-P1-2 | When `auto` succeeds but the user expected a different proof path, show the winning path and explain why the expected hint was not preferred (lower priority, matched later, etc.) |
| AT-P1-3 | Distinguish between `auto`, `eauto`, and `typeclasses eauto` semantics in the diagnosis: explain which variant would succeed and why, based on their different unification strategies and database defaults |
| AT-P1-4 | Show the effective database(s) and transparency settings that were in scope for the failed invocation, so the user can verify their `Hint` registrations and `with` clauses |
| AT-P1-5 | When the trace reveals that `auto using foo` would succeed but `Hint Resolve foo` + `auto` fails (due to different unification paths), explain this known inconsistency and recommend the appropriate workaround |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| AT-P2-1 | Visualize the hint search tree as a diagram (analogous to existing proof tree visualization), showing branching points, successful paths, and failure reasons at each node |
| AT-P2-2 | Compare the behavior of `auto`, `eauto`, and `typeclasses eauto` on the same goal side-by-side, showing which hints each variant considers and how their search strategies diverge |
| AT-P2-3 | Detect and warn about common hint database misconfigurations: hints registered in a database that is never consulted, overlapping hints with inconsistent priorities, Hint Extern patterns that shadow Hint Resolve entries |
| AT-P2-4 | Provide a "lint" mode that examines a hint database for potential issues without requiring a specific failing goal: transparency mismatches, unreachable hints, redundant entries |

---

## 5. Scope Boundaries

**In scope:**
- Running `auto`/`eauto` with debug tracing against a live proof state and parsing the trace output
- Cross-referencing trace output with hint database contents, transparency settings, and goal structure
- Classifying and explaining hint rejection reasons
- Providing actionable fix suggestions
- Exposing the diagnostic as an MCP tool within an active proof session
- Explaining the differences between `auto`, `eauto`, and `typeclasses eauto` in the context of a specific failure

**Out of scope:**
- Modifying Coq's `auto`/`eauto` implementation or debug output format
- Automated proof repair (applying the suggested fix without user approval — that is the responsibility of the proof repair initiative)
- General tactic debugging beyond the `auto`/`eauto`/`typeclasses eauto` family (e.g., debugging `rewrite`, `apply`, `inversion` — those are separate concerns)
- Typeclass resolution tracing (already covered by `trace_resolution` in the Typeclass Debugging initiative)
- Hint database authoring or management tools (adding, removing, or reorganizing hints)
- IDE plugin development
- Build system or CI integration
