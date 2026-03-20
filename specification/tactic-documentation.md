# Tactic Documentation

Structured tactic information through Coq introspection parsing, tactic comparison, contextual suggestion against live proof state, and hint database inspection.

**Architecture**: [tactic-documentation.md](../doc/architecture/tactic-documentation.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [proof-types.md](../doc/architecture/data-models/proof-types.md)

---

## 1. Purpose

Define the Tactic Documentation component that retrieves, parses, and structures Coq tactic information — looking up Ltac definitions via `Print Ltac`, inspecting unfolding strategies via `Print Strategy`, comparing related tactics, ranking contextual suggestions against a live proof state, and inspecting hint databases via `Print HintDb`. The component returns structured records to the LLM rather than raw Coq output.

## 2. Scope

**In scope**: Tactic lookup (Ltac parsing, strategy inspection), tactic comparison (shared capabilities, pairwise differences, selection guidance), contextual suggestion (goal classification, hypothesis inspection, hint retrieval, ranking), hint database inspection (entry parsing, grouping, summarization).

**Out of scope**: MCP protocol handling (owned by mcp-server), session lifecycle management (owned by proof-session), Coq backend communication (owned by vernacular-introspection via `coq_query`), proof search execution (owned by proof-search-engine), proof state serialization (owned by proof-serialization).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Tactic lookup | Retrieval of a tactic's definition and metadata by name via `Print Ltac` |
| Strategy entry | A constant's unfolding level as reported by `Print Strategy` |
| Tactic comparison | Structured analysis of similarities and differences between two or more tactics |
| Contextual suggestion | A ranked list of tactic candidates derived from the current proof state |
| Hint database | A named collection of hint entries used by `auto`, `eauto`, and related automation tactics |
| Goal classification | Structural analysis of a goal's head constructor to determine applicable tactic categories |
| Vernacular Query Handler | The shared `coq_query` infrastructure that dispatches introspection commands to Coq |

## 4. Behavioral Requirements

### 4.1 Tactic Lookup

#### tactic_lookup(name, session_id?)

- REQUIRES: `name` is a non-empty string. When `session_id` is provided, it references an active proof session in the Proof Session Manager.
- ENSURES: When `name` matches a known multi-word primitive (e.g. `"typeclasses eauto"`), returns TacticInfo with `kind = "primitive"` without issuing a Coq query. When `name` contains whitespace and is not a known multi-word primitive, returns an `INVALID_ARGUMENT` error without issuing a Coq query. Otherwise, issues `coq_query("Print", "Ltac <name>", session_id)`. When `coq_query` succeeds, parses the raw output into a TacticInfo record. When `coq_query` raises a `QueryError` whose message contains `"not an Ltac definition"` or `"not a user defined tactic"`, the lookup intercepts the error and returns TacticInfo with `kind = "primitive"` and `body = null`. When `coq_query` raises any other `QueryError`, the lookup re-raises. When the tactic is found as an Ltac definition, returns TacticInfo with `kind = "ltac"`, `qualified_name`, `body`, and extracted references. When the name is not found, returns a `NOT_FOUND` error.
- MAINTAINS: The underlying proof session state is not modified by the lookup.

> **Given** a tactic name `"my_tactic"` defined as `Ltac my_tactic := auto; try reflexivity`
> **When** `tactic_lookup("my_tactic", session_id)` is called
> **Then** a TacticInfo is returned with `kind = "ltac"`, `body = "auto; try reflexivity"`, `referenced_tactics = ["auto", "reflexivity"]`, and `is_recursive = false`

> **Given** the name `"intro"` which is a primitive tactic
> **When** `tactic_lookup("intro")` is called and Coq returns `"Error: intro is not an Ltac definition"`
> **Then** the lookup intercepts the QueryError and returns a TacticInfo with `kind = "primitive"`, `body = null`, `qualified_name = null`, and `category = "introduction"`

> **Given** the name `"apply"` which is a primitive tactic
> **When** `tactic_lookup("apply")` is called and Coq returns `"Error: apply is not a user defined tactic"`
> **Then** the lookup intercepts the QueryError and returns a TacticInfo with `kind = "primitive"`, `body = null`, and `category = "rewriting"`

> **Given** the name `"nonexistent_tactic"` which does not exist in the current environment
> **When** `tactic_lookup("nonexistent_tactic")` is called
> **Then** a `NOT_FOUND` error is returned with message `Tactic "nonexistent_tactic" not found in the current environment.`

> **Given** the known multi-word primitive `"typeclasses eauto"`
> **When** `tactic_lookup("typeclasses eauto")` is called
> **Then** a TacticInfo is returned with `kind = "primitive"`, `body = null`, and `category = "automation"` without issuing a Coq query

> **Given** an unknown multi-word input `"dependent destruction"`
> **When** `tactic_lookup("dependent destruction")` is called
> **Then** an `INVALID_ARGUMENT` error is returned with message `Tactic name must be a single identifier (no whitespace). Got: "dependent destruction".`

#### Ltac Output Parsing

The Ltac Parser shall process the `output` field of QueryResult returned by `coq_query("Print", "Ltac <name>")`:

| Output shape | Condition | Parser behavior |
|-------------|-----------|-----------------|
| `Ltac <qualified_name> := <body>` | Ltac definition found | Extract `qualified_name`, `body`, compute `is_recursive`, extract `referenced_tactics` and `referenced_constants` |
| Error: not an Ltac definition | Name exists but is primitive or Ltac2 | Return TacticInfo with `kind = "primitive"` or `kind = "ltac2"`, `body = null` |
| Error: name not found | Name does not exist | Return `NOT_FOUND` error |

The parser shall determine `is_recursive` by checking whether the body text contains a reference to the tactic's own name. The parser shall extract `referenced_tactics` as identifiers in tactic position within the body. The parser shall extract `referenced_constants` as non-tactic identifiers appearing as arguments to `unfold`, `rewrite`, `apply`, and similar commands.

### 4.2 Strategy Inspection

#### strategy_inspect(constant_name, session_id?)

- REQUIRES: `constant_name` is a non-empty string. When `session_id` is provided, it references an active proof session.
- ENSURES: Issues `coq_query("Print", "Strategy <constant_name>", session_id)`. Parses the output into a list of StrategyEntry records. When the constant is not found, returns a `NOT_FOUND` error.
- MAINTAINS: The underlying proof session state is not modified.

> **Given** a constant `Nat.add` with strategy level `transparent`
> **When** `strategy_inspect("Nat.add")` is called
> **Then** a list containing one StrategyEntry with `constant = "Nat.add"` and `level = "transparent"` is returned

> **Given** a constant name that does not exist in the environment
> **When** `strategy_inspect("no_such_constant")` is called
> **Then** a `NOT_FOUND` error is returned

#### Strategy Output Parsing

The Strategy Parser shall process lines of the form `<constant_name> : <level>` where `<level>` is one of:

| Level value | Meaning |
|-------------|---------|
| `transparent` | Always unfolded by `simpl`, `cbn`, and related reduction tactics |
| `opaque` | Never unfolded |
| Numeric integer | Unfolded only when reduction depth reaches that level |

When invoked without an argument (global strategy dump), the parser shall apply the same truncation rules as `Search` results in the Vernacular Query Handler.

### 4.3 Tactic Comparison

#### tactic_compare(names, session_id?)

- REQUIRES: `names` is a list of two or more non-empty strings. When `session_id` is provided, it references an active proof session.
- ENSURES: Calls `tactic_lookup` for each name. When at least two names resolve to valid TacticInfo records, produces a TacticComparison containing per-tactic summaries, pairwise differences, shared capabilities, and selection guidance. When fewer than two names resolve, returns an `INVALID_ARGUMENT` error. When some names resolve and others do not (and at least two resolve), the comparison proceeds with the resolved names and includes a note listing unresolved names.
- MAINTAINS: The underlying proof session state is not modified.

> **Given** tactic names `["auto", "eauto"]`
> **When** `tactic_compare(["auto", "eauto"])` is called
> **Then** a TacticComparison is returned with two entries in `tactics`, `shared_capabilities` listing common automation behavior, and `selection_guidance` indicating when to prefer each

> **Given** tactic names `["auto", "nonexistent"]`
> **When** `tactic_compare(["auto", "nonexistent"])` is called
> **Then** an `INVALID_ARGUMENT` error is returned with message `Comparison requires at least two valid tactics. Only "auto" was found.`

> **Given** tactic names `["auto", "eauto", "nonexistent"]`
> **When** `tactic_compare(["auto", "eauto", "nonexistent"])` is called
> **Then** a TacticComparison is returned for `["auto", "eauto"]` with a note that `"nonexistent"` was not found

#### Comparison Analysis

When definitions are available (Ltac tactics), the Comparator shall identify relationships by:

| Relationship type | Detection method |
|-------------------|-----------------|
| Shared referenced tactics | Both bodies call the same tactic name |
| Superset behavior | One body wraps the other (e.g., `Ltac eauto := ... auto ...`) |
| Shared referenced constants | Same constant names appear in both bodies |

For primitive tactics where no body is available, the Comparator shall use `kind` and `category` fields from TacticInfo to produce the comparison.

### 4.4 Contextual Suggestion

#### tactic_suggest(session_id, limit?)

- REQUIRES: `session_id` references an active proof session with at least one open goal. `limit` is a positive integer, default 10.
- ENSURES: Retrieves the current proof state via `observe_proof_state(session_id)`. Classifies the focused goal. Inspects hypotheses. Retrieves relevant hint database contents and unfolding strategies. Returns a ranked list of at most `limit` TacticSuggestion records ordered by rank (1 = highest).
- MAINTAINS: The underlying proof session state is not modified. No tactics are executed or verified.

> **Given** a proof session with focused goal `A /\ B` and hypotheses `HA : A` and `HB : B`
> **When** `tactic_suggest(session_id)` is called
> **Then** a ranked list is returned where `split` ranks high (goal pattern match), and `exact HA` / `exact HB` do not appear (they apply to subgoals after splitting, not the current goal)

> **Given** a proof session with focused goal `x = x`
> **When** `tactic_suggest(session_id)` is called
> **Then** `reflexivity` ranks at position 1 with `confidence = "high"`

> **Given** no active proof session
> **When** `tactic_suggest(session_id)` is called with an invalid session_id
> **Then** a `SESSION_NOT_FOUND` error is returned

#### Goal Classification

The Suggester shall classify the focused goal by structural analysis of the goal type's head constructor:

| Goal pattern | Suggested category | Representative tactics |
|--------------|--------------------|----------------------|
| Conjunction (`A /\ B`) | splitting | `split`, `constructor` |
| Disjunction (`A \/ B`) | case analysis / introduction | `left`, `right`, `destruct` |
| Existential (`exists x, P x`) | witness | `exists`, `eexists` |
| Propositional formula | decision procedures | `intuition`, `tauto`, `firstorder` |
| Arithmetic expression | arithmetic solvers | `lia`, `ring`, `field` |
| Equality (`x = y`) | rewriting / reflexivity | `reflexivity`, `congruence`, `rewrite` |
| Universal quantification (`forall x, P x`) | introduction | `intro`, `intros` |
| Application of defined constant | unfolding | `unfold`, `simpl`, `cbn` |
| Hypothesis matches goal | direct proof | `assumption`, `exact` |

Classification is structural: the classifier inspects the head constructor or top-level shape of the goal type. The classifier shall not evaluate or reduce the goal.

#### Hypothesis Inspection

The Suggester shall scan local hypotheses for shapes that enable specific tactics:

| Hypothesis shape | Enabled tactic |
|-----------------|----------------|
| `H : A /\ B` | `destruct H` |
| `H : A \/ B` | `destruct H` |
| `H : exists x, P x` | `destruct H` |
| `H : x = y` | `rewrite H` |
| `H : <goal_type>` | `exact H`, `assumption` |

#### Ranking

The Suggester shall rank candidates by the following factors, in decreasing priority:

| Factor | Effect |
|--------|--------|
| Goal pattern match strength | Direct structural match ranks above heuristic match |
| Hypothesis availability | Tactics consuming available hypotheses rank higher |
| Hint database presence | Tactics backed by relevant hints rank higher |
| Generality penalty | Broad tactics (`auto`) rank below specific tactics (`reflexivity`) when a specific match exists |

When no strong candidates are identified, the Suggester shall return a short list of general strategies (unfold definitions, case analysis, induction) with a rationale explaining that no specific tactic was identified. Each returned suggestion shall have `confidence = "low"`.

### 4.5 Hint Database Inspection

#### hint_inspect(db_name, session_id?)

- REQUIRES: `db_name` is a non-empty string. When `session_id` is provided, it references an active proof session.
- ENSURES: Issues `coq_query("Print", "HintDb <db_name>", session_id)`. Parses the output into a HintDatabase record containing a summary (counts per entry type), parsed entries, and truncation metadata. When the database is not found, returns a `NOT_FOUND` error.
- MAINTAINS: The underlying proof session state is not modified.

> **Given** a hint database `"core"` containing 5 Resolve hints and 2 Extern hints
> **When** `hint_inspect("core")` is called
> **Then** a HintDatabase is returned with `summary.resolve_count = 5`, `summary.extern_count = 2`, and 7 entries in `entries`

> **Given** a hint database name `"nonexistent_db"` that does not exist
> **When** `hint_inspect("nonexistent_db")` is called
> **Then** a `NOT_FOUND` error is returned with message `Hint database "nonexistent_db" not found.`

> **Given** a hint database with 500 entries and the truncation limit is 200
> **When** `hint_inspect("large_db")` is called
> **Then** a HintDatabase is returned with `truncated = true`, `total_entries = 500`, and `entries` containing the first 200 entries

#### Hint Entry Parsing

The Hint Parser shall extract entries from `Print HintDb` output into HintEntry records:

| Hint type | Output pattern | Extracted fields |
|-----------|---------------|-----------------|
| Resolve | `Resolve <lemma_name> : <type> (cost <n>)` | `hint_type = "resolve"`, `name = <lemma_name>`, `cost = <n>` |
| Unfold | `Unfold <constant_name> (cost <n>)` | `hint_type = "unfold"`, `name = <constant_name>`, `cost = <n>` |
| Constructors | `Constructors <inductive_name> (cost <n>)` | `hint_type = "constructors"`, `name = <inductive_name>`, `cost = <n>` |
| Extern | `Extern <n> (<pattern>) => <tactic>` | `hint_type = "extern"`, `pattern = <pattern>`, `tactic = <tactic>`, `cost = <n>` |

The parser shall group entries by type and prepend a HintSummary with counts per type. For databases exceeding the truncation limit, the parser shall include the total entry count in the truncation message.

## 5. Data Model

### TacticInfo

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; the tactic name as provided by the caller |
| `qualified_name` | string or null | Fully qualified name from Coq; null for primitive tactics |
| `kind` | `"ltac"` or `"ltac2"` or `"primitive"` | Required; how the tactic is defined |
| `category` | string or null | Functional category; one of `"automation"`, `"rewriting"`, `"case_analysis"`, `"introduction"`, `"arithmetic"`, or null when unclassified |
| `body` | string or null | Ltac definition body; null for primitive and Ltac2 tactics |
| `is_recursive` | boolean | Required; true when the body references its own name; false when `body` is null |
| `referenced_tactics` | list of string | Required; tactic names called in the body; empty when `body` is null |
| `referenced_constants` | list of string | Required; non-tactic identifiers in the body; empty when `body` is null |
| `strategy_entries` | list of StrategyEntry | Required; unfolding strategies for referenced constants; may be empty |

### StrategyEntry

| Field | Type | Constraints |
|-------|------|-------------|
| `constant` | string | Required; fully qualified constant name |
| `level` | `"transparent"` or `"opaque"` or integer | Required; unfolding level |

### TacticComparison

| Field | Type | Constraints |
|-------|------|-------------|
| `tactics` | list of TacticInfo | Required; length >= 2; the tactics being compared |
| `shared_capabilities` | list of string | Required; capabilities common to all compared tactics |
| `pairwise_differences` | list of PairwiseDiff | Required; one entry per unique pair of tactics |
| `selection_guidance` | list of SelectionHint | Required; one entry per tactic in `tactics` |
| `not_found` | list of string | Required; names that were requested but not found; empty when all resolved |

### PairwiseDiff

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic_a` | string | Required; first tactic name |
| `tactic_b` | string | Required; second tactic name |
| `differences` | list of string | Required; structured descriptions of behavioral differences |

### SelectionHint

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic` | string | Required; tactic name |
| `prefer_when` | list of string | Required; conditions under which this tactic is preferred |

### TacticSuggestion

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic` | string | Required; suggested tactic text |
| `rank` | positive integer | Required; position in the ranked list (1 = highest) |
| `rationale` | string | Required; explanation of why this tactic may apply |
| `confidence` | `"high"` or `"medium"` or `"low"` | Required; match strength against goal structure |
| `category` | string | Required; functional category (same vocabulary as `TacticInfo.category`) |

### HintDatabase

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | Required; database name as provided by the caller |
| `summary` | HintSummary | Required; counts of entries by type |
| `entries` | list of HintEntry | Required; parsed hint entries |
| `truncated` | boolean | Required; true when the entry list was truncated |
| `total_entries` | non-negative integer | Required; total entry count before truncation |

### HintSummary

| Field | Type | Constraints |
|-------|------|-------------|
| `resolve_count` | non-negative integer | Required; number of Resolve hints |
| `unfold_count` | non-negative integer | Required; number of Unfold hints |
| `constructors_count` | non-negative integer | Required; number of Constructors hints |
| `extern_count` | non-negative integer | Required; number of Extern hints |

### HintEntry

| Field | Type | Constraints |
|-------|------|-------------|
| `hint_type` | `"resolve"` or `"unfold"` or `"constructors"` or `"extern"` | Required; entry type |
| `name` | string or null | Lemma, constant, or inductive name; null for extern hints |
| `pattern` | string or null | Match pattern; non-null only for extern hints |
| `tactic` | string or null | Tactic body; non-null only for extern hints |
| `cost` | non-negative integer | Required; priority cost (lower = tried earlier by `auto`/`eauto`) |

## 6. Interface Contracts

### Tactic Documentation Handler -> Vernacular Query Handler

| Property | Value |
|----------|-------|
| Operations used | `coq_query(command, argument, session_id?)` |
| Commands issued | `("Print", "Ltac <name>")`, `("Print", "Strategy <name>")`, `("Print", "HintDb <name>")` |
| Session routing | When `session_id` is provided, the query executes in session context (project-local definitions and imports visible). When absent, the query falls back to a standalone Coq process with global environment only. |
| Error strategy | `NOT_FOUND` from Coq output -> mapped to component-level `NOT_FOUND`. `BACKEND_CRASHED` -> propagated as `BACKEND_CRASHED`. `TIMEOUT` -> propagated as `TIMEOUT`. |
| Concurrency | Serialized per session; concurrent queries to different sessions are independent |
| Idempotency | All queries are read-only and idempotent |

### Tactic Documentation Handler -> Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `observe_proof_state(session_id)` |
| Usage context | Contextual suggestion only (`tactic_suggest`) |
| Error strategy | `SESSION_NOT_FOUND` -> propagated. `SESSION_EXPIRED` -> propagated as `SESSION_NOT_FOUND`. |
| Concurrency | Read-only observation; does not conflict with other session operations |

### MCP Server -> Tactic Documentation Handler

| Property | Value |
|----------|-------|
| Tools exposed | `tactic_lookup`, `tactic_compare`, `tactic_suggest`, `hint_inspect` |
| Input validation | MCP Server validates parameter presence and types. Handler validates semantic constraints (non-empty names, minimum two names for comparison). |
| Response format | All responses are structured records (TacticInfo, TacticComparison, TacticSuggestion list, HintDatabase). MCP Server serializes to JSON. |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Empty tactic name | `INVALID_ARGUMENT` | `Tactic name must not be empty.` |
| Tactic name contains whitespace and is not a known multi-word primitive | `INVALID_ARGUMENT` | `Tactic name must be a single identifier (no whitespace). Got: "<name>".` |
| Empty database name | `INVALID_ARGUMENT` | `Hint database name must not be empty.` |
| Empty constant name | `INVALID_ARGUMENT` | `Constant name must not be empty.` |
| Fewer than two names for comparison | `INVALID_ARGUMENT` | `Comparison requires at least two tactic names.` |
| Zero valid tactics after lookup (comparison) | `INVALID_ARGUMENT` | `Comparison requires at least two valid tactics. None of the provided names were found.` |
| One valid tactic after lookup (comparison) | `INVALID_ARGUMENT` | `Comparison requires at least two valid tactics. Only "<name>" was found.` |
| `limit` <= 0 for suggestion | Clamp to 1 | No error returned |

### 7.2 State Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `session_id` references non-existent session | `SESSION_NOT_FOUND` | `Proof session "<session_id>" not found or has expired.` |
| No active proof session for `tactic_suggest` without `session_id` | `SESSION_REQUIRED` | `Tactic suggestion requires an active proof session. Provide a session_id.` |
| Proof is complete (no open goals) for `tactic_suggest` | `SESSION_REQUIRED` | `Tactic suggestion requires at least one open goal. The proof is complete.` |

### 7.3 Dependency Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Tactic name not found in environment | `NOT_FOUND` | `Tactic "<name>" not found in the current environment.` |
| Hint database not found | `NOT_FOUND` | `Hint database "<name>" not found.` |
| Constant not found (strategy) | `NOT_FOUND` | `Constant "<name>" not found in the current environment.` |
| Coq backend crashes during query | `BACKEND_CRASHED` | `The Coq backend has crashed.` |
| Coq query exceeds time limit | `TIMEOUT` | `Query exceeded time limit.` |

### 7.4 Edge Cases

| Condition | Behavior |
|-----------|----------|
| Tactic is not Ltac but exists (primitive/Ltac2) | Normal response: TacticInfo with `kind = "primitive"` or `"ltac2"`, `body = null`. The lookup intercepts the `QueryError` raised by `coq_query` when Coq's error message contains `"not an Ltac definition"` or `"not a user defined tactic"`. |
| Comparison with mix of found and not-found names (>= 2 found) | Normal response: comparison of found tactics with `not_found` field listing missing names |
| Hint database with zero entries | Normal response: HintDatabase with empty `entries`, all summary counts = 0, `truncated = false` |
| Recursive Ltac tactic | Normal response: TacticInfo with `is_recursive = true` |
| Session-free lookup | Query executes against standalone Coq process with global environment only; project-local definitions are not visible |

## 8. Non-Functional Requirements

- Tactic lookup shall return a TacticInfo record within 2 seconds (excluding Coq query latency).
- Strategy inspection shall return within 2 seconds (excluding Coq query latency).
- Hint database parsing shall process up to 1,000 entries within 500 milliseconds (excluding Coq query latency).
- Tactic comparison shall complete within 5 seconds for up to 5 tactics (excluding Coq query latency).
- Contextual suggestion shall complete goal classification and ranking within 1 second (excluding Coq query and proof state retrieval latency).
- The component shall not cache parsed results across tool invocations; each invocation queries Coq to reflect the current environment state.

## 9. Examples

### Tactic Lookup -- Ltac definition

```
tactic_lookup("my_solver", session_id="abc123")

Coq output: "Ltac my_solver := intros; auto with arith; try lia"

Result:
{
  "name": "my_solver",
  "qualified_name": "Top.my_solver",
  "kind": "ltac",
  "category": "automation",
  "body": "intros; auto with arith; try lia",
  "is_recursive": false,
  "referenced_tactics": ["intros", "auto", "lia"],
  "referenced_constants": [],
  "strategy_entries": []
}
```

### Tactic Lookup -- primitive tactic

```
tactic_lookup("intro")

Coq output: error indicating not an Ltac definition

Result:
{
  "name": "intro",
  "qualified_name": null,
  "kind": "primitive",
  "category": "introduction",
  "body": null,
  "is_recursive": false,
  "referenced_tactics": [],
  "referenced_constants": [],
  "strategy_entries": []
}
```

### Tactic Comparison

```
tactic_compare(["auto", "eauto"], session_id="abc123")

Result:
{
  "tactics": [
    {"name": "auto", "kind": "primitive", "category": "automation", ...},
    {"name": "eauto", "kind": "primitive", "category": "automation", ...}
  ],
  "shared_capabilities": ["proof search using hint databases", "backtracking"],
  "pairwise_differences": [
    {
      "tactic_a": "auto",
      "tactic_b": "eauto",
      "differences": [
        "eauto supports existential variable instantiation; auto does not",
        "eauto may use Resolve hints with existential parameters; auto requires fully instantiated hints"
      ]
    }
  ],
  "selection_guidance": [
    {"tactic": "auto", "prefer_when": ["all hint arguments are fully determined", "lower search cost is desired"]},
    {"tactic": "eauto", "prefer_when": ["the goal requires existential variable instantiation", "Resolve hints have uninstantiated parameters"]}
  ],
  "not_found": []
}
```

### Contextual Suggestion

```
tactic_suggest(session_id="def456")

Proof state: ⊢ forall n : nat, n + 0 = n
Hypotheses: (none)

Result:
[
  {"tactic": "intro n", "rank": 1, "rationale": "Goal is a universal quantification; introduce the bound variable", "confidence": "high", "category": "introduction"},
  {"tactic": "intros", "rank": 2, "rationale": "Introduces all universally quantified variables", "confidence": "high", "category": "introduction"},
  {"tactic": "induction n", "rank": 3, "rationale": "Goal quantifies over nat; induction is a common proof strategy", "confidence": "medium", "category": "case_analysis"}
]
```

### Hint Database Inspection

```
hint_inspect("core", session_id="abc123")

Result:
{
  "name": "core",
  "summary": {
    "resolve_count": 12,
    "unfold_count": 3,
    "constructors_count": 2,
    "extern_count": 1
  },
  "entries": [
    {"hint_type": "resolve", "name": "eq_refl", "pattern": null, "tactic": null, "cost": 0},
    {"hint_type": "unfold", "name": "not", "pattern": null, "tactic": null, "cost": 1},
    {"hint_type": "constructors", "name": "bool", "pattern": null, "tactic": null, "cost": 0},
    {"hint_type": "extern", "name": null, "pattern": "(_ = _)", "tactic": "congruence", "cost": 5}
  ],
  "truncated": false,
  "total_entries": 18
}
```

## 10. Language-Specific Notes (Python)

- Use `asyncio` for all operations that delegate to `coq_query` or `observe_proof_state`, as these are async calls through the session manager.
- Package location: `src/poule/tactics/`.
- Entry points: `async def tactic_lookup(name, session_id=None) -> TacticInfo`, `async def strategy_inspect(constant_name, session_id=None) -> list[StrategyEntry]`, `async def tactic_compare(names, session_id=None) -> TacticComparison`, `async def tactic_suggest(session_id, limit=10) -> list[TacticSuggestion]`, `async def hint_inspect(db_name, session_id=None) -> HintDatabase`.
- Use `dataclasses` or Pydantic models for all data structures (TacticInfo, StrategyEntry, TacticComparison, TacticSuggestion, HintDatabase, HintEntry).
- Ltac body parsing: use regular expressions for the `Ltac <name> := <body>` pattern. Tactic reference extraction does not require a full parser; pattern matching on known tactic names in tactic position is sufficient.
- Strategy level parsing: match `transparent`, `opaque`, or integer via regex on each output line.
- Hint entry parsing: match each of the four hint output patterns (Resolve, Unfold, Constructors, Extern) via regex, one entry per line or block.
- Goal classification: implement as a chain of pattern matchers over the goal type string, checking head constructors (`and`, `or`, `ex`, `eq`, `forall`) in order of specificity.
