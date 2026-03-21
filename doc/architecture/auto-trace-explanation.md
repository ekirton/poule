# Auto Trace Explanation

The component that diagnoses `auto`/`eauto` hint search failures by capturing debug traces, parsing them into search trees, cross-referencing with hint database contents, and classifying each hint rejection with an actionable fix suggestion.

**Feature**: [Auto/Eauto Trace Explanation](../features/auto-trace-explanation.md)

---

## Component Diagram

```
MCP Server
  │
  │ diagnose_auto(session_id, tactic?, hint_name?)
  ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Auto Trace Analyzer                              │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ Trace Capture                                             │   │
│  │                                                           │   │
│  │  1. Save current proof state position                     │   │
│  │  2. Set Debug "auto"                                      │   │
│  │  3. Submit "try <tactic>" → capture messages + outcome    │   │
│  │  4. Unset Debug "auto"                                    │   │
│  │  5. Restore proof state (step_backward if needed)         │   │
│  │                                                           │   │
│  │  → RawTraceCapture (messages, outcome, goal)              │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Trace Parser                                              │   │
│  │                                                           │   │
│  │  Flat depth-annotated lines → AutoSearchTree              │   │
│  │  "depth=N tactic (*fail*)" → tree of AutoSearchNode       │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Hint Classifier                                           │   │
│  │                                                           │   │
│  │  AutoSearchTree + HintDatabase[] + ProofState             │   │
│  │    → HintClassification[] (matched / attempted / filtered)│   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                              │                                    │
│  ┌──────────────────────────▼────────────────────────────────┐   │
│  │ Failure Diagnoser                                         │   │
│  │                                                           │   │
│  │  HintClassification[] → RejectionReason per hint          │   │
│  │                       → FixSuggestion per hint            │   │
│  │                       → AutoDiagnosis                     │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ Variant Comparator                                        │   │
│  │                                                           │   │
│  │  Runs Trace Capture for auto, eauto, typeclasses eauto    │   │
│  │  Diffs results → VariantComparison                        │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
  │                     │                        │
  │ submit_tactic       │ coq_query              │ inspect_hint_db
  │ step_backward       │ (Set/Unset Debug,      │ (reuses HintDatabase
  │ observe_proof_state │  Print HintDb)         │  from tactic-documentation)
  ▼                     ▼                        ▼
Proof Session        Vernacular              Tactic Documentation
Manager              Introspection           Handler
```

The component does not own a Coq backend process. It borrows the backend associated with an active proof session, issues debug commands, captures their output, and restores the session state afterward.

## Tool Signature

```typescript
diagnose_auto(
  session_id: string,         // active proof session positioned at a goal
  tactic: string = "auto",    // tactic to diagnose: "auto", "eauto", "auto with <db>", etc.
  hint_name: string | null = null,  // if provided, focus diagnosis on this specific hint
  compare_variants: boolean = false // if true, run auto + eauto + typeclasses eauto and diff
) → AutoDiagnosis
```

When `hint_name` is provided, the response focuses on that single hint rather than reporting on all hints — the "why not this hint?" mode.

When `compare_variants` is true, the Variant Comparator runs all three auto-family tactics and returns a `VariantComparison` alongside the primary diagnosis.

## Trace Capture

The Trace Capture sub-component obtains debug output from the hint search engine without permanently altering the proof session state.

### Capture Protocol

```
diagnose_auto(session_id, tactic, ...)
  │
  ├─ observe_proof_state(session_id) → save ProofState, current_step
  │
  ├─ coq_query("Set", "Debug \"auto\".", session_id)
  │
  ├─ submit_tactic(session_id, "try (" ++ tactic ++ ")")
  │    │
  │    ├─ The "try" wrapper ensures the tactic always "succeeds" from Coq's
  │    │   perspective: if the inner tactic fails, try catches the failure
  │    │   and the goal is unchanged.
  │    │
  │    ├─ If the inner tactic succeeded: the goal changed (possibly to Qed-ready).
  │    │   Record outcome = "succeeded".
  │    │
  │    └─ If the inner tactic failed (try caught it): the goal is unchanged.
  │        Record outcome = "failed".
  │
  ├─ Capture the debug messages emitted during tactic execution.
  │   These are delivered as Coq feedback messages through the backend,
  │   separate from the proof state response.
  │
  ├─ coq_query("Unset", "Debug \"auto\".", session_id)
  │
  ├─ If outcome = "succeeded":
  │    └─ step_backward(session_id)  // restore to the pre-tactic state
  │
  └─ Return RawTraceCapture { messages, outcome, goal }
```

### Handling the `debug auto` Semantic Divergence

`debug auto` has different semantics from `auto` — it wraps `Hint Extern` entries with `once`, preventing backtracking (Coq issue #4064). The capture protocol works around this by running `auto` itself (not `debug auto`) with debug output enabled via `Set Debug "auto"`. This produces trace messages while preserving `auto`'s actual search semantics.

If the backend does not emit trace messages with `Set Debug "auto"` (behavior varies by Coq version), the protocol falls back to running `debug auto` as the tactic. When the fallback is used and `Hint Extern` entries appear in the trace, the diagnosis includes a caveat noting the potential semantic divergence.

### State Preservation

The component must not leave the proof session in a different state than it found it. The `try` wrapper ensures Coq does not raise an error (which would block subsequent commands). If the tactic succeeded inside `try`, a `step_backward` call restores the original state. If it failed inside `try`, the state is already unchanged.

Debug flags are set and unset within a single operation. If an error occurs after `Set Debug "auto"`, the component issues `Unset Debug "auto"` in a cleanup step before propagating the error.

## Trace Parser

### Debug Output Format

Coq's auto debug output consists of depth-annotated lines:

```
depth=5 apply H2
depth=4 simple apply Nat.add_comm
depth=3 exact H1
depth=3 simple apply Nat.add_comm (*fail*)
depth=4 intro
depth=3 simple apply H2 (*fail*)
```

Each line contains:
- **Remaining depth**: `depth=N` where N decreases as the search goes deeper (depth=5 is the root at the default max depth of 5, depth=1 is the deepest allowed step).
- **Action**: The tactic the hint engine attempted — typically `simple apply <lemma>`, `exact <lemma>`, or `intro`.
- **Failure annotation**: `(*fail*)` if the action did not produce a valid sub-state.

### Parsing into a Search Tree

The parser reconstructs the search tree from the flat log:

1. Read the captured debug messages line by line.
2. Extract depth, action, and failure status from each line by pattern matching on the `depth=N action (*fail*)?` format.
3. Build the tree by tracking a stack of active nodes. A line at depth N is a child of the most recent line at depth N+1 (higher remaining depth = closer to root). When a new line appears at depth ≥ the current node's depth, the current node is popped.
4. Mark each node as `success` or `failure` based on the `(*fail*)` annotation and whether the node has successful children.

Unrecognized lines (e.g., unification debug output interleaved with auto debug output) are preserved as raw text in the nearest enclosing node rather than causing a parse failure.

### Depth Limit Detection

When the search tree contains a leaf node at depth=1 that is not marked as failed for unification reasons, the parser flags this as a potential depth exhaustion. The minimum required depth is estimated as `max_depth - min_leaf_depth + 1` where `max_depth` is extracted from the root node's depth annotation.

## Hint Classifier

The Hint Classifier cross-references the parsed search tree with the hint database contents to classify every hint in scope.

### Inputs

1. **AutoSearchTree**: The parsed trace from the Trace Parser.
2. **HintDatabase[]**: The contents of every database consulted by the tactic, retrieved via the Tactic Documentation Handler's Hint Database Inspector. For `auto` with no `with` clause, this is the `core` database. For `auto with db1 db2`, it includes `core`, `db1`, and `db2`.
3. **ProofState**: The goal and hypotheses at the point of the failed tactic.

### Classification Logic

For each hint in the retrieved databases:

1. **Search the trace for the hint's lemma name.** If the name appears in an action line (`simple apply <name>`, `exact <name>`):
   - If the node is marked as success → classification = `matched`.
   - If the node is marked as failure → classification = `attempted_but_rejected`.

2. **If the hint name does not appear in the trace** → classification = `not_considered`. The classifier determines why:
   - **Head symbol mismatch**: Compare the hint's conclusion head symbol (from the `HintEntry` pattern field) against the goal's head symbol. If they differ, report head symbol mismatch.
   - **Database not consulted**: If the hint's database is not in the set of consulted databases, report this.
   - **Hint Mode filtered**: If a `Hint Mode` constraint is active for the relevant typeclass and the goal does not satisfy it, report this.

3. **Hints from hypotheses**: `auto` also tries local hypotheses. The classifier checks each hypothesis in the proof state against the trace. Hypotheses that appear as `apply H` or `exact H` in the trace are classified as matched or attempted.

### Identifying Evar Rejection

When a hint is `attempted_but_rejected` and the trace shows `simple apply <name> (*fail*)` at a node with no children, the classifier checks whether `eapply <name>` would succeed (i.e., whether the hint's conclusion has uninstantiated universals that do not appear in the goal's conclusion). This is the primary heuristic for detecting the auto/eauto distinction: `auto` uses `simple apply` (which rejects evars), while `eauto` uses `simple eapply` (which allows them).

The check is not performed by running `eapply` — that would require tactic execution. Instead, the classifier examines the hint's type signature (from the `HintEntry`) for universally quantified variables that do not appear in the conclusion. If such variables exist, the rejection is tentatively classified as `evar_rejected`.

## Failure Diagnoser

The Failure Diagnoser consumes the classified hints and produces a structured diagnosis with fix suggestions.

### Rejection Reasons

Each `attempted_but_rejected` or `not_considered` hint is assigned one of the following rejection reasons:

| Reason | Detection method | Fix suggestion |
|--------|-----------------|----------------|
| `evar_rejected` | Hint has quantified vars not in conclusion; `simple apply` failed at leaf | Switch to `eauto` or `eauto with <db>` |
| `unification_failure` | `simple apply <name> (*fail*)` with children that also failed | Use explicit `apply <name>` with instantiation, or check argument types |
| `depth_exhausted` | Search reached depth=1 without completing | Use `auto <N>` or `eauto <N>` with the minimum required depth |
| `wrong_database` | Hint's database not in consulted set | Add `with <db>` to the tactic invocation |
| `head_symbol_mismatch` | Hint's pattern head ≠ goal's head symbol | Unfold the goal head, or use `apply` directly |
| `opacity_mismatch` | Database uses opaque transparency; hint requires transparent unification | Adjust database transparency or use explicit `apply` |
| `resolve_extern_mismatch` | Hint registered as `Extern` with syntactic pattern that does not match the simplified goal shape | Re-register as `Hint Resolve`, or adjust the `Extern` pattern |
| `quantified_vars_not_in_conclusion` | Hint has universals not in conclusion, and `auto` (not `eauto`) was used | Switch to `eauto` |
| `priority_shadowed` | Hint exists and matches, but a lower-cost hint in the same or earlier database was applied first | Adjust hint priority or database order |

When multiple rejection reasons could apply, the diagnoser reports the most specific one. The ordering from most to least specific: `evar_rejected` > `unification_failure` > `head_symbol_mismatch` > `wrong_database` > `depth_exhausted` > `opacity_mismatch` > `priority_shadowed`.

### Minimum Depth Calculation

When `depth_exhausted` is diagnosed, the diagnoser estimates the minimum required depth by:

1. Finding the deepest successful partial path in the search tree.
2. Counting the remaining unsolved sub-goals at the deepest point.
3. Adding the partial path length and the estimated remaining depth.

This produces a lower-bound estimate. The diagnosis reports it as: "This proof needs at least depth N; try `auto N`."

### Success Path Reporting

When the tactic succeeded and the user asked for path explanation (no specific hint_name query), the diagnoser extracts the winning path from the search tree — the root-to-leaf sequence of nodes where every node is marked `success`. Each step in the path is annotated with the hint that was applied and its source database.

If the user specified a `hint_name`, the diagnoser locates that hint in the tree and explains why it was not on the winning path: lower priority, appeared in a later database, or was rejected at a branch where another hint matched first.

## Variant Comparator

When `compare_variants` is true, the comparator runs the full Trace Capture → Parser → Classifier → Diagnoser pipeline for each of three tactics:

1. `auto` (default databases)
2. `eauto` (default databases)
3. `typeclasses eauto` (`typeclass_instances` database)

The comparator then produces a `VariantComparison` by diffing the three results:

- **Which variants succeeded and which failed.**
- **Divergence points**: Hints that one variant used but another rejected, with the specific reason for divergence (evar handling, database scope, multi-goal backtracking).
- **Effective configuration per variant**: Databases consulted, transparency settings, Hint Mode constraints.

If the user's original tactic included a `with` clause or a depth override, the comparator applies the same modifiers to the `auto` and `eauto` variants but not to `typeclasses eauto` (which uses its own database).

## Data Structures

### RawTraceCapture

| Field | Type | Description |
|-------|------|-------------|
| `messages` | list of string | Debug messages emitted by the backend during tactic execution |
| `outcome` | `"succeeded"` or `"failed"` | Whether the inner tactic (inside `try`) solved the goal |
| `goal` | string | The goal text at the point of diagnosis |
| `tactic` | string | The tactic that was diagnosed |

### AutoSearchTree

| Field | Type | Description |
|-------|------|-------------|
| `root_nodes` | list of AutoSearchNode | Top-level hint application attempts |
| `max_depth` | positive integer | The maximum depth from the root node's depth annotation |
| `min_leaf_depth` | positive integer | The lowest depth reached in any branch |
| `raw_messages` | list of string | Original debug messages, preserved for fallback |

### AutoSearchNode

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | The tactic action attempted (e.g., `simple apply Nat.add_comm`) |
| `hint_name` | string or null | The lemma or hypothesis name extracted from the action (null for `intro` steps) |
| `remaining_depth` | positive integer | The `depth=N` value from the trace line |
| `outcome` | `"success"` or `"failure"` | Whether this node's action succeeded |
| `children` | list of AutoSearchNode | Sub-goal attempts spawned by this node |
| `raw_line` | string | The original trace line, preserved for fallback |

### HintClassification

| Field | Type | Description |
|-------|------|-------------|
| `hint_name` | string | Fully qualified lemma or constant name |
| `hint_type` | `"resolve"` or `"unfold"` or `"constructors"` or `"extern"` | From HintEntry |
| `database` | string | The hint database this hint is registered in |
| `classification` | `"matched"` or `"attempted_but_rejected"` or `"not_considered"` | How the search engine treated this hint |
| `rejection_reason` | RejectionReason or null | Null if `matched`; classified reason otherwise |
| `trace_node` | AutoSearchNode or null | The search tree node corresponding to this hint's attempt (null if `not_considered`) |

### RejectionReason

| Field | Type | Description |
|-------|------|-------------|
| `reason` | string | One of: `evar_rejected`, `unification_failure`, `depth_exhausted`, `wrong_database`, `head_symbol_mismatch`, `opacity_mismatch`, `resolve_extern_mismatch`, `quantified_vars_not_in_conclusion`, `priority_shadowed` |
| `detail` | string | Human-readable explanation of the specific rejection |
| `fix_suggestion` | string | Concrete fix (e.g., "Use `eauto` instead of `auto`", "Add `with mydb`", "Try `auto 7`") |

### AutoDiagnosis

| Field | Type | Description |
|-------|------|-------------|
| `tactic` | string | The tactic that was diagnosed |
| `outcome` | `"succeeded"` or `"failed"` | Whether the tactic solved the goal |
| `goal` | string | The goal text |
| `classifications` | list of HintClassification | Per-hint classification for all hints in scope |
| `winning_path` | list of AutoSearchNode or null | Root-to-leaf success path (null if tactic failed) |
| `min_depth_required` | positive integer or null | Estimated minimum depth if `depth_exhausted` was diagnosed; null otherwise |
| `databases_consulted` | list of DatabaseConfig | Databases that were searched, in order |
| `variant_comparison` | VariantComparison or null | Present only when `compare_variants` was true |
| `semantic_divergence_caveat` | string or null | Non-null when fallback to `debug auto` was used and `Hint Extern` entries were detected |

### DatabaseConfig

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Database name |
| `transparency` | `"transparent"` or `"opaque"` | Whether the database uses transparent or opaque conversion for unification |
| `hint_count` | non-negative integer | Number of hints in this database |

### VariantComparison

| Field | Type | Description |
|-------|------|-------------|
| `variants` | list of VariantResult | One entry per variant tested |
| `divergence_points` | list of DivergencePoint | Hints where variants behaved differently |

### VariantResult

| Field | Type | Description |
|-------|------|-------------|
| `tactic` | string | `"auto"`, `"eauto"`, or `"typeclasses eauto"` |
| `outcome` | `"succeeded"` or `"failed"` | Whether this variant solved the goal |
| `databases_consulted` | list of string | Database names in consultation order |
| `winning_path` | list of AutoSearchNode or null | Success path if the variant succeeded |

### DivergencePoint

| Field | Type | Description |
|-------|------|-------------|
| `hint_name` | string | The hint where behavior diverged |
| `per_variant` | map of string to HintClassification | Keyed by variant tactic name |
| `explanation` | string | Why the variants diverged on this hint (e.g., "auto rejects evars; eauto allows them") |

## Integration with Existing Components

### Proof Session Manager

The Auto Trace Analyzer borrows the session backend to execute debug commands and tactics. Integration follows the same contract as Typeclass Debugging:

1. **Session required**: All operations require an active proof session positioned at a goal. The MCP server passes the `session_id`; the analyzer resolves it through the session registry.
2. **State preservation**: The analyzer restores the proof state to its pre-diagnosis position. `try` wrappers prevent tactic errors from blocking cleanup. `step_backward` reverses successful tactic applications. Debug flags are unset in a cleanup path.
3. **Concurrency**: The analyzer serializes access to the session backend. It does not issue concurrent commands to the same session.

### Tactic Documentation Handler

The analyzer reuses the Hint Database Inspector from the [Tactic Documentation component](tactic-documentation.md) to retrieve and parse `Print HintDb` output. This means:

- `HintDatabase` and `HintEntry` types are shared — the analyzer consumes them, not duplicates them.
- Database retrieval inherits the same parsing, truncation, and error handling logic.
- When the Hint Database Inspector is improved (e.g., to extract transparency settings), the Auto Trace Analyzer benefits automatically.

### Vernacular Introspection

Debug flag management (`Set Debug "auto"`, `Unset Debug "auto"`) is issued through `coq_query`. This reuses session routing and error handling. The `coq_query` command set does not currently include `Set`/`Unset` — these are state-modifying vernacular commands that extend beyond the read-only introspection scope. The Auto Trace Analyzer issues these commands directly through the session's backend rather than through `coq_query`, following the same pattern as Typeclass Debugging's `Set Typeclasses Debug` usage.

## Error Handling

| Condition | Error Code | Message |
|-----------|------------|---------|
| No active session | `SESSION_NOT_FOUND` | Auto diagnosis requires an active proof session. |
| Session has no open goal | `NO_GOAL` | No open goal to diagnose. Complete `Proof.` before diagnosing. |
| Tactic string is empty | `INVALID_ARGUMENT` | Tactic must not be empty. |
| Tactic is not in the auto family | `INVALID_ARGUMENT` | `{tactic}` is not an auto-family tactic. Supported: `auto`, `eauto`, `auto with <db>`, `eauto with <db>`, `auto <N>`, `eauto <N>`, `typeclasses eauto`. |
| Hint name not found in any database | `NOT_FOUND` | Hint `{name}` not found in any consulted database. |
| Debug output parsing failed | `PARSE_ERROR` | Failed to parse auto debug output. Raw output included in response. |
| Backend crash during diagnosis | `BACKEND_CRASHED` | The Coq backend has crashed. Close the session and open a new one. |
| Debug output capture timed out | `TIMEOUT` | Auto diagnosis timed out after {N} seconds. The hint search may be non-terminating; try a lower depth. |

When debug output parsing fails, the analyzer returns the raw messages alongside the error so that the LLM can still attempt interpretation. This is a degraded mode, not a complete failure.

When the backend crashes during diagnosis (e.g., `auto` triggers a Coq bug), the analyzer cannot restore the session state. The error message directs the user to close and reopen the session.

## Design Rationale

### Why `Set Debug "auto"` + real tactic rather than `debug auto`

`debug auto` wraps `Hint Extern` entries with `once`, preventing backtracking (Coq issue #4064). This means `debug auto` can fail on goals that `auto` solves, and vice versa. Using `Set Debug "auto"` with the actual `auto` tactic (where supported) produces trace output while preserving the real search semantics. The fallback to `debug auto` exists for Coq versions that do not emit trace messages via the flag, with an explicit caveat in the output.

### Why `try` wrapping rather than separate success/failure paths

The `try` wrapper simplifies state management. Without it, a failing tactic raises a Coq error that may prevent subsequent commands (including `Unset Debug "auto"`) from executing in the same backend interaction. With `try`, the tactic always "succeeds" from Coq's perspective: if the inner tactic fails, the goal is unchanged and subsequent cleanup commands execute normally. The outcome is distinguished by checking whether the goal changed, not by catching exceptions.

### Why reuse the Tactic Documentation Handler's HintDatabase rather than re-parsing

`Print HintDb` output is complex and version-sensitive. The Tactic Documentation Handler already has a tested parser that produces structured `HintDatabase` records. Duplicating this parsing would create a maintenance burden and risk inconsistency. The Auto Trace Analyzer consumes `HintDatabase` as a dependency, not a copy.

### Why debug flag commands bypass coq_query

`coq_query` is designed for read-only introspection commands. `Set Debug "auto"` and `Unset Debug "auto"` modify Coq's global state (they toggle a debug flag). Routing them through `coq_query` would either require extending `coq_query`'s command set to include state-modifying commands (which contradicts its design) or treating them as a special case (which adds complexity for a single consumer). Issuing them directly through the session backend, following the Typeclass Debugging precedent, keeps the boundary clean.

### Why classify exhaustively rather than heuristically

Each of the nine rejection reasons maps to a specific, actionable fix. An unclassified rejection produces "auto failed for unknown reasons" — which is no better than Coq's own silence. By enumerating the known failure modes and checking for each one, the diagnoser guarantees that every hint in scope receives either a classification or an explicit "unclassified" marker. The fallback to unclassified is expected to be rare because the nine reasons cover the known behavior of Coq's hint search engine. When it does occur, the raw trace and hint database are still available for the LLM to attempt manual interpretation.

### Why the Variant Comparator runs all three tactics independently

The three auto-family tactics have different databases, different unification strategies, and different backtracking semantics. Predicting `eauto`'s behavior from `auto`'s trace is unreliable — the search trees may differ structurally, not just at individual hint nodes. Running each variant independently and comparing the results produces accurate divergence data at the cost of three tactic executions. The cost is acceptable because the diagnosis is an interactive tool (the user is waiting for one answer), not a batch operation.
