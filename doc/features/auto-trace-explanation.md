# Auto/Eauto Trace Explanation

When `auto` or `eauto` fails to solve a goal, the user has no way to learn why. The tactic either succeeds or fails silently — there is no structured explanation of which hints were tried, which were rejected, or what the user should do differently. Auto Trace Explanation gives Claude the ability to diagnose these failures: it runs the tactic with debug tracing, cross-references the trace with the hint database contents and goal structure, and delivers a classified explanation of every hint rejection along with a concrete fix suggestion. The user asks "why didn't auto work?" and gets an answer, not a wall of trace output to decode.

---

## Problem

`auto` and `eauto` are the workhorses of Coq proof automation. They search a database of registered hints — lemmas, constructors, and custom tactics — and try to chain them together to close the current goal. When they work, they are invisible and effortless. When they fail, they are opaque and frustrating.

The failure mode is always the same: silence. The user registers a hint, invokes `auto`, and nothing happens. The goal remains unchanged. Coq provides no indication that the hint was even considered, let alone why it was rejected. The user is left to guess among at least nine distinct failure modes:

- The hint exists but is in a database that `auto` did not consult (the user forgot `with mydb`).
- The hint would work but leaves an existential variable, which `auto` refuses — `eauto` is needed instead.
- The hint matches but the search ran out of depth before reaching it (the default is 5 steps).
- The hint's conclusion does not match the goal's head symbol, so it was filtered before it was even tried.
- `auto` uses `simple apply` internally, which is weaker than `apply` — unification succeeds with one but fails with the other.
- The hint database has opaque transparency settings that prevent unification from seeing through definitions.
- `Hint Resolve` and `Hint Extern` use different matching strategies — the same lemma can match or fail depending on how it was registered.
- The hint has universally quantified variables that don't appear in the conclusion, which `auto` cannot instantiate.
- Hint priorities are respected within a database but ignored across databases — database order on the command line matters more than cost annotations.

Coq does provide debugging commands, but they are unreliable or unusable for this purpose. `debug auto` has *different semantics* from `auto` — it wraps `Hint Extern` entries with `once`, preventing backtracking, so goals that `auto` solves can fail under `debug auto`. `Info auto` shows the winning path when `auto` succeeds but provides nothing when it fails. `Info 1 auto` outputs `<unknown>;<unknown>` and the Coq developers closed the bug as "won't fix." `Set Debug "tactic-unification"` produces a flat stream of unification problems with no tree structure and no correlation to specific hints. Adding `Timeout` to a runaway `eauto` overwrites the debug trace with the timeout error.

The result is that debugging `auto`/`eauto` is a tedious manual process: the user tries `debug auto` (which may not reproduce the failure), inspects `Print HintDb` (which doesn't show transparency settings or goal relevance), manually attempts `apply` with individual lemmas, and eventually guesses their way to a workaround. For newcomers, this process is impassable. For experts, it is a well-known time sink.

## Solution

Claude acts as a diagnostic layer between the user and Coq's hint search engine. The user describes the problem — "why doesn't auto solve this?" or "why wasn't this lemma used?" — and Claude runs the tactic, inspects the trace and the hint databases, and returns a structured explanation with a fix suggestion.

### Failed Invocation Diagnosis

The core capability. Given an active proof state where `auto` or `eauto` failed, Claude runs the tactic with debug tracing, retrieves the hint database contents for every database that was consulted, and classifies each hint into one of three categories:

- **Matched:** Applied successfully as part of a (potentially incomplete) search path.
- **Attempted but rejected:** The search engine tried this hint but unification failed, an evar was left, or some other specific check prevented it.
- **Not considered:** The hint was filtered before any attempt — wrong database, head symbol mismatch, or Hint Mode prevented it.

For each rejected or filtered hint, the diagnosis names the specific failure reason from the classified set. For each diagnosis, Claude provides a fix: switch to `eauto`, increase the depth to N, add `with mydb`, use explicit `apply`, or adjust the hint registration.

When the depth limit is the bottleneck, the diagnosis reports the minimum depth required — not just "depth exceeded" but "this proof needs depth 7; try `auto 7`."

When a hint would succeed with `eauto` but not `auto`, the diagnosis states this explicitly: "This hint leaves an existential variable for `?m`. `auto` rejects hints that leave evars; `eauto` does not. Try `eauto` or `eauto with mydb`."

### Specific Hint Query

A narrower variant for when the user knows which hint they expected to fire. Given a lemma name and a goal, Claude focuses the diagnosis on that single hint: was it in the consulted database? Did the head symbol match? Did unification succeed? If `simple apply` failed but `apply` would succeed, Claude explains the weaker unification used by `auto` and suggests alternatives.

This mode avoids flooding the user with information about hundreds of irrelevant hints when they already know which one they care about.

### Success Path Explanation

When `auto` succeeds but the user wants to understand *how* — or wants to know why a preferred lemma was not used — Claude extracts the winning proof path and explains each step. If the user names a specific lemma they expected `auto` to use, Claude explains why it was not preferred: lower priority, later in the database order, or rejected at a branching point where another hint matched first.

This matters for controlling proof dependencies. A user who wants their proof to depend on lemma A, not lemma B, needs to understand why `auto` chose B — and how to steer it (adjust priorities, reorder databases, use explicit `auto using A`).

### Variant Comparison

When the user is unsure whether to use `auto`, `eauto`, or `typeclasses eauto`, Claude runs all three against the current goal and reports which succeeded, which failed, and why. The report highlights the concrete behavioral differences that mattered for this goal — not a generic comparison, but "on *your* goal, `auto` failed because hint X leaves an evar; `eauto` succeeded because it allows evars; `typeclasses eauto` failed because it only consults `typeclass_instances` and X is not registered there."

This includes showing the effective databases and transparency settings for each variant, so the user can verify their expectations about what `auto with mydb` actually consults.

### Effective Configuration Display

For subtle failures — opacity, transparency, priority ordering, `auto using` vs. `Hint Resolve` inconsistencies — the user needs to see the effective configuration, not just the trace. Claude reports: which databases were consulted and in what order, the transparency setting for each database, any active Hint Mode constraints, and the full hint inventory for the relevant head symbol.

When the trace reveals that `auto using foo` would succeed but `Hint Resolve foo` followed by `auto` fails (a known Coq inconsistency where the two paths use different unification engines), Claude identifies this pattern and explains the workaround.

## Scope

Auto Trace Explanation provides:

- Structured diagnosis of failed `auto` and `eauto` invocations with per-hint failure classification
- Targeted diagnosis for a specific expected hint ("why not this lemma?")
- Explanation of successful `auto` paths and why alternative hints were not preferred
- Side-by-side comparison of `auto`, `eauto`, and `typeclasses eauto` on a given goal
- Display of effective database configuration including transparency and Hint Mode settings
- Actionable fix suggestions for every diagnosed failure
- An MCP tool accessible within active proof sessions

Auto Trace Explanation does not provide:

- Modifications to Coq's `auto`/`eauto` implementation or debug trace format
- Automated fix application — fixes are suggested, not applied (proof repair is a separate initiative)
- General tactic debugging for non-`auto` tactics (e.g., `rewrite`, `inversion`, `apply` — those are separate concerns)
- Typeclass resolution tracing (covered by the Typeclass Debugging feature's `trace_resolution` tool)
- Hint database authoring or reorganization tools
- IDE integration — the tool runs within Claude Code via MCP

---

## Design Rationale

### Why this is separate from Tactic Documentation

Tactic Documentation answers "what does this tactic do?" Auto Trace Explanation answers "why didn't this tactic work on *my* goal?" The two are complementary but serve fundamentally different purposes. Documentation is reference material — it describes behavior in general terms. Trace explanation is diagnostic — it examines a specific failure in a specific proof state and produces a specific answer. Tactic Documentation tells you that `auto` only searches the `core` database by default; Auto Trace Explanation tells you that *your* hint is in `mydb` and that is why `auto` ignored it.

The implementation also differs. Tactic Documentation wraps `Print Ltac`, `Print HintDb`, and `Print Strategy` — static queries that return reference information. Trace explanation requires running the tactic in the proof session, capturing and parsing the debug trace, cross-referencing it with database contents, and synthesizing a diagnosis. The tools share some infrastructure (hint database inspection) but the diagnostic workflow is distinct.

### Why an MCP tool rather than a slash command

Slash commands in Poule are reserved for multi-step agentic workflows that orchestrate several tools and make complex decisions — `/explain-error` parses an error, fetches definitions, analyzes coercions, and synthesizes a diagnosis. Auto trace diagnosis, while internally multi-step, has a narrow and predictable input-output contract: given a proof state and a tactic, return a structured diagnosis. This fits the MCP tool pattern — Claude invokes it when the user asks about an `auto` failure, and the tool returns a self-contained result. Claude can compose it with other tools (hint database inspection, tactic comparison) when the user's question requires broader context, but the core diagnostic is a single tool call with a single response.

### Why LLM interpretation of debug traces is the right approach

Coq's `debug auto` output is a flat, depth-annotated log: `depth=5 apply H2`, `depth=4 simple apply H1 (*fail*)`. This log contains enough information to reconstruct the search tree and classify failures, but doing so manually requires understanding `auto`'s search strategy, the semantics of `simple apply` vs `apply`, and the hint database's internal filtering logic. An LLM that can parse this structured (but unintuitive) output and map it to classified failure reasons provides exactly the translation layer that is missing — the same approach that makes Typeclass Debugging effective.

The alternative — building structured trace output directly in Coq — would require modifying Coq's tactic engine, which is out of scope and out of Poule's control. The Coq project has explicitly declined to improve `Info auto` (issue #4587, "won't fix") and has not resolved the semantic divergence between `debug auto` and `auto` (issue #4064, open since 2015). Poule works with Coq as it is, interpreting its existing output rather than waiting for upstream improvements.

### Handling the `debug auto` semantic divergence

`debug auto` is known to have different behavior from `auto` — it wraps `Hint Extern` entries with `once`, preventing backtracking. This means a goal that `auto` solves can fail under `debug auto`, and vice versa. The diagnostic cannot naively trust `debug auto` output as representative of `auto` behavior.

The approach is to run both: first `auto` (to determine whether it succeeds or fails), then `debug auto` (to capture the trace), and reconcile any divergence. When `auto` succeeds but `debug auto` fails, the diagnosis notes the discrepancy and falls back to `info_auto` to capture the winning path. When both fail, the `debug auto` trace is used for hint classification with the caveat that `Hint Extern` backtracking behavior may differ. The diagnosis flags this when `Hint Extern` entries appear in the trace, so the user knows the trace may not perfectly represent `auto`'s actual behavior.

### Relationship to Typeclass Debugging

Typeclass resolution (`typeclasses eauto`) uses a search engine that is related to but distinct from the `auto`/`eauto` hint engine. The key differences: `typeclasses eauto` consults the `typeclass_instances` database rather than `core`, supports multi-goal backtracking (it can undo across subgoals), respects Hint Mode constraints, and counts intro steps against the depth limit. The Typeclass Debugging feature's `trace_resolution` tool handles that engine.

Auto Trace Explanation handles the `auto`/`eauto` engine specifically. When the user's question spans both — "why does `auto` fail but `typeclasses eauto` succeed?" — the variant comparison capability coordinates both diagnostic approaches and presents a unified explanation. But the underlying diagnostic logic is separate because the two engines have different search strategies, different database defaults, and different failure modes.

---

## Acceptance Criteria

### Explain Why Auto Failed

**Priority:** P0
**Stability:** Stable

- GIVEN an active proof session with an open goal WHEN the user asks why `auto` failed THEN the tool runs `auto` with debug tracing, parses the output, and returns a structured report listing each hint that was considered, attempted, or filtered
- GIVEN a goal where `auto` fails because the relevant hint is registered in a database not consulted by default WHEN the diagnosis is requested THEN the report identifies the database gap and suggests `auto with <db>`
- GIVEN a goal where `auto` fails because the default depth (5) is insufficient WHEN the diagnosis is requested THEN the report states the minimum depth required and suggests `auto <N>`
- GIVEN a goal where `auto` fails but `eauto` would succeed (because a hint leaves existential variables) WHEN the diagnosis is requested THEN the report explicitly states that `eauto` would succeed and explains the evar distinction
- GIVEN a goal where no hints in scope match the head symbol WHEN the diagnosis is requested THEN the report explains the head symbol filtering and suggests alternative tactics or manual `apply`

**Traces to:** AT-P0-1, AT-P0-2, AT-P0-3, AT-P0-4, AT-P0-5, AT-P0-6, AT-P0-7

### Explain Why a Specific Hint Was Not Used

**Priority:** P1
**Stability:** Stable

- GIVEN an active proof session, a goal, and the name of a lemma registered as a hint WHEN the user asks why that specific hint was not used by `auto` THEN the tool returns a focused explanation of the rejection reason for that specific hint
- GIVEN a hint registered via `Hint Resolve` whose `simple apply` unification fails but whose full `apply` succeeds WHEN the diagnosis is requested THEN the report explains the weaker unification used by `auto` and suggests `eapply` or explicit instantiation
- GIVEN a hint registered in database `mydb` but `auto` invoked without `with mydb` WHEN the diagnosis is requested THEN the report identifies the database mismatch
- GIVEN a hint whose conclusion has a universally quantified variable not appearing in the goal's conclusion WHEN the diagnosis is requested THEN the report explains that `auto` cannot instantiate such variables and suggests `eauto`

**Traces to:** AT-P1-1

### Explain Which Proof Path Auto Chose

**Priority:** P1
**Stability:** Stable

- GIVEN an active proof session where `auto` succeeds WHEN the user asks which path `auto` took THEN the tool returns the winning tactic sequence (as `info_auto` would) along with an explanation of why each step was selected
- GIVEN a goal where `auto` chose hint A over the user's expected hint B WHEN the user asks why B was not preferred THEN the report explains the ordering: priority, cost, database order, or definition order
- GIVEN a goal where `auto` succeeds with a suboptimal proof (e.g., longer path, unnecessary axiom) WHEN the user asks for alternatives THEN the report identifies whether other hint paths existed and why they ranked lower

**Traces to:** AT-P1-2

### Distinguish Auto, Eauto, and Typeclasses Eauto

**Priority:** P1
**Stability:** Stable

- GIVEN an active proof session with an open goal WHEN the user asks Claude to compare automation variants THEN the tool runs each variant against the goal and reports: which succeeded, which failed, and the key behavioral differences that explain the divergence
- GIVEN a goal where `auto` fails but `eauto` succeeds WHEN the comparison is requested THEN the report identifies the specific hint that required evar instantiation and explains why `auto` rejected it
- GIVEN a goal where `typeclasses eauto` succeeds but `eauto` fails WHEN the comparison is requested THEN the report explains the different databases consulted (`typeclass_instances` vs. `core`) and any Hint Mode constraints that affected resolution
- GIVEN a goal where all three fail WHEN the comparison is requested THEN the report provides a unified diagnosis covering the union of attempted hints and their failure reasons, with a suggestion for an alternative approach

**Traces to:** AT-P1-3

### Show Effective Databases and Transparency Settings

**Priority:** P1
**Stability:** Stable

- GIVEN an active proof session and a failed `auto` or `eauto` invocation WHEN the user asks to see the effective configuration THEN the tool lists: the databases consulted (in order), the transparency setting for each database, and any Hint Mode constraints in effect
- GIVEN a database created implicitly (via `Create HintDb` without transparency argument) WHEN the effective settings are shown THEN the report notes that the database defaults to opaque transparency and explains the implication for unification
- GIVEN `auto using foo` vs. `Hint Resolve foo` + `auto` WHEN the user encounters different behavior between the two THEN the report explains the known unification path inconsistency and recommends a workaround

**Traces to:** AT-P1-4, AT-P1-5

### Visualize the Hint Search Tree

**Priority:** P2
**Stability:** Draft

- GIVEN an active proof session and a failed or succeeded `auto`/`eauto` invocation WHEN visualization is requested THEN the tool generates a tree diagram showing each hint application attempt as a node, with edges labeled by tactic, and failure reasons annotated on rejected branches
- GIVEN a search tree with more than 50 nodes WHEN visualization is requested THEN the diagram is pruned to show the most relevant branches (winning path if succeeded, deepest failed paths if failed) with a summary of elided branches
- GIVEN a visualization request THEN the diagram is written to `proof-diagram.html` following the same convention as existing Poule visualization tools

**Traces to:** AT-P2-1

### Lint a Hint Database

**Priority:** P2
**Stability:** Draft

- GIVEN a hint database name WHEN the lint tool is invoked THEN it reports: hints with transparency mismatches (registered in an opaque database but requiring transparent unification), hints that shadow other hints due to identical patterns with different priorities, and Hint Extern patterns that are unreachable because a Hint Resolve with lower cost matches first
- GIVEN a project with multiple custom hint databases WHEN linting is requested without specifying a database THEN the tool lints all non-default databases and reports cross-database issues (hints registered in a database that no `auto with` invocation ever consults)
- GIVEN a lint report with no issues found THEN the tool confirms the database is clean rather than producing an empty result

**Traces to:** AT-P2-3, AT-P2-4
