# Tactic Documentation

The component that provides structured tactic information by parsing Coq introspection output, comparing related tactics, and ranking contextual suggestions against the current proof state. Claude Code invokes these capabilities as MCP tools; the LLM interprets the structured results rather than raw Coq output.

**Feature**: [Tactic Documentation](../features/tactic-documentation.md)
**Stories**: [Epics 1--4](../requirements/stories/tactic-documentation.md)

---

## Component Diagram

```
MCP Server
  |
  | tactic_lookup / tactic_compare / tactic_suggest / hint_inspect
  v
+----------------------------------------------------------------+
|              Tactic Documentation Handler                       |
|                                                                |
|  +----------------------------------------------------------+  |
|  | Tactic Lookup                                            |  |
|  |   tactic name --> coq_query("Print", "Ltac <name>")     |  |
|  |   raw output  --> Ltac Parser --> TacticInfo             |  |
|  +----------------------------------------------------------+  |
|                                                                |
|  +----------------------------------------------------------+  |
|  | Strategy Inspector                                       |  |
|  |   constant name --> coq_query("Print", "Strategy <name>")|  |
|  |   raw output    --> Strategy Parser --> StrategyEntry[]   |  |
|  +----------------------------------------------------------+  |
|                                                                |
|  +----------------------------------------------------------+  |
|  | Tactic Comparator                                        |  |
|  |   tactic names --> Tactic Lookup (per name)              |  |
|  |   TacticInfo[] --> diff logic --> TacticComparison       |  |
|  +----------------------------------------------------------+  |
|                                                                |
|  +----------------------------------------------------------+  |
|  | Contextual Suggester                                     |  |
|  |   session_id --> Proof Session Manager --> ProofState     |  |
|  |   ProofState --> goal classifier + hint retrieval        |  |
|  |             --> ranked TacticSuggestion[]                |  |
|  +----------------------------------------------------------+  |
|                                                                |
|  +----------------------------------------------------------+  |
|  | Hint Database Inspector                                  |  |
|  |   db name --> coq_query("Print", "HintDb <name>")       |  |
|  |   raw output --> Hint Parser --> HintDatabase            |  |
|  +----------------------------------------------------------+  |
+----------------------------------------------------------------+
  |                         |
  | coq_query(...)          | observe_proof_state(session_id)
  v                         v
Vernacular Introspection    Proof Session Manager
(coq_query infrastructure)    |
                              v
                           Coq Backend Process
```

## Integration with Vernacular Introspection

All Coq introspection commands are issued through the shared `coq_query` infrastructure defined in [vernacular-introspection.md](vernacular-introspection.md). The Tactic Documentation Handler does not communicate with Coq backend processes directly. It constructs the appropriate `(command, argument)` pair and delegates execution to the Vernacular Query Handler.

When a `session_id` is available (the common case during proof development), queries execute in the session's context, so `Print Ltac` and `Print HintDb` reflect project-local definitions and imports. When no session is active, queries fall back to the standalone Coq process with the global environment only.

This reuse means the Tactic Documentation Handler inherits session-aware vs session-free execution, output parsing, warning extraction, and error classification without reimplementing them.

## Tactic Lookup

Given a tactic name, the lookup retrieves the tactic's definition and produces a `TacticInfo` record.

### Input Validation

The lookup validates the tactic name before issuing a Coq query:

- **Empty name**: rejected with `INVALID_ARGUMENT`.
- **Multi-word name** (contains whitespace): rejected with `INVALID_ARGUMENT`. Coq's `Print Ltac` accepts only single identifiers; passing multi-word input produces a malformed vernacular command. Multi-word tactic notations (e.g., `dependent destruction`) and proof techniques (e.g., `convoy pattern`) cannot be introspected via `Print Ltac`.

### Error Interception for Primitive Tactics

The Vernacular Query Handler (`coq_query`) raises a `QueryError` when Coq's output contains `Error:`. For primitive tactics, Coq returns errors like `"Error: apply is not an Ltac definition"` or `"Error: apply is not a user defined tactic"` (wording varies by Coq version). The Query Handler classifies these as `PARSE_ERROR` because they do not match any specific error pattern.

The Tactic Lookup must intercept this `QueryError` and inspect the error message for primitive-detection patterns (`"not an Ltac definition"` or `"not a user defined tactic"`). When either pattern is detected, the lookup returns a `TacticInfo` with `kind = "primitive"` and `body = null` — the same result the Ltac Parser would produce if it received the raw output directly. All other `QueryError` instances are re-raised.

This interception is necessary because `coq_query` treats all `Error:` output as errors and raises before the Ltac Parser runs. Without interception, every primitive tactic lookup fails with a `PARSE_ERROR` — the parser's primitive-handling logic is unreachable.

### Primitive Category Table

The lookup maintains a mapping from known primitive tactic names to their functional categories. This table covers all commonly used Coq built-in tactics across rewriting, case analysis, automation, introduction, arithmetic, control flow, context management, and equality reasoning categories. Tactics not in the table receive `category = null`.

### Ltac Output Parsing

The Ltac Parser processes the `output` field of `QueryResult` returned by `coq_query("Print", "Ltac <name>")`.

Coq's `Print Ltac` output follows one of these shapes:

1. **Ltac definition found**: The output begins with `Ltac <qualified_name> :=` followed by the tactic body, which may span multiple lines and contain nested `match goal`, `try`, `repeat`, and other combinators.
2. **Not an Ltac tactic**: Coq returns an error indicating the name is not an Ltac definition. This covers primitive tactics (`intro`, `apply`, `rewrite`) and Ltac2 tactics. In production, this case is handled by the error interception layer above; the parser handles it as a fallback for cases where `coq_query` does not raise.
3. **Name not found**: Coq returns an error indicating the name does not exist in the current environment.

The parser extracts:

| Field | Source |
|-------|--------|
| `qualified_name` | The fully qualified name from the `Ltac <name> :=` prefix |
| `body` | The tactic body text following `:=`, preserving Coq's formatting |
| `is_recursive` | Whether the body references the tactic's own name |
| `referenced_tactics` | Tactic names appearing in the body (identifiers in tactic position) |
| `referenced_constants` | Non-tactic identifiers appearing in the body (used in `unfold`, `rewrite`, `apply` arguments) |

For primitive and Ltac2 tactics (shape 2), the parser produces a `TacticInfo` with `kind = "primitive"` or `kind = "ltac2"` and `body = null`. The handler signals this clearly to the LLM so it can explain the tactic from general knowledge rather than from a definition.

### Strategy Output Parsing

The Strategy Inspector processes the `output` field of `QueryResult` returned by `coq_query("Print", "Strategy <constant_name>")`.

Coq's `Print Strategy` output lists constants with their unfolding levels:

```
<constant_name> : <level>
```

Where `<level>` is one of:
- `transparent` -- the constant is always unfolded by `simpl`, `cbn`, and related reduction tactics
- `opaque` -- the constant is never unfolded
- A numeric level -- the constant is unfolded only when the reduction depth reaches that level

The parser produces a list of `StrategyEntry` records, one per constant. When invoked for a single constant, the list typically has one entry. When invoked without an argument (global strategy dump), the list may be large; truncation follows the same rules as `Search` truncation in the Vernacular Query Handler.

## Tactic Comparison

Given two or more tactic names, the Comparator retrieves `TacticInfo` for each (via Tactic Lookup), then produces a `TacticComparison` by analyzing the retrieved definitions.

### How Related Tactics Are Identified

When definitions are available (Ltac tactics), the Comparator identifies relationships by:

1. **Shared referenced tactics**: If tactic A and tactic B both call `auto` internally, this is noted as shared infrastructure.
2. **Superset behavior**: If tactic A's body wraps tactic B (e.g., `Ltac eauto := ... auto ...`), the comparison notes that A extends B.
3. **Shared referenced constants**: Constants appearing in both bodies suggest overlapping domains.

For primitive tactics where no body is available, the comparison relies on the `kind` and `category` fields of `TacticInfo` and on the structured metadata (see Data Structures below). The LLM uses the structured comparison as grounding; it adds general knowledge about primitive tactics to fill gaps.

### Comparison Structure

The `TacticComparison` record provides:

- Per-tactic summaries (name, kind, category)
- Pairwise difference annotations (which capabilities differ between each pair)
- Shared capabilities (what all compared tactics have in common)
- Selection guidance (structured hints on when to prefer each tactic)

The comparison does not attempt to rank tactics globally -- ranking depends on the proof context, which is the Contextual Suggester's responsibility.

## Contextual Suggestion

Given an active proof session, the Suggester retrieves the current proof state, analyzes it, and produces a ranked list of `TacticSuggestion` records.

### How Proof State Informs Suggestions

1. **Retrieve proof state**: Call `observe_proof_state(session_id)` via the Proof Session Manager to obtain the current `ProofState` (goals, hypotheses, local context).

2. **Classify the goal**: Analyze the focused goal's type structure to determine applicable tactic categories:

   | Goal pattern | Suggested category |
   |--------------|--------------------|
   | Conjunction (`A /\ B`) | splitting tactics (`split`, `constructor`) |
   | Disjunction (`A \/ B`) | case analysis or introduction (`left`, `right`, `destruct`) |
   | Existential (`exists x, P x`) | witness tactics (`exists`, `eexists`) |
   | Propositional formula | decision procedures (`intuition`, `tauto`, `firstorder`) |
   | Arithmetic expression | arithmetic solvers (`lia`, `ring`, `field`) |
   | Equality (`x = y`) | rewriting, reflexivity, congruence (`reflexivity`, `congruence`, `rewrite`) |
   | Universal quantification (`forall x, P x`) | introduction (`intro`, `intros`) |
   | Application of a defined constant | unfolding (`unfold`, `simpl`, `cbn`) |
   | Hypothesis matches goal | direct proof (`assumption`, `exact`) |

   Classification is structural: it inspects the head constructor or top-level shape of the goal type. It does not evaluate or reduce the goal.

3. **Inspect hypotheses**: Scan local hypotheses for shapes that enable specific tactics (e.g., a hypothesis `H : A /\ B` enables `destruct H`; a hypothesis `H : x = y` enables `rewrite H`).

4. **Retrieve hint database contents** (when available): If the goal involves constants registered in hint databases, call `coq_query("Print", "HintDb <db>")` to retrieve relevant hints. Hints that match the goal structure are promoted in the ranking.

5. **Retrieve unfolding strategies** (when available): For constants appearing in the goal, call the Strategy Inspector to determine whether they are transparent, opaque, or at a specific level. Opaque constants are de-prioritized for `unfold`/`simpl` suggestions.

6. **Rank and filter**: Produce a ranked list of `TacticSuggestion` records. Ranking factors:
   - Goal pattern match strength (direct structural match ranks higher than heuristic)
   - Hypothesis availability (tactics that consume available hypotheses rank higher)
   - Hint database presence (tactics backed by relevant hints rank higher)
   - Generality penalty (broad tactics like `auto` rank below specific tactics like `reflexivity` when a specific match exists)

When no strong candidates are identified, the Suggester returns a short list of general strategies (unfold definitions, case analysis, induction) with a rationale explaining that no specific tactic was identified.

## Hint Database Inspection

Given a hint database name, the Inspector retrieves and parses the database contents.

### How Print HintDb Output Is Parsed

The Hint Parser processes the `output` field of `QueryResult` returned by `coq_query("Print", "HintDb <name>")`.

Coq's `Print HintDb` output lists hint entries grouped by head constant. Each entry has one of the following forms:

| Hint type | Output pattern |
|-----------|---------------|
| `Resolve` | `Resolve <lemma_name> : <type> (cost <n>)` |
| `Unfold` | `Unfold <constant_name> (cost <n>)` |
| `Constructors` | `Constructors <inductive_name> (cost <n>)` |
| `Extern` | `Extern <n> (<pattern>) => <tactic>` |

The parser extracts each entry into an `HintEntry` record and groups entries by type. A summary section is prepended with counts per type, enabling the LLM to give an overview before diving into details.

For databases with many entries, the parser respects the same truncation limit as `Search` results in the Vernacular Query Handler. The truncation message includes the total entry count.

## Data Structures

### TacticInfo

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | The tactic name as provided by the caller |
| `qualified_name` | string or null | Fully qualified name from Coq (null for primitive tactics) |
| `kind` | `"ltac"` or `"ltac2"` or `"primitive"` | How the tactic is defined |
| `category` | string or null | Functional category (e.g., `"automation"`, `"rewriting"`, `"case_analysis"`, `"introduction"`, `"arithmetic"`) |
| `body` | string or null | The Ltac definition body (null for primitive/Ltac2 tactics) |
| `is_recursive` | boolean | Whether the body references its own name |
| `referenced_tactics` | list of string | Tactic names called in the body |
| `referenced_constants` | list of string | Non-tactic identifiers appearing in the body |
| `strategy_entries` | list of StrategyEntry | Unfolding strategies for constants referenced by this tactic (may be empty) |

### StrategyEntry

| Field | Type | Description |
|-------|------|-------------|
| `constant` | string | Fully qualified constant name |
| `level` | `"transparent"` or `"opaque"` or integer | Unfolding level |

### TacticComparison

| Field | Type | Description |
|-------|------|-------------|
| `tactics` | list of TacticInfo | The tactics being compared |
| `shared_capabilities` | list of string | Capabilities common to all compared tactics |
| `pairwise_differences` | list of PairwiseDiff | Per-pair difference annotations |
| `selection_guidance` | list of SelectionHint | When to prefer each tactic |

### PairwiseDiff

| Field | Type | Description |
|-------|------|-------------|
| `tactic_a` | string | First tactic name |
| `tactic_b` | string | Second tactic name |
| `differences` | list of string | Structured descriptions of behavioral differences |

### SelectionHint

| Field | Type | Description |
|-------|------|-------------|
| `tactic` | string | Tactic name |
| `prefer_when` | list of string | Conditions under which this tactic is preferred |

### TacticSuggestion

| Field | Type | Description |
|-------|------|-------------|
| `tactic` | string | Suggested tactic text |
| `rank` | positive integer | Position in the ranked list (1 = highest) |
| `rationale` | string | Brief explanation of why this tactic may apply |
| `confidence` | `"high"` or `"medium"` or `"low"` | How strongly the suggestion matches the goal structure |
| `category` | string | Functional category (same vocabulary as `TacticInfo.category`) |

### HintDatabase

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Database name as provided by the caller |
| `summary` | HintSummary | Counts of entries by type |
| `entries` | list of HintEntry | Parsed hint entries |
| `truncated` | boolean | Whether the entry list was truncated |
| `total_entries` | non-negative integer | Total entry count before truncation |

### HintSummary

| Field | Type | Description |
|-------|------|-------------|
| `resolve_count` | non-negative integer | Number of Resolve hints |
| `unfold_count` | non-negative integer | Number of Unfold hints |
| `constructors_count` | non-negative integer | Number of Constructors hints |
| `extern_count` | non-negative integer | Number of Extern hints |

### HintEntry

| Field | Type | Description |
|-------|------|-------------|
| `hint_type` | `"resolve"` or `"unfold"` or `"constructors"` or `"extern"` | Entry type |
| `name` | string | Lemma, constant, or inductive name (for resolve/unfold/constructors) |
| `pattern` | string or null | Match pattern (for extern hints) |
| `tactic` | string or null | Tactic body (for extern hints) |
| `cost` | non-negative integer | Priority cost (lower = tried earlier by `auto`/`eauto`) |

## Error Handling

All errors use the MCP standard error format (see [mcp-server.md](mcp-server.md) -- Error Contract).

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Tactic name not found in session | `NOT_FOUND` | Tactic `{name}` not found in the current environment. |
| Tactic is not an Ltac definition (Print Ltac fails) | (normal response) | `TacticInfo` with `kind = "primitive"` or `kind = "ltac2"` and `body = null`; not an error. |
| Hint database not found | `NOT_FOUND` | Hint database `{name}` not found. |
| Session not found (when session_id provided) | `SESSION_NOT_FOUND` | Proof session `{session_id}` not found or has expired. |
| No active session for contextual suggestion | `SESSION_REQUIRED` | Tactic suggestion requires an active proof session. Provide a session_id. |
| Backend crash during query | `BACKEND_CRASHED` | The Coq backend has crashed. |
| Comparison with zero valid tactics | `INVALID_ARGUMENT` | Comparison requires at least two valid tactics. None of the provided names were found. |
| Comparison with one valid tactic | `INVALID_ARGUMENT` | Comparison requires at least two valid tactics. Only `{name}` was found. |
| Empty tactic name | `INVALID_ARGUMENT` | Tactic name must not be empty. |
| Strategy query for unknown constant | `NOT_FOUND` | Constant `{name}` not found in the current environment. |
| Coq query timeout | `TIMEOUT` | Query exceeded time limit. |

When a comparison request includes a mix of found and not-found tactics and at least two are found, the comparison proceeds with the found tactics and includes a note listing which names were not found. This is a normal response, not an error.

## Design Rationale

### LLM interprets structured data rather than raw output

Coq's `Print Ltac`, `Print HintDb`, and `Print Strategy` output is designed for expert human readers. An LLM can parse it, but the parsing is unreliable across variations in Coq versions and output formatting. By parsing the output once in the handler and returning structured records (`TacticInfo`, `HintDatabase`, `StrategyEntry`), the system moves parsing complexity out of the LLM's context window and into deterministic code. The LLM receives clean, typed data and focuses on interpretation and explanation -- the task it does well.

### Contextual over reference

Static tactic documentation describes behavior in isolation. The Contextual Suggester grounds suggestions in the user's live proof state -- the goal type, available hypotheses, loaded hint databases, and unfolding strategies. This means the answer to "what tactic should I use?" depends on where the user is in their proof, not on a generic reference page. The handler provides the structured context; the LLM provides the natural-language explanation tailored to the specific situation.

### Separation from proof search

Tactic suggestion and proof search both analyze the proof state to propose tactics. They differ in purpose: suggestion explains and teaches (returning a ranked list with rationales), while proof search automates (running a tight verify loop to find a complete proof script). The Tactic Documentation Handler does not execute tactics or verify that suggestions succeed -- it ranks candidates by structural analysis and returns them to the LLM for presentation. Proof search, by contrast, executes every candidate against Coq. This separation keeps each component focused and avoids coupling the suggestion ranking logic to the search engine's scoring function.

### Shared coq_query infrastructure

Tactic documentation reuses the Vernacular Query Handler rather than opening its own communication channel to Coq. This ensures that session routing, output parsing, warning extraction, error classification, and process lifecycle are handled uniformly. It also means that improvements to the Vernacular Query Handler (e.g., better error classification, output caching) benefit tactic documentation automatically.
