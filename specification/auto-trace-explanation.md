# Auto Trace Explanation

Diagnosing `auto`/`eauto` hint search failures by capturing debug traces, parsing them into search trees, cross-referencing with hint database contents, classifying each hint rejection, and producing fix suggestions.

**Architecture**: [auto-trace-explanation.md](../doc/architecture/auto-trace-explanation.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the Auto Trace Analyzer component that captures Coq's auto debug output during a live proof session, parses the flat depth-annotated trace into a search tree, cross-references each hint against the consulted databases and the goal, classifies hint rejections into nine named reasons, and returns a structured diagnosis with per-hint fix suggestions. The component also supports focused single-hint queries and side-by-side comparison of `auto`, `eauto`, and `typeclasses eauto` on the same goal.

## 2. Scope

**In scope**: Debug trace capture with state preservation, trace parsing (depth-annotated lines to tree), hint classification (matched / attempted-but-rejected / not-considered), rejection reason assignment (9 classified reasons), fix suggestion generation, single-hint focused query, variant comparison across `auto`/`eauto`/`typeclasses eauto`, effective database configuration reporting.

**Out of scope**: MCP protocol handling (owned by mcp-server), session lifecycle management (owned by proof-session), hint database parsing (owned by tactic-documentation via `hint_inspect`), typeclass resolution tracing (owned by typeclass-debugging via `trace_resolution`), proof search execution (owned by proof-search-engine), natural language explanation generation (owned by the LLM layer), automated fix application.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Auto-family tactic | One of `auto`, `eauto`, `auto N`, `eauto N`, `auto with <db>`, `eauto with <db>`, `typeclasses eauto` |
| Debug trace | The sequence of depth-annotated messages Coq emits when `Set Debug "auto"` is active and an auto-family tactic executes |
| Remaining depth | The `depth=N` annotation on each trace line; decreases as the search goes deeper (root has the highest value) |
| Search tree | A tree of AutoSearchNode records reconstructed from the flat trace by interpreting remaining-depth values as parent-child relationships |
| Hint classification | Assignment of each hint in scope to one of: `matched` (applied successfully), `attempted_but_rejected` (tried and failed), `not_considered` (filtered before attempt) |
| Rejection reason | One of nine classified failure modes: `evar_rejected`, `unification_failure`, `depth_exhausted`, `wrong_database`, `head_symbol_mismatch`, `opacity_mismatch`, `resolve_extern_mismatch`, `quantified_vars_not_in_conclusion`, `priority_shadowed` |
| Consulted databases | The set of hint databases the tactic searches: `core` by default, plus any databases named in a `with` clause |
| Head symbol | The outermost constant or inductive in the goal type; used by the hint engine to filter candidate hints before attempting unification |
| Semantic divergence caveat | A warning included when the fallback `debug auto` tactic was used instead of `Set Debug "auto"` with the real tactic, because `debug auto` wraps `Hint Extern` entries with `once` |

## 4. Behavioral Requirements

### 4.1 Trace Capture

#### capture_trace(session_id, tactic)

- REQUIRES: `session_id` references an active proof session with at least one open goal. `tactic` is a non-empty string naming an auto-family tactic.
- ENSURES: Saves the current proof state position. Sends `Set Debug "auto".` to the session backend. Submits `try (<tactic>)` and captures the debug messages and the outcome (succeeded or failed). Sends `Unset Debug "auto".` to the session backend. When the inner tactic succeeded (goal changed), issues `step_backward` to restore the original proof state. Returns a RawTraceCapture record.
- MAINTAINS: The proof session's proof state is identical before and after the call. The `Debug "auto"` flag is never left enabled across tool calls — even when an error occurs mid-operation.

> **Given** a proof session at goal `n + 0 = n` with `Nat.add_0_r` in hint database `core`
> **When** `capture_trace(session_id, "auto")` is called
> **Then** debug messages are captured, `outcome = "succeeded"`, the proof state is restored to `n + 0 = n`, and `Debug "auto"` is unset

> **Given** a proof session at goal `n + 0 = n` where `auto` fails (no matching hint)
> **When** `capture_trace(session_id, "auto")` is called
> **Then** debug messages are captured, `outcome = "failed"`, the proof state is unchanged (try caught the failure), and `Debug "auto"` is unset

> **Given** a proof session where the backend crashes during `try (auto)`
> **When** `capture_trace(session_id, "auto")` is called
> **Then** a `BACKEND_CRASHED` error is returned (debug flag cleanup is impossible)

#### Fallback to `debug auto`

When the backend does not emit trace messages with `Set Debug "auto"` (empty `messages` list after tactic execution), the component shall retry using `debug auto` as the tactic string instead of the user's original tactic:

1. Submit `try (debug auto)` and capture messages.
2. When `Hint Extern` entries appear in the captured messages, set `semantic_divergence_caveat` on the returned RawTraceCapture.

> **Given** a Coq version that does not emit trace messages via `Set Debug "auto"`
> **When** `capture_trace(session_id, "auto")` is called and the first attempt returns empty messages
> **Then** the component retries with `try (debug auto)` and returns the captured messages with `semantic_divergence_caveat` set if `Hint Extern` entries were detected

#### Cleanup guarantee

When an error occurs after `Set Debug "auto".` has been sent but before `Unset Debug "auto".` has been sent, the component shall issue `Unset Debug "auto".` before returning the error. The sole exception is `BACKEND_CRASHED`, where cleanup is impossible.

### 4.2 Trace Parsing

#### parse_trace(messages)

- REQUIRES: `messages` is a list of strings (may be empty).
- ENSURES: Parses each line matching the pattern `depth=<N> <action> [(*fail*)]` into an AutoSearchNode. Reconstructs a tree by treating remaining-depth values as parent-child indicators: a line at depth N is a child of the most recent line at depth N+1. Returns an AutoSearchTree.
- MAINTAINS: Pure function; no side effects.

**Line parsing rules:**

1. When a line matches `depth=<N> <action>` without `(*fail*)`, the parser shall create a node with `remaining_depth = N` and `outcome = "success"` (tentatively; may be overridden if all children fail).
2. When a line matches `depth=<N> <action> (*fail*)`, the parser shall create a node with `remaining_depth = N` and `outcome = "failure"`.
3. When the action contains `simple apply <name>`, `exact <name>`, or `apply <name>`, the parser shall extract `<name>` as `hint_name`.
4. When the action is `intro`, the parser shall set `hint_name = null`.
5. When a line does not match any recognized pattern, the parser shall preserve it as raw text in the nearest enclosing node's `raw_line` field rather than raising a parse error.

**Tree construction rules:**

6. The parser shall maintain a stack of active nodes. When a new line appears at depth N, all nodes on the stack with remaining depth ≤ N are popped. The new node becomes a child of the node now at the top of the stack (which has remaining depth > N).
7. When the stack is empty, the new node is a root node.
8. After all lines are processed, `max_depth` is the highest remaining-depth value seen; `min_leaf_depth` is the lowest remaining-depth value among leaf nodes.

> **Given** messages `["depth=5 simple apply Nat.add_comm", "depth=4 exact eq_refl", "depth=4 simple apply Nat.add_0_r (*fail*)"]`
> **When** `parse_trace(messages)` is called
> **Then** an AutoSearchTree with one root node (`Nat.add_comm`, depth=5) containing two children (`eq_refl` success at depth=4, `Nat.add_0_r` failure at depth=4) is returned, with `max_depth = 5` and `min_leaf_depth = 4`

> **Given** an empty messages list
> **When** `parse_trace([])` is called
> **Then** an AutoSearchTree with empty `root_nodes`, `max_depth = 0`, and `min_leaf_depth = 0` is returned

> **Given** messages containing unrecognized lines interspersed with valid trace lines
> **When** `parse_trace(messages)` is called
> **Then** valid lines are parsed into nodes; unrecognized lines are preserved as raw text; no error is raised

#### Depth limit detection

9. When the search tree contains a leaf node with `remaining_depth = 1` and `outcome = "failure"` that is not marked with `(*fail*)` in the action (i.e., the failure is due to depth exhaustion, not unification), the parser shall set a flag `depth_limit_reached = true` on the AutoSearchTree.
10. The minimum required depth shall be estimated as `max_depth - min_leaf_depth + 1`.

### 4.3 Hint Classification

#### classify_hints(search_tree, hint_databases, proof_state)

- REQUIRES: `search_tree` is an AutoSearchTree. `hint_databases` is a list of HintDatabase records (as defined in the [tactic-documentation specification](tactic-documentation.md)). `proof_state` is the ProofState at the point of diagnosis.
- ENSURES: For every HintEntry in every provided HintDatabase, and for every hypothesis in `proof_state`, produces a HintClassification record. Returns the complete list.
- MAINTAINS: Pure function; no side effects.

**Classification rules:**

1. When a hint's `name` appears in a trace node's `hint_name` field and that node has `outcome = "success"`, the hint's classification shall be `matched`.
2. When a hint's `name` appears in a trace node's `hint_name` field and that node has `outcome = "failure"`, the hint's classification shall be `attempted_but_rejected`.
3. When a hint's `name` does not appear in any trace node, the hint's classification shall be `not_considered`.
4. When classifying hypotheses: for each hypothesis `H` in `proof_state.hypotheses`, the classifier shall check whether `H` appears in any trace node's action (e.g., `apply H`, `exact H`). If found, classify as `matched` or `attempted_but_rejected` per rules 1–2. If not found, classify as `not_considered`.

#### Evar rejection detection

5. When a hint is classified as `attempted_but_rejected` and its trace node has zero children (leaf failure), the classifier shall examine the hint's type signature (from HintEntry or via `coq_query("Check", "<name>")`) for universally quantified variables that do not appear in the conclusion. When such variables exist, the classifier shall tentatively assign `rejection_reason = "evar_rejected"`.
6. The evar detection shall not execute tactics. It operates solely on the hint's type signature and the trace structure.

> **Given** a search tree where `Nat.add_comm` appears with `outcome = "success"` and `Nat.mul_comm` does not appear
> **When** `classify_hints(tree, [core_db], state)` is called
> **Then** `Nat.add_comm` is classified as `matched` and `Nat.mul_comm` is classified as `not_considered`

> **Given** a search tree where `my_lemma` appears as a leaf failure, and `my_lemma`'s type is `forall n m p, n = p -> n = m` (where `p` does not appear in the conclusion `n = m`)
> **When** `classify_hints(tree, [db], state)` is called
> **Then** `my_lemma` is classified as `attempted_but_rejected` with `rejection_reason = "evar_rejected"`

### 4.4 Failure Diagnosis

#### diagnose_failures(classifications, search_tree, consulted_databases, goal)

- REQUIRES: `classifications` is a list of HintClassification records. `search_tree` is an AutoSearchTree. `consulted_databases` is a list of database names (in consultation order). `goal` is the goal text.
- ENSURES: For each HintClassification with classification `attempted_but_rejected` or `not_considered`, assigns a RejectionReason with a specific `reason`, `detail`, and `fix_suggestion`. Returns an AutoDiagnosis record.
- MAINTAINS: Pure function; no side effects.

**Rejection reason assignment for `not_considered` hints:**

1. When the hint's database is not in `consulted_databases`, the reason shall be `wrong_database` with fix `"Add 'with <db>' to the tactic invocation"`.
2. When the hint's database is in `consulted_databases` but the hint's pattern head symbol does not match the goal's head symbol, the reason shall be `head_symbol_mismatch` with fix `"Unfold the goal head or use 'apply <name>' directly"`.
3. When neither rule 1 nor rule 2 applies, the reason shall be `head_symbol_mismatch` with detail noting that Hint Mode or other filtering may have prevented consideration.

**Rejection reason assignment for `attempted_but_rejected` hints:**

4. When the classifier assigned `evar_rejected` (§4.3 rule 5), the reason shall be `evar_rejected` with fix `"Switch to 'eauto' or 'eauto with <db>'"`.
5. When the trace node is a leaf failure not classified as evar-related, and the search tree has `depth_limit_reached = true` and this node's `remaining_depth = 1`, the reason shall be `depth_exhausted` with fix `"Use '<tactic> <N>' with N >= <min_depth>"` where `<min_depth>` is the estimated minimum from §4.2 rule 10.
6. When the trace node is a leaf failure with `remaining_depth > 1` and has `(*fail*)` annotation, the reason shall be `unification_failure` with fix `"Use explicit 'apply <name>' with instantiation, or check argument types"`.
7. When rules 4–6 do not apply, the component shall attempt detection of `opacity_mismatch`, `resolve_extern_mismatch`, `quantified_vars_not_in_conclusion`, or `priority_shadowed` based on available metadata (database transparency from DatabaseConfig, hint type from HintEntry, type signature analysis). When none match, the reason shall be `unification_failure` as a fallback.

**Specificity ordering:**

8. When multiple rejection reasons could apply to the same hint, the component shall assign the most specific reason. Ordering from most to least specific: `evar_rejected` > `unification_failure` > `head_symbol_mismatch` > `wrong_database` > `depth_exhausted` > `opacity_mismatch` > `priority_shadowed`.

**Minimum depth calculation:**

9. When `depth_exhausted` is assigned to any hint, the component shall compute `min_depth_required` as the estimated minimum depth from §4.2 rule 10 and include it in the AutoDiagnosis.

**Success path extraction:**

10. When `search_tree` contains a root-to-leaf path where every node has `outcome = "success"`, the component shall extract this path as the `winning_path` in AutoDiagnosis.
11. When the user specified a `hint_name` and that hint is not on the winning path, the component shall include in the diagnosis an explanation of why the hint was not preferred: the winning hint had lower cost, appeared in an earlier database, or was tried first at a branching point.

> **Given** classifications where `my_hint` is `not_considered` and `my_hint` is in database `mydb` which is not in `consulted_databases = ["core"]`
> **When** `diagnose_failures(classifications, tree, ["core"], goal)` is called
> **Then** `my_hint` receives `reason = "wrong_database"`, `detail` mentioning `mydb` is not consulted, and `fix_suggestion = "Add 'with mydb' to the tactic invocation"`

> **Given** classifications where `my_lemma` is `attempted_but_rejected` with `evar_rejected`
> **When** `diagnose_failures(classifications, tree, dbs, goal)` is called
> **Then** `my_lemma` receives `reason = "evar_rejected"` and `fix_suggestion = "Switch to 'eauto' or 'eauto with <db>'"`

> **Given** a search tree with `depth_limit_reached = true`, `max_depth = 5`, `min_leaf_depth = 1`
> **When** `diagnose_failures(classifications, tree, dbs, goal)` is called
> **Then** `min_depth_required = 5` and depth-limited hints receive `fix_suggestion = "Use 'auto 5' or 'eauto 5'"`

### 4.5 Variant Comparison

#### compare_variants(session_id)

- REQUIRES: `session_id` references an active proof session with at least one open goal.
- ENSURES: Runs the full capture → parse → classify → diagnose pipeline for each of `auto`, `eauto`, and `typeclasses eauto`. Produces a VariantComparison containing per-variant outcomes, divergence points (hints where variants behaved differently), and effective database configuration per variant.
- MAINTAINS: The proof session's proof state is identical before and after the call. Debug flags are cleaned up after each variant's capture.

**Per-variant configuration:**

1. For `auto`: consulted databases = `core` (default).
2. For `eauto`: consulted databases = `core` (default).
3. For `typeclasses eauto`: consulted databases = `typeclass_instances`.
4. When the user's original tactic included a `with` clause, the same clause shall be applied to `auto` and `eauto` variants but not to `typeclasses eauto`.
5. When the user's original tactic included a depth override `N`, the same depth shall be applied to `auto` and `eauto` variants but not to `typeclasses eauto`.

**Divergence detection:**

6. For each hint that appears in any variant's classifications, the comparator shall check whether all variants assigned the same classification. When classifications differ, a DivergencePoint is created with per-variant classifications and an explanation of the divergence.
7. Common divergence patterns the comparator shall recognize:
   - `auto` rejected a hint as `evar_rejected` but `eauto` classified it as `matched` → explanation: "auto rejects hints that leave existential variables; eauto allows them"
   - `auto`/`eauto` classified a hint as `not_considered` (wrong database) but `typeclasses eauto` classified it as `matched` → explanation: "this hint is registered in typeclass_instances, not core"
   - All three failed but at different depths → explanation: "all variants exhausted depth; eauto reached depth N, auto reached depth M"

> **Given** a goal where `auto` fails (evar rejection) but `eauto` succeeds via `my_hint`
> **When** `compare_variants(session_id)` is called
> **Then** a VariantComparison is returned with `auto.outcome = "failed"`, `eauto.outcome = "succeeded"`, and a DivergencePoint for `my_hint` explaining the evar distinction

> **Given** a goal where all three variants fail
> **When** `compare_variants(session_id)` is called
> **Then** a VariantComparison is returned with all outcomes `"failed"` and divergence points showing the union of attempted hints across all three variants

### 4.6 Top-Level Tool

#### diagnose_auto(session_id, tactic?, hint_name?, compare_variants?)

- REQUIRES: `session_id` references an active proof session with at least one open goal. `tactic` is a valid auto-family tactic string (default: `"auto"`). `hint_name`, when provided, is a non-empty string. `compare_variants` is a boolean (default: false).
- ENSURES: Orchestrates trace capture (§4.1), trace parsing (§4.2), hint database retrieval (via tactic-documentation's `hint_inspect`), hint classification (§4.3), and failure diagnosis (§4.4). When `hint_name` is provided, filters the classifications to report only that hint. When `compare_variants` is true, additionally runs variant comparison (§4.5). Returns an AutoDiagnosis record.
- MAINTAINS: The proof session's proof state is identical before and after the call.

**Database retrieval:**

1. The component shall determine the consulted databases from the tactic string: `core` by default; additional databases from `with <db1> <db2> ...` clauses.
2. For each consulted database, the component shall call `hint_inspect(db_name, session_id)` (from the [tactic-documentation specification](tactic-documentation.md)) to obtain a HintDatabase record.
3. When `hint_inspect` returns a `NOT_FOUND` error for a database, the component shall include that database name in the diagnosis with a note that the database does not exist.

**Focused hint query (hint_name provided):**

4. When `hint_name` is provided, the component shall search all databases available via `hint_inspect` — not just the consulted databases — to locate the hint. If the hint is found in a non-consulted database, it shall be included in classification and diagnosed as `wrong_database`. If the hint is not found in any available database, the component shall return a `NOT_FOUND` error: `Hint "<name>" not found in any consulted database.`
5. When `hint_name` is provided and the name appears in a database, the component shall filter the classifications list to the single entry for that hint and return the focused diagnosis.

> **Given** a proof session at goal `n + 0 = n` where `auto` fails because `Nat.add_0_r` is in `arith` but not `core`
> **When** `diagnose_auto(session_id, "auto")` is called
> **Then** an AutoDiagnosis is returned with `Nat.add_0_r` classified as `not_considered`, `reason = "wrong_database"`, and `fix_suggestion = "Add 'with arith'"`

> **Given** a proof session at the same goal
> **When** `diagnose_auto(session_id, "auto", hint_name="Nat.add_0_r")` is called
> **Then** the same diagnosis is returned but `classifications` contains only the entry for `Nat.add_0_r`

> **Given** a proof session at goal `exists x, x = 0` where `auto` fails but `eauto` succeeds
> **When** `diagnose_auto(session_id, "auto", compare_variants=true)` is called
> **Then** an AutoDiagnosis is returned with `variant_comparison` populated, showing `auto` failed and `eauto` succeeded

## 5. Data Model

### RawTraceCapture

| Field | Type | Constraints |
|-------|------|-------------|
| `messages` | list of string | Required; may be empty (triggers fallback) |
| `outcome` | `"succeeded"` or `"failed"` | Required; outcome of the inner tactic |
| `goal` | string | Required; goal text at point of diagnosis |
| `tactic` | string | Required; the tactic that was diagnosed |
| `semantic_divergence_caveat` | string or null | Non-null when fallback to `debug auto` was used and `Hint Extern` entries detected |

### AutoSearchTree

| Field | Type | Constraints |
|-------|------|-------------|
| `root_nodes` | ordered list of AutoSearchNode | Required; may be empty |
| `max_depth` | non-negative integer | Required; 0 when `root_nodes` is empty |
| `min_leaf_depth` | non-negative integer | Required; 0 when `root_nodes` is empty |
| `depth_limit_reached` | boolean | Required; true when a leaf at depth=1 failed without `(*fail*)` |
| `raw_messages` | list of string | Required; original debug messages |

### AutoSearchNode

| Field | Type | Constraints |
|-------|------|-------------|
| `action` | string | Required; the tactic action attempted |
| `hint_name` | string or null | Extracted lemma or hypothesis name; null for `intro` steps |
| `remaining_depth` | positive integer | Required; the `depth=N` value from the trace |
| `outcome` | `"success"` or `"failure"` | Required |
| `children` | ordered list of AutoSearchNode | Required; empty for leaf nodes |
| `raw_line` | string | Required; original trace line |

### HintClassification

| Field | Type | Constraints |
|-------|------|-------------|
| `hint_name` | string | Required; fully qualified name |
| `hint_type` | `"resolve"` or `"unfold"` or `"constructors"` or `"extern"` or `"hypothesis"` | Required; `"hypothesis"` for local context entries |
| `database` | string or null | Required for database hints; null for hypotheses |
| `classification` | `"matched"` or `"attempted_but_rejected"` or `"not_considered"` | Required |
| `rejection_reason` | RejectionReason or null | Null when `classification = "matched"` |
| `trace_node` | AutoSearchNode or null | Null when `classification = "not_considered"` |

### RejectionReason

| Field | Type | Constraints |
|-------|------|-------------|
| `reason` | string | Required; one of: `evar_rejected`, `unification_failure`, `depth_exhausted`, `wrong_database`, `head_symbol_mismatch`, `opacity_mismatch`, `resolve_extern_mismatch`, `quantified_vars_not_in_conclusion`, `priority_shadowed` |
| `detail` | string | Required; human-readable explanation of the specific rejection |
| `fix_suggestion` | string | Required; concrete actionable fix |

### AutoDiagnosis

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic` | string | Required; the tactic that was diagnosed |
| `outcome` | `"succeeded"` or `"failed"` | Required |
| `goal` | string | Required; goal text |
| `classifications` | ordered list of HintClassification | Required; one per hint in scope (may be filtered to one when `hint_name` was provided) |
| `winning_path` | ordered list of AutoSearchNode or null | Null when tactic failed; root-to-leaf success path when succeeded |
| `min_depth_required` | positive integer or null | Non-null only when `depth_exhausted` was diagnosed |
| `databases_consulted` | ordered list of DatabaseConfig | Required; in consultation order |
| `variant_comparison` | VariantComparison or null | Non-null only when `compare_variants` was true |
| `semantic_divergence_caveat` | string or null | Propagated from RawTraceCapture |

### DatabaseConfig

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; database name |
| `transparency` | `"transparent"` or `"opaque"` | Required |
| `hint_count` | non-negative integer | Required |

### VariantComparison

| Field | Type | Constraints |
|-------|------|-------------|
| `variants` | ordered list of VariantResult | Required; length = 3 (auto, eauto, typeclasses eauto) |
| `divergence_points` | ordered list of DivergencePoint | Required; may be empty when all variants agree |

### VariantResult

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic` | string | Required; `"auto"`, `"eauto"`, or `"typeclasses eauto"` |
| `outcome` | `"succeeded"` or `"failed"` | Required |
| `databases_consulted` | ordered list of string | Required |
| `winning_path` | ordered list of AutoSearchNode or null | Null when tactic failed |

### DivergencePoint

| Field | Type | Constraints |
|-------|------|-------------|
| `hint_name` | string | Required |
| `per_variant` | map of string to HintClassification | Required; keyed by tactic name; 2–3 entries |
| `explanation` | string | Required; why variants diverged |

**Cross-reference**: HintDatabase, HintEntry, HintSummary are defined in [tactic-documentation.md](tactic-documentation.md) §5 and consumed by this component without modification.

## 6. Interface Contracts

### Auto Trace Analyzer -> Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `observe_proof_state(session_id)`, `submit_tactic(session_id, tactic)`, `step_backward(session_id)` |
| Concurrency | Serialized — one command at a time per session backend |
| Error strategy | `SESSION_NOT_FOUND` → return error immediately. `BACKEND_CRASHED` → return error (cleanup impossible). Tactic failure inside `try` wrapper → not an error (proof state unchanged). |
| Idempotency | Not required — the operation is diagnostic and leaves no persistent side effects after state restoration. |
| State preservation | The component shall restore the proof state to its pre-diagnosis position. `try` wrapper prevents tactic errors from blocking cleanup. `step_backward` reverses successful tactic application. |

### Auto Trace Analyzer -> Session Backend (direct)

| Property | Value |
|----------|-------|
| Operations used | `execute_vernacular` for `Set Debug "auto".` and `Unset Debug "auto".` |
| Rationale | Debug flag commands modify Coq's global state and bypass `coq_query` (which is read-only). Follows the same pattern as typeclass-debugging's `Set Typeclasses Debug`. |
| Concurrency | Serialized — same backend as proof session operations, never concurrent. |
| Cleanup guarantee | `Unset Debug "auto".` is sent in a `finally` path. Exception: `BACKEND_CRASHED`, where cleanup is impossible. |

### Auto Trace Analyzer -> Tactic Documentation Handler

| Property | Value |
|----------|-------|
| Operations used | `hint_inspect(db_name, session_id)` |
| Types consumed | HintDatabase, HintEntry, HintSummary (no duplication) |
| Error strategy | `NOT_FOUND` from `hint_inspect` → recorded in diagnosis as a missing database, not propagated as a top-level error. `BACKEND_CRASHED` → propagated. `TIMEOUT` → propagated. |

### MCP Server -> Auto Trace Analyzer

| Property | Value |
|----------|-------|
| Tool exposed | `diagnose_auto` |
| Input validation | MCP Server validates parameter presence and types. Analyzer validates semantic constraints (auto-family tactic, non-empty hint name). |
| Response format | AutoDiagnosis record serialized to JSON by MCP Server. |

## 7. State and Lifecycle

The Auto Trace Analyzer is stateless across invocations. Each `diagnose_auto` call is self-contained: it borrows the session, performs the diagnosis, restores the session state, and returns. No data is cached between calls.

### State transitions during a single invocation

| Step | Session state | Debug flag |
|------|--------------|------------|
| Entry | Goal at user's position | Unset |
| After `Set Debug "auto".` | Goal at user's position | Set |
| After `submit_tactic("try (<tactic>)")` — tactic failed | Goal at user's position (unchanged by `try`) | Set |
| After `submit_tactic("try (<tactic>)")` — tactic succeeded | Goal changed (tactic advanced) | Set |
| After `Unset Debug "auto".` | Same as previous row | Unset |
| After `step_backward` (only when tactic succeeded) | Goal at user's position (restored) | Unset |
| Exit | Goal at user's position | Unset |

When an error occurs at any step after `Set Debug "auto".`, the component transitions directly to the cleanup step (`Unset Debug "auto".`) before returning. When an error occurs during cleanup itself (`BACKEND_CRASHED`), cleanup is abandoned.

## 8. Error Specification

### 8.1 Input Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `tactic` is empty | `INVALID_ARGUMENT` | `Tactic must not be empty.` |
| `tactic` is not an auto-family tactic | `INVALID_ARGUMENT` | `"<tactic>" is not an auto-family tactic. Supported: auto, eauto, auto with <db>, eauto with <db>, auto <N>, eauto <N>, typeclasses eauto.` |
| `hint_name` is provided but empty | `INVALID_ARGUMENT` | `Hint name must not be empty.` |

### 8.2 State Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `session_id` references non-existent session | `SESSION_NOT_FOUND` | `Proof session "<session_id>" not found or has expired.` |
| No open goal in session | `NO_GOAL` | `No open goal to diagnose.` |
| `hint_name` not found in any available database (consulted and probed) | `NOT_FOUND` | `Hint "<name>" not found in any consulted database.` |

### 8.3 Dependency Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Backend crashed during diagnosis | `BACKEND_CRASHED` | `The Coq backend has crashed. Close the session and open a new one.` |
| Debug output capture timed out (> 10 seconds) | `TIMEOUT` | `Auto diagnosis timed out after 10 seconds. The hint search may be non-terminating; try a lower depth.` |
| Trace parsing failed | `PARSE_ERROR` | `Failed to parse auto debug output. Raw output included in response.` |

### 8.4 Edge Cases

| Condition | Behavior |
|-----------|----------|
| Empty trace (no debug messages and fallback also empty) | Return AutoDiagnosis with empty `classifications`; all hints from retrieved databases classified as `not_considered` with `reason = "head_symbol_mismatch"` (default when no trace data available) |
| `auto` succeeds but the user asks for diagnosis | Normal operation: trace is captured, winning path extracted, all non-winning hints classified |
| Tactic with `with` clause naming a non-existent database | `hint_inspect` returns `NOT_FOUND`; diagnosis notes the missing database but does not fail |
| `compare_variants` with a tactic that includes `with` or depth | `with`/depth applied to auto and eauto variants; `typeclasses eauto` runs with its own defaults |
| Trace contains thousands of lines | Parser processes all lines; no truncation of the search tree. Downstream classification respects `hint_inspect`'s truncation of large databases. |

## 9. Non-Functional Requirements

- Trace capture shall complete within 10 seconds (including tactic execution, debug output capture, and state restoration). When the 10-second deadline is reached, the component shall abort the tactic and return a `TIMEOUT` error.
- Trace parsing shall process up to 10,000 trace lines within 500 milliseconds.
- Hint classification shall complete within 1 second for up to 1,000 hints across all consulted databases.
- The full `diagnose_auto` pipeline (capture + parse + classify + diagnose) shall complete within 15 seconds for the common case of ≤ 200 hints in scope.
- Variant comparison shall complete within 45 seconds (three sequential diagnoses, each up to 15 seconds).
- The component shall not spawn additional OS processes; it reuses the session's existing backend.
- The component shall not cache results across invocations; each call queries live Coq state.

## 10. Examples

### Diagnosis — hint in wrong database

```
diagnose_auto(session_id="abc123", tactic="auto")

Goal: n + 0 = n
Consulted databases: ["core"]

Trace capture:
  Set Debug "auto".
  try (auto)  → failed (goal unchanged)
  Unset Debug "auto".

  Messages:
    depth=5 simple apply eq_refl (*fail*)

Hint database retrieval:
  hint_inspect("core") → 15 entries, none named "Nat.add_0_r"
  (Nat.add_0_r is registered in "arith", not consulted)

Result:
{
  "tactic": "auto",
  "outcome": "failed",
  "goal": "n + 0 = n",
  "classifications": [
    {
      "hint_name": "eq_refl",
      "hint_type": "resolve",
      "database": "core",
      "classification": "attempted_but_rejected",
      "rejection_reason": {
        "reason": "unification_failure",
        "detail": "eq_refl requires the LHS and RHS to be identical; n + 0 and n are not definitionally equal",
        "fix_suggestion": "Use explicit 'apply' with instantiation, or check argument types"
      },
      "trace_node": {"action": "simple apply eq_refl", "remaining_depth": 5, "outcome": "failure", ...}
    }
  ],
  "winning_path": null,
  "min_depth_required": null,
  "databases_consulted": [{"name": "core", "transparency": "transparent", "hint_count": 15}],
  "variant_comparison": null,
  "semantic_divergence_caveat": null
}
```

### Diagnosis — evar rejection

```
diagnose_auto(session_id="def456", tactic="auto")

Goal: exists x : nat, x = 0
Consulted databases: ["core"]

Trace messages:
  depth=5 simple apply ex_intro (*fail*)

Classification:
  ex_intro: attempted_but_rejected (type: forall A P, ?x -> ex A P — ?x is uninstantiated)

Result:
{
  "tactic": "auto",
  "outcome": "failed",
  "goal": "exists x : nat, x = 0",
  "classifications": [
    {
      "hint_name": "ex_intro",
      "hint_type": "constructors",
      "database": "core",
      "classification": "attempted_but_rejected",
      "rejection_reason": {
        "reason": "evar_rejected",
        "detail": "ex_intro has universally quantified variable not determined by the conclusion; auto's simple apply rejects it",
        "fix_suggestion": "Switch to 'eauto' or 'eauto with core'"
      },
      "trace_node": {"action": "simple apply ex_intro", "remaining_depth": 5, "outcome": "failure", ...}
    }
  ],
  "winning_path": null,
  "min_depth_required": null,
  "databases_consulted": [{"name": "core", "transparency": "transparent", "hint_count": 15}],
  "variant_comparison": null,
  "semantic_divergence_caveat": null
}
```

### Variant comparison

```
diagnose_auto(session_id="def456", tactic="auto", compare_variants=true)

Goal: exists x : nat, x = 0

Result:
{
  "tactic": "auto",
  "outcome": "failed",
  ...
  "variant_comparison": {
    "variants": [
      {"tactic": "auto", "outcome": "failed", "databases_consulted": ["core"], "winning_path": null},
      {"tactic": "eauto", "outcome": "succeeded", "databases_consulted": ["core"], "winning_path": [
        {"action": "simple eapply ex_intro", "remaining_depth": 5, "outcome": "success", ...},
        {"action": "exact eq_refl", "remaining_depth": 4, "outcome": "success", ...}
      ]},
      {"tactic": "typeclasses eauto", "outcome": "failed", "databases_consulted": ["typeclass_instances"], "winning_path": null}
    ],
    "divergence_points": [
      {
        "hint_name": "ex_intro",
        "per_variant": {
          "auto": {"classification": "attempted_but_rejected", "rejection_reason": {"reason": "evar_rejected", ...}},
          "eauto": {"classification": "matched", "rejection_reason": null},
          "typeclasses eauto": {"classification": "not_considered", "rejection_reason": {"reason": "wrong_database", ...}}
        },
        "explanation": "auto rejects ex_intro because it leaves an existential variable; eauto allows existential variables and succeeds; typeclasses eauto does not consult the core database"
      }
    ]
  }
}
```

### Focused hint query

```
diagnose_auto(session_id="abc123", tactic="auto", hint_name="Nat.add_0_r")

Goal: n + 0 = n
Consulted databases: ["core"]
Nat.add_0_r found in database "arith" (not consulted)

Result:
{
  "tactic": "auto",
  "outcome": "failed",
  "goal": "n + 0 = n",
  "classifications": [
    {
      "hint_name": "Nat.add_0_r",
      "hint_type": "resolve",
      "database": "arith",
      "classification": "not_considered",
      "rejection_reason": {
        "reason": "wrong_database",
        "detail": "Nat.add_0_r is registered in database 'arith', but auto only consulted ['core']",
        "fix_suggestion": "Add 'with arith' to the tactic invocation"
      },
      "trace_node": null
    }
  ],
  ...
}
```

## 11. Language-Specific Notes (Python)

- Package location: `src/poule/auto_trace/`.
- Entry points: `async def diagnose_auto(session_id, tactic="auto", hint_name=None, compare_variants=False) -> AutoDiagnosis`.
- Internal functions: `async def capture_trace(session_id, tactic) -> RawTraceCapture`, `def parse_trace(messages) -> AutoSearchTree`, `def classify_hints(tree, dbs, state) -> list[HintClassification]`, `def diagnose_failures(classifications, tree, consulted, goal) -> AutoDiagnosis`, `async def compare_variants(session_id) -> VariantComparison`.
- Use `asyncio` for all operations that communicate with the session backend.
- Use `dataclasses` or Pydantic models for all data structures.
- Trace parser: implement as a stateful line-by-line parser with an explicit stack for tree construction. Use `re` module for the `depth=(\d+)\s+(.+?)(\s+\(\*fail\*\))?$` pattern.
- Cleanup guarantee: use `try`/`finally` around the debug capture sequence to ensure `Unset Debug "auto".` is always sent.
- The 10-second capture timeout is a constant (`AUTO_TRACE_CAPTURE_TIMEOUT_SECONDS`).
- The auto-family tactic validation shall use a regex matching `^(auto|eauto)(\s+\d+)?(\s+with\s+\w+(\s+\w+)*)?$|^typeclasses\s+eauto$`.
- For evar rejection detection (§4.3 rule 5): use `coq_query("Check", "<hint_name>", session_id)` to retrieve the hint's type, then parse for universally quantified variables. Do not execute tactics for this check.
- Import HintDatabase, HintEntry, HintSummary from `src/poule/tactics/` (tactic-documentation package) — do not duplicate.
