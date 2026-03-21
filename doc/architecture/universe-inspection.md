# Universe Constraint Inspection

The component that retrieves, parses, and diagnoses Coq universe constraints, providing structured access to the universe constraint system through the MCP tool surface. It mediates between the MCP Server and the Coq backend, translating raw vernacular output into queryable data structures and actionable diagnosis.

**Feature**: [Universe Constraint Inspection](../features/universe-inspection.md)

---

## Component Diagram

```
MCP Server
  │
  │ universe tool calls
  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                  Universe Inspection Component                       │
│                                                                      │
│  ┌────────────────────┐  ┌─────────────────────┐                    │
│  │ Command Dispatcher  │  │ Constraint Parser   │                    │
│  │                     │  │                     │                    │
│  │ Selects vernacular  │  │ Raw text →          │                    │
│  │ command(s) for the  │  │  UniverseConstraint │                    │
│  │ requested operation │  │  ConstraintGraph    │                    │
│  └─────────┬───────────┘  └──────────┬──────────┘                    │
│            │                          │                               │
│            │ coq_query                │ structured constraints        │
│            ▼                          │                               │
│  ┌─────────────────────┐             │                               │
│  │ Coq Query Layer     │─────────────┘                               │
│  │ (shared with        │  raw text response                          │
│  │  vernacular         │                                             │
│  │  introspection)     │                                             │
│  └─────────┬───────────┘                                             │
│            │                                                         │
│  ┌─────────────────────┐  ┌──────────────────────────┐              │
│  │ Graph Builder       │  │ Inconsistency Diagnoser  │              │
│  │                     │  │                           │              │
│  │ Constraints →       │  │ Error message →           │              │
│  │  ConstraintGraph    │  │  cycle detection →        │              │
│  │  (adjacency, filter │  │  source attribution →     │              │
│  │   by reachability)  │  │  InconsistencyDiagnosis  │              │
│  └─────────────────────┘  └──────────────────────────┘              │
│                                                                      │
│  ┌──────────────────────────┐                                       │
│  │ Polymorphic Inspector    │                                       │
│  │                          │                                       │
│  │ Retrieves instantiation  │                                       │
│  │ details for universe-    │                                       │
│  │ polymorphic definitions  │                                       │
│  └──────────────────────────┘                                       │
└──────────────────────────────────────────────────────────────────────┘
  │
  │ coq_query (command submission + response)
  ▼
Proof Session Manager → Coq Backend Process
```

## Constraint Retrieval

The component retrieves universe constraints through two mechanisms, selected by the Command Dispatcher based on the operation requested.

### Full Graph Retrieval: Print Universes

For operations requiring the complete constraint graph (story 1.2) or a filtered subgraph (story 4.1):

1. Submit `Print Universes.` to the Coq backend via `coq_query`.
2. Coq returns the full set of universe variables and constraints as text, one constraint per line, in the form `u.N op u.M` where `op` is `<` (strict), `<=` (non-strict), or `=` (equality).
3. The Constraint Parser processes each line into a `UniverseConstraint` record.
4. The Graph Builder assembles constraints into a `ConstraintGraph`.

### Per-Definition Retrieval: Set Printing Universes + Print

For operations targeting a single definition (story 1.1, 1.3):

1. Submit `Set Printing Universes.` to enable universe annotations on output.
2. Submit `Print <qualified_name>.` to retrieve the definition with universe-annotated types.
3. The Constraint Parser extracts universe variables and constraints from the annotated output.
4. Submit `Unset Printing Universes.` to restore default printing.

The `Set`/`Unset` pair is scoped to a single logical operation. The Coq Query Layer ensures these commands are submitted atomically — no interleaving with other commands on the same backend process.

### About Command for Universe Parameters

For universe-polymorphic definitions, `About <qualified_name>.` returns the universe polymorphism declaration, including universe parameter names and their constraints. This is used by the Polymorphic Inspector (Epic 3) and as supplementary data for constraint retrieval.

## Constraint Parsing

Raw Coq output for universe constraints follows predictable formats.

### Print Universes Output Format

Each line of `Print Universes` output is one of:

- `u.N <= u.M` — non-strict constraint
- `u.N < u.M` — strict constraint
- `u.N = u.M` — equality constraint

Universe expressions may include algebraic forms: `u.N+1`, `max(u.N, u.M)`, `Set`, `Prop`. The parser handles these as universe expressions rather than bare variables.

### Set Printing Universes Output Format

When printing a definition with universe annotations enabled, `Type` occurrences are annotated as `Type@{u.N}` and sort occurrences carry their universe level. The parser extracts:

- Each universe variable referenced in the annotated term
- The mapping from universe variable to its position in the type signature
- For universe-polymorphic definitions, the polymorphic universe parameters and their declared constraints (from the `(* Universe polymorphism *)` section of the output)

### Parser Behavior

The parser operates line-by-line. It:

1. Identifies the output format (full graph dump vs. annotated definition) from the originating command.
2. Extracts universe expressions from each line using pattern matching on the constraint syntax.
3. Normalizes universe variable names to a canonical form (preserving the Coq-assigned names for traceability).
4. Emits one `UniverseConstraint` per parsed constraint line.
5. Collects all constraints into a list for downstream consumption by the Graph Builder or the response formatter.

Malformed lines (comments, blank lines, Coq informational messages) are skipped. If the parser encounters output that matches no known format, it records the unparseable text in a diagnostic field on the response rather than failing silently.

## Inconsistency Diagnosis Flow

When a user submits a universe inconsistency error for diagnosis (Epic 2):

```
diagnose_universe_error(error_message, environment_context)
  │
  ├─ 1. Parse the error message
  │      Extract the universe variables named in the error
  │      (e.g., "Universe inconsistency: cannot enforce u.42 < u.17
  │       because u.17 <= u.42 is already required")
  │
  ├─ 2. Retrieve the full constraint graph
  │      Submit Print Universes via coq_query
  │      Parse into ConstraintGraph
  │
  ├─ 3. Identify the relevant subgraph
  │      Starting from the universe variables named in the error,
  │      compute the reachable subgraph (forward and backward
  │      along constraint edges)
  │
  ├─ 4. Detect the inconsistent cycle
  │      Search for a directed cycle in the relevant subgraph
  │      that violates the well-ordering requirement
  │      (a cycle containing at least one strict "<" edge)
  │
  ├─ 5. Attribute constraints to source definitions
  │      For each constraint in the cycle:
  │        - Use About or Print on definitions that reference
  │          the involved universe variables
  │        - Map universe variable names to the definitions
  │          that introduced them
  │
  ├─ 6. Build the diagnosis
  │      Assemble an InconsistencyDiagnosis containing:
  │        - The cycle (ordered list of constraints)
  │        - Source attribution for each constraint
  │        - Plain-language explanation of the conflict
  │        - Suggested resolution strategies
  │
  └─ Return InconsistencyDiagnosis
```

### Cycle Detection

The constraint graph is a directed graph where edges represent `<`, `<=`, and `=` relationships. An inconsistency exists when there is a cycle that contains at least one strict inequality (`<`), since the universe ordering must be well-founded.

The Inconsistency Diagnoser performs cycle detection on the subgraph reachable from the error-named variables:

1. Build the subgraph from the parsed `ConstraintGraph`, filtered to the reachable set.
2. Run a depth-first search for back edges (standard cycle detection).
3. Among detected cycles, identify those containing at least one strict edge.
4. Select the shortest such cycle as the primary explanation (shorter cycles are easier to explain).

### Source Attribution

Universe variable names (`u.N`, `Top.M`) are internal identifiers. The Inconsistency Diagnoser maps them back to source-level definitions:

1. For each universe variable in the cycle, query `About` for definitions known to reference that variable (the constraint graph output sometimes includes definition-origin annotations; when it does not, the diagnoser falls back to iterating over candidate definitions from the error context).
2. Match universe variables to definitions by checking which definitions' annotated output (via `Set Printing Universes` + `Print`) references those variables.
3. Record the mapping in the `InconsistencyDiagnosis` as `(constraint, source_definition, location_hint)` triples.

This attribution is best-effort. When a universe variable cannot be traced to a specific definition, the diagnosis includes the raw variable name with a note that the origin could not be determined.

### Resolution Suggestions

Based on the cycle structure and source attribution, the diagnoser generates resolution suggestions from a fixed set of strategies:

- **Add universe polymorphism**: When a monomorphic definition introduces a rigid constraint that causes the cycle, suggest making it universe-polymorphic.
- **Adjust universe declarations**: When explicit `Constraint` or `Universe` declarations are involved, suggest modifying them.
- **Restructure to break the cycle**: When two definitions form a mutual constraint path, suggest decoupling them (e.g., by introducing an intermediate abstraction).
- **Use a universe-polymorphic variant**: When a monomorphic standard library definition is involved and a polymorphic variant exists, suggest using it.

The diagnoser selects applicable strategies based on which pattern the cycle matches. At least one suggestion is always included.

## Universe-Polymorphic Inspection

For definitions declared with `Polymorphic` or `#[universes(polymorphic)]` (Epic 3):

### Retrieving Instantiations (Story 3.1)

1. Enable universe printing: `Set Printing Universes.`
2. Print the use site (the definition that references the polymorphic definition): `Print <use_site_name>.`
3. The annotated output shows each occurrence of the polymorphic definition with concrete universe levels substituted for its universe parameters (e.g., `list@{u.5}` where `list` has one universe parameter).
4. Parse the annotated output to extract the mapping from universe parameters to concrete levels.
5. Restore printing: `Unset Printing Universes.`

### Comparing Definitions (Story 3.2)

1. Retrieve the universe constraints for both definitions (per-definition retrieval).
2. Retrieve the `About` output for both definitions to obtain their universe parameter declarations.
3. Identify the constraint sets for each definition.
4. Check compatibility: determine whether there exists an assignment of universe levels that satisfies both constraint sets simultaneously.
5. If incompatible, identify the specific constraints that conflict and report which definition's constraint is more restrictive.

Compatibility checking is a constraint satisfaction problem over the combined constraint sets. For the typical case (small numbers of universe variables per definition), exhaustive checking of the combined constraint graph for cycles is sufficient.

## Data Structures

### UniverseConstraint

A single constraint between two universe expressions.

| Field | Type | Description |
|-------|------|-------------|
| `left` | UniverseExpression | Left-hand side of the constraint |
| `relation` | `"lt"` or `"le"` or `"eq"` | Strict less-than, less-than-or-equal, or equality |
| `right` | UniverseExpression | Right-hand side of the constraint |
| `source` | string or null | Qualified name of the definition that introduced this constraint, if known |

### UniverseExpression

A universe level expression.

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `"variable"` or `"algebraic"` or `"set"` or `"prop"` | Expression kind |
| `name` | string or null | Universe variable name (e.g., `"u.42"`, `"Top.37"`) for `variable` kind |
| `base` | UniverseExpression or null | Base expression for `algebraic` kind |
| `offset` | non-negative integer or null | Increment (e.g., 1 for `u.N+1`) for `algebraic` kind |
| `operands` | list of UniverseExpression or null | Operands for `max(...)` expressions within `algebraic` kind |

### ConstraintGraph

The full or filtered universe constraint graph.

| Field | Type | Description |
|-------|------|-------------|
| `variables` | list of string | All universe variable names present in the graph |
| `constraints` | list of UniverseConstraint | All constraints in the graph |
| `node_count` | non-negative integer | Number of distinct universe variables |
| `edge_count` | non-negative integer | Number of constraints |
| `filtered_from` | string or null | If this is a filtered subgraph, the definition or variable it was filtered from |

### InconsistencyDiagnosis

The result of diagnosing a universe inconsistency error.

| Field | Type | Description |
|-------|------|-------------|
| `error_text` | string | The original error message submitted for diagnosis |
| `cycle` | list of UniverseConstraint | The constraints forming the inconsistent cycle, in order |
| `attributions` | list of ConstraintAttribution | Source attribution for each constraint in the cycle |
| `explanation` | string | Plain-language explanation of why the cycle is inconsistent |
| `suggestions` | list of string | Concrete resolution strategies |
| `relevant_subgraph` | ConstraintGraph | The subgraph reachable from the error-named variables |

### ConstraintAttribution

Maps a constraint to the source definition that introduced it.

| Field | Type | Description |
|-------|------|-------------|
| `constraint` | UniverseConstraint | The attributed constraint |
| `definition` | string or null | Qualified name of the definition that introduced this constraint |
| `location` | string or null | Human-readable location hint (e.g., file and line if available) |
| `confidence` | `"certain"` or `"inferred"` or `"unknown"` | Confidence level of the attribution |

## Integration with Vernacular Introspection

Universe inspection shares the **Coq Query Layer** with vernacular introspection. Both components issue vernacular commands (`Print`, `About`, `Check`, `Set`/`Unset` options) to the Coq backend and parse structured responses. Rather than duplicating this infrastructure, universe inspection depends on the same `coq_query` mechanism:

- **coq_query(command) -> raw_text**: Submits a vernacular command string to the active Coq backend process via the Proof Session Manager and returns the raw text response. This is the shared interface.
- **Command atomicity**: The Coq Query Layer guarantees that multi-command sequences (e.g., `Set Printing Universes` / `Print` / `Unset Printing Universes`) are submitted without interleaving from other callers on the same backend process.
- **Session context**: Universe inspection operates within an active proof session. The session determines which Coq environment is visible (loaded files, imported modules, current proof state). The Proof Session Manager owns the backend process; the Coq Query Layer borrows it for the duration of a query.

Universe inspection adds domain-specific parsing (the Constraint Parser) and domain-specific reasoning (the Graph Builder, Inconsistency Diagnoser, Polymorphic Inspector) on top of the shared query layer. Vernacular introspection returns lightly parsed results; universe inspection returns richly structured, domain-specific data.

## Error Handling

| Condition | Error Code | Behavior |
|-----------|-----------|----------|
| Definition name not found in environment | `NOT_FOUND` | Structured error: `Definition '{name}' not found in the current environment.` |
| Error message is not a universe inconsistency | `INVALID_INPUT` | Structured error: `The provided error is not a universe inconsistency error.` |
| Coq backend returns unexpected output format | `PARSE_ERROR` | Return partial results with unparseable text in a diagnostic field; do not discard successfully parsed constraints |
| No active session (no Coq environment loaded) | `SESSION_NOT_FOUND` | Structured error: `No active session. Open a proof session first to establish a Coq environment.` |
| Backend crash during query | `BACKEND_CRASHED` | Propagated from Proof Session Manager; no universe-specific handling |
| Definition has no universe constraints | (normal response) | Success response with empty constraint set and explanatory note; not an error |
| Constraint graph too large for response | `GRAPH_TOO_LARGE` | Return a truncated graph with a truncation flag, similar to `DIAGRAM_TRUNCATED` in visualization tools |
| Cycle detection finds no cycle (error message was misleading or environment changed) | (normal response) | Return diagnosis with empty cycle and explanation that the inconsistency could not be reproduced in the current environment |
| Source attribution fails for a constraint | (normal response) | Attribution confidence set to `"unknown"`; diagnosis proceeds with available information |
| Query timeout (large environment, slow backend) | `QUERY_TIMEOUT` | Structured error: `Universe query timed out after {timeout}s. Try filtering to a specific definition.` |

All error responses conform to the MCP error contract defined in [mcp-server.md](mcp-server.md).

## Design Rationale

### Why a separate component rather than extending vernacular introspection

Vernacular introspection provides general-purpose access to Coq's query commands. Universe inspection requires domain-specific parsing (constraint syntax), domain-specific data structures (constraint graphs), and domain-specific reasoning (cycle detection, source attribution, resolution suggestions). Embedding this in the general introspection layer would violate the single-responsibility boundary. The shared Coq Query Layer provides the integration point without coupling the two components' domain logic.

### Why parse constraints into a graph rather than returning raw text

Raw `Print Universes` output is unstructured text that the LLM would need to parse on every invocation. Parsing into a `ConstraintGraph` makes the data queryable (filter by reachability, detect cycles, compare definitions) and allows the component to perform analysis that raw text cannot support. The structured format also enables deterministic diagnosis rather than relying on the LLM to correctly interpret dense constraint output.

### Why best-effort source attribution rather than requiring complete attribution

Coq's universe variable names are internal and not always traceable to a single source definition. Some constraints arise from the combination of multiple definitions or from implicit universe unification. Requiring complete attribution would either produce incorrect results or fail on many real-world errors. Best-effort attribution with confidence levels gives the user maximum available information while being honest about uncertainty.

### Why filter by reachability rather than by definition name

A definition may involve universe variables that participate in constraints introduced by other definitions. Filtering by reachability from a definition's universe variables captures the full relevant context — including constraints that originate elsewhere but affect the definition's universe levels. Filtering by name alone would miss these transitive constraints, which are often the source of inconsistencies.

### Why suggest multiple resolution strategies

Universe inconsistencies can often be resolved in more than one way, and the best resolution depends on the user's broader design goals (e.g., whether they want universe polymorphism or prefer to restructure). Presenting multiple options lets the user (or Claude) choose the approach that best fits the context.
