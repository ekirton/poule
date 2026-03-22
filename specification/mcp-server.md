# MCP Server

Thin adapter between Claude Code, the retrieval pipeline, the proof session manager, the proof search engine, the fill admits orchestrator, and the Mermaid renderer — exposing search, proof interaction, proof search, and visualization tools via the Model Context Protocol.

**Architecture**: [mcp-server.md](../doc/architecture/mcp-server.md), [proof-search-engine.md](../doc/architecture/proof-search-engine.md), [fill-admits-orchestrator.md](../doc/architecture/fill-admits-orchestrator.md), [mermaid-renderer.md](../doc/architecture/mermaid-renderer.md), [diagram-file-output.md](../doc/architecture/diagram-file-output.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [response-types.md](../doc/architecture/data-models/response-types.md), [proof-types.md](../doc/architecture/data-models/proof-types.md)

---

## 1. Purpose

Define the MCP server that translates MCP tool calls into pipeline queries, session manager operations, search engine invocations, fill-admits orchestration, and renderer invocations — validates inputs, formats responses, manages index lifecycle on startup, and serializes proof interaction types.

## 2. Scope

**In scope**: 7 search tool handlers, 12 proof interaction tool handlers (11 P0 + 1 P1), 2 proof search tool handlers, 4 visualization tool handlers, input validation, error formatting, index state management, startup checks, response construction, proof state serialization, visualization dispatch, diagram file output integration.

**Out of scope**: Search logic (owned by pipeline/channels), storage management (owned by storage), Coq expression parsing (owned by pipeline), session state management (owned by proof-session), proof search algorithm (owned by proof-search-engine), admit location and orchestration (owned by fill-admits-orchestrator), proof type definitions (owned by data-models/proof-types), serialization format details (owned by proof-serialization), Mermaid diagram generation logic (owned by mermaid-renderer), HTML file writing logic (owned by diagram-file-output).

## 3. Definitions

| Term | Definition |
|------|-----------|
| MCP | Model Context Protocol — the communication protocol between Claude Code and tool servers |
| Tool handler | A function that processes one MCP tool call and returns a formatted response |
| Index state | The loaded state of the search index (ready, missing, or version-mismatched) |
| Session manager | The stateful component managing interactive proof sessions (see proof-session spec) |
| Proof state | A snapshot of goals and hypotheses at a single point in a proof |
| Mermaid renderer | The pure function component that generates Mermaid syntax from proof data (see mermaid-renderer spec) |
| Detail level | One of `summary`, `standard`, `detailed` — controls proof state diagram density |

## 4. Behavioral Requirements

### 4.1 Transport

The server shall support two transport modes selected via `--transport`:

| Mode | Flag | Usage |
|------|------|-------|
| SSE (default in container) | `--transport sse --host 127.0.0.1 --port 3000` | Persistent HTTP daemon; Claude Code connects via `url` in `mcp.json` |
| stdio | `--transport stdio` | Subprocess mode; Claude Code spawns the process directly |

In the standard container deployment the server runs in SSE mode as a background daemon, enabling the server to be stopped and restarted independently of the Claude Code session. Claude Code connects to `http://127.0.0.1:3000/sse`.

### 4.2 Search Tool Signatures

#### search_by_name(pattern, limit=50)

- REQUIRES: `pattern` is a non-empty string. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by BM25 relevance.
- Delegates to: `pipeline.search_by_name(ctx, pattern, limit)`

#### search_by_type(type_expr, limit=50)

- REQUIRES: `type_expr` is a non-empty string. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by RRF-fused score.
- Delegates to: `pipeline.search_by_type(ctx, type_expr, limit)`

#### search_by_structure(expression, limit=50)

- REQUIRES: `expression` is a non-empty string. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by structural score.
- Delegates to: `pipeline.search_by_structure(ctx, expression, limit)`

#### search_by_symbols(symbols, limit=50)

- REQUIRES: `symbols` is a non-empty list of symbol name strings (at any qualification level — short names like `Nat.add`, partial qualifications like `Init.Nat.add`, or fully qualified kernel names like `Coq.Init.Nat.add`). `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by MePo relevance. Symbol names are resolved to FQNs by the pipeline before matching.
- Delegates to: `pipeline.search_by_symbols(ctx, symbols, limit)`

#### get_lemma(name)

- REQUIRES: `name` is a non-empty string.
- ENSURES: Returns a `LemmaDetail` for the named declaration.
- On not found: returns `NOT_FOUND` error.
- Constructs `LemmaDetail` by querying: declaration row, outgoing `uses` dependencies, incoming `uses` dependencies, symbol set, node count. `proof_sketch` is always empty string in Phase 1. `score` is always 1.0 (exact match).

#### find_related(name, relation, limit=50)

- REQUIRES: `name` is a non-empty string. `relation` is one of: `"uses"`, `"used_by"`, `"same_module"`, `"same_typeclass"`. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` for related declarations.
- On unknown declaration name: returns `NOT_FOUND` error.

Query strategies:

| Relation | Strategy |
|----------|----------|
| `uses` | `dependencies` where `src = decl_id` and `relation = 'uses'` |
| `used_by` | `dependencies` where `dst = decl_id` and `relation = 'uses'` |
| `same_module` | `declarations` where `module = decl.module` and `id != decl_id` |
| `same_typeclass` | Two-hop: find typeclasses via `instance_of` edges from decl, then find other instances of those typeclasses |

All `find_related` results receive `score = 1.0` (relationship-based, not scored).

#### list_modules(prefix="")

- REQUIRES: `prefix` is a string (may be empty).
- ENSURES: Returns `Module[]` for all modules matching the prefix. If no modules match the given prefix, retries with the aliased prefix via `alias_prefix` (see [pipeline.md](pipeline.md) §4.1.1). Both `Coq.*` and `Corelib.*` prefixes are accepted for standard library modules. Results are deduplicated by module name.

### 4.3 Proof Interaction Tool Signatures

All proof interaction tools delegate to the session manager. The MCP server does not manage proof session state directly. On `SessionError` from the session manager, the server translates the error code to the corresponding MCP error response.

#### open_proof_session(file_path, proof_name)

- REQUIRES: `file_path` is a non-empty string (absolute path to a .v file). `proof_name` is a non-empty string (fully qualified proof name).
- ENSURES: Returns `{ session_id: string, state: ProofState }`. The session is registered and its Coq backend process is running.
- Delegates to: `session_manager.create_session(file_path, proof_name)`
- On file not found: returns `FILE_NOT_FOUND` error.
- On proof not found in file: returns `PROOF_NOT_FOUND` error.

> **Given** a valid .v file and proof name
> **When** `open_proof_session` is called
> **Then** the response contains a `session_id` string and a `ProofState` at step 0

> **Given** a non-existent file path
> **When** `open_proof_session` is called
> **Then** the response is a `FILE_NOT_FOUND` error

#### close_proof_session(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns `{ closed: true }`. The session is removed and its backend process is terminated.
- Delegates to: `session_manager.close_session(session_id)`
- On unknown session: returns `SESSION_NOT_FOUND` error.

#### list_proof_sessions()

- REQUIRES: No parameters.
- ENSURES: Returns `Session[]` for all active sessions.
- Delegates to: `session_manager.list_sessions()`

#### observe_proof_state(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns the current `ProofState` for the session.
- Delegates to: `session_manager.observe_state(session_id)`
- On unknown/expired/crashed session: returns the appropriate session error.

#### get_proof_state_at_step(session_id, step)

- REQUIRES: `session_id` is a non-empty string. `step` is a non-negative integer.
- ENSURES: Returns the `ProofState` at the given step index.
- Delegates to: `session_manager.get_state_at_step(session_id, step)`
- On step out of range: returns `STEP_OUT_OF_RANGE` error.

#### extract_proof_trace(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns the full `ProofTrace` for the session.
- Delegates to: `session_manager.extract_trace(session_id)`

#### submit_tactic(session_id, tactic)

- REQUIRES: `session_id` is a non-empty string. `tactic` is a non-empty string.
- ENSURES: Returns the resulting `ProofState` after applying the tactic.
- Delegates to: `session_manager.submit_tactic(session_id, tactic)`
- On tactic failure: returns `TACTIC_ERROR` with the Coq error message and the unchanged `ProofState`.

#### step_backward(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns the `ProofState` at the previous step.
- Delegates to: `session_manager.step_backward(session_id)`
- On already at initial state: returns `NO_PREVIOUS_STATE` error.

#### step_forward(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns `{ tactic: string, state: ProofState }` — the original tactic and resulting state.
- Delegates to: `session_manager.step_forward(session_id)`
- On proof already complete: returns `PROOF_COMPLETE` error.

#### submit_tactic_batch(session_id, tactics) — P1

- REQUIRES: `session_id` is a non-empty string. `tactics` is a non-empty list of non-empty strings.
- ENSURES: Returns `{ tactic: string, state: ProofState }[]` — one entry per successful tactic. Stops on first failure; the failure entry includes `error` instead of `state`.
- Delegates to: `session_manager.submit_tactic_batch(session_id, tactics)`

#### get_proof_premises(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns `PremiseAnnotation[]` for all tactic steps in the proof.
- Delegates to: `session_manager.get_premises(session_id)`

#### get_step_premises(session_id, step)

- REQUIRES: `session_id` is a non-empty string. `step` is a positive integer (range [1, total_steps]).
- ENSURES: Returns a single `PremiseAnnotation` for the given step.
- Delegates to: `session_manager.get_step_premises(session_id, step)`
- On step out of range: returns `STEP_OUT_OF_RANGE` error.

### 4.4 Visualization Tool Signatures

All visualization tools delegate diagram generation to the Mermaid renderer. The MCP server resolves data (from the session manager or search index) and passes it to the renderer. Visualization tools return Mermaid syntax text, not rendered images.

When `diagram_dir` is configured (not None), each visualization handler also writes a self-contained HTML file to the project directory via `write_diagram_html` as a fire-and-forget side effect (see [diagram-file-output specification](diagram-file-output.md)). Exceptions from the file write are caught and logged at WARNING, not propagated to the MCP response.

#### visualize_proof_state(session_id, step?, detail_level?)

- REQUIRES: `session_id` is a non-empty string. `step` is a non-negative integer (default: current step). `detail_level` is one of `"summary"`, `"standard"`, `"detailed"` (default: `"standard"`).
- ENSURES: Returns `{ mermaid: string, step_index: number }`.
- Resolves proof state: if `step` is provided, delegates to `session_manager.get_state_at_step(session_id, step)`; otherwise `session_manager.observe_state(session_id)`.
- Delegates rendering to: `renderer.render_proof_state(state, detail_level)`
- On unknown/expired session: returns the appropriate session error.
- On step out of range: returns `STEP_OUT_OF_RANGE` error.

> **Given** an active session at step 3 with 2 goals
> **When** `visualize_proof_state(session_id)` is called with default parameters
> **Then** the response contains a `mermaid` string and `step_index: 3`

> **Given** a session where the proof is complete
> **When** `visualize_proof_state` is called
> **Then** the Mermaid output contains a single `Proof complete (Qed)` node

#### visualize_proof_tree(session_id)

- REQUIRES: `session_id` is a non-empty string.
- ENSURES: Returns `{ mermaid: string, total_steps: number }`.
- Resolves proof trace: delegates to `session_manager.extract_trace(session_id)`.
- Verifies the final step's state has `is_complete=true`. If not, returns `PROOF_INCOMPLETE` error.
- Delegates rendering to: `renderer.render_proof_tree(trace)`
- On unknown/expired session: returns the appropriate session error.

> **Given** a session with a completed proof of 5 steps
> **When** `visualize_proof_tree(session_id)` is called
> **Then** the response contains a Mermaid tree diagram and `total_steps: 5`

> **Given** a session where the proof is not yet complete
> **When** `visualize_proof_tree(session_id)` is called
> **Then** the response is a `PROOF_INCOMPLETE` error

#### visualize_dependencies(name, max_depth?, max_nodes?)

- REQUIRES: `name` is a non-empty string. `max_depth` is a positive integer (default: 2). `max_nodes` is a positive integer (default: 50).
- ENSURES: Returns `{ mermaid: string, node_count: number, truncated: boolean }`.
- Resolves dependency data: queries the search index via `find_related(name, "uses")` recursively up to `max_depth` hops to build the adjacency list.
- Delegates rendering to: `renderer.render_dependencies(name, adjacency_list, max_depth, max_nodes)`
- On declaration not found: returns `NOT_FOUND` error.
- When the diagram is truncated (max_nodes exceeded): includes a `DIAGRAM_TRUNCATED` warning in the response alongside the valid diagram.

> **Given** a theorem `Nat.add_comm` in the search index
> **When** `visualize_dependencies(name="Nat.add_comm", max_depth=1)` is called
> **Then** the response contains a Mermaid graph of direct dependencies, `node_count`, and `truncated: false`

> **Given** a name not in the search index
> **When** `visualize_dependencies(name="nonexistent")` is called
> **Then** the response is a `NOT_FOUND` error

#### visualize_proof_sequence(session_id, detail_level?)

- REQUIRES: `session_id` is a non-empty string. `detail_level` is one of `"summary"`, `"standard"`, `"detailed"` (default: `"standard"`).
- ENSURES: Returns `{ diagrams: SequenceEntry[] }` where each entry contains `step_index`, `tactic`, and `mermaid`.
- Resolves proof trace: delegates to `session_manager.extract_trace(session_id)`. This requires the session to have an original script (completed proof). If the session has no original script (interactive session), `extract_trace` returns a `STEP_OUT_OF_RANGE` error, which the handler propagates as a `PROOF_INCOMPLETE` error.
- Delegates rendering to: `renderer.render_proof_sequence(trace, detail_level)`
- On unknown/expired session: returns the appropriate session error.
- On session with no original script: returns `PROOF_INCOMPLETE` error.

> **Given** a session with a completed proof of 3 steps
> **When** `visualize_proof_sequence(session_id)` is called
> **Then** the response contains 4 diagrams (initial state + 3 tactic steps), each with diff annotations

> **Given** an interactive session with no original script
> **When** `visualize_proof_sequence(session_id)` is called
> **Then** the response is a `PROOF_INCOMPLETE` error

### 4.5 Proof Search Tool Signatures

All proof search tools delegate to the Proof Search Engine or Fill Admits Orchestrator. The MCP server does not implement search algorithms or admit location logic.

#### proof_search(session_id, timeout?, max_depth?, max_breadth?)

- REQUIRES: `session_id` is a non-empty string. `timeout` is a positive number (default: 30). `max_depth` is a positive integer (default: 10). `max_breadth` is a positive integer (default: 20).
- ENSURES: Returns a SearchResult (see proof-search-engine spec §5). On success, includes the verified proof script. On failure, includes best partial proof and statistics.
- Delegates to: `search_engine.proof_search(session_id, timeout, max_depth, max_breadth)`
- On unknown/expired/crashed session: returns the appropriate session error.

> **Given** an active proof session with an open goal
> **When** `proof_search(session_id)` is called
> **Then** the engine runs best-first search and returns a SearchResult

> **Given** a non-existent session ID
> **When** `proof_search(session_id)` is called
> **Then** a `SESSION_NOT_FOUND` error is returned

> **Given** a proof search that times out
> **When** the result is returned
> **Then** it has `status = "failure"` with `states_explored > 0` and `wall_time_ms` near the timeout value

#### fill_admits(file_path, timeout_per_admit?, max_depth?, max_breadth?)

- REQUIRES: `file_path` is a non-empty string (absolute path to a .v file). `timeout_per_admit` is a positive number (default: 30). `max_depth` is a positive integer (default: 10). `max_breadth` is a positive integer (default: 20).
- ENSURES: Returns a FillAdmitsResult (see fill-admits-orchestrator spec §5). Includes per-admit outcomes and the modified script.
- Delegates to: `orchestrator.fill_admits(file_path, timeout_per_admit, max_depth, max_breadth)`
- On file not found: returns `FILE_NOT_FOUND` error.

> **Given** a .v file with two `admit.` calls
> **When** `fill_admits(file_path)` is called
> **Then** the orchestrator processes each admit and returns a FillAdmitsResult

> **Given** a .v file with no admits
> **When** `fill_admits(file_path)` is called
> **Then** a FillAdmitsResult with `total_admits = 0` and unmodified script is returned

> **Given** a non-existent file path
> **When** `fill_admits(file_path)` is called
> **Then** a `FILE_NOT_FOUND` error is returned

### 4.6 Input Validation

The server shall validate all inputs before delegating to the pipeline, session manager, search engine, orchestrator, or renderer:

| Validation | Rule |
|-----------|------|
| String parameters | Must be non-empty after stripping whitespace |
| `limit` parameter | Clamped to [1, 200] (values < 1 become 1, values > 200 become 200) |
| `symbols` list | Must be non-empty; each element must be non-empty after stripping |
| `relation` parameter | Must be one of the four recognized values |
| `session_id` parameter | Must be a non-empty string |
| `step` parameter | Must be a non-negative integer (for `get_proof_state_at_step`, `visualize_proof_state`); must be a positive integer (for `get_step_premises`) |
| `tactic` parameter | Must be a non-empty string after stripping whitespace |
| `tactics` list | Must be non-empty; each element must be a non-empty string after stripping |
| `detail_level` parameter | Must be one of `"summary"`, `"standard"`, `"detailed"` (default: `"standard"`) |
| `max_depth` parameter | Must be a positive integer (default: 2) |
| `max_nodes` parameter | Must be a positive integer (default: 50) |
| `timeout` / `timeout_per_admit` parameter | Must be a positive number; values ≤ 0 are clamped to 1 |
| `max_breadth` parameter | Must be a positive integer; values ≤ 0 are clamped to 1 |

Invalid inputs that cannot be clamped shall return a `PARSE_ERROR` response.

### 4.7 Index State Management

On startup, the server shall check the index in this order:

1. Does the database file exist at the configured path? If not → all search tool calls return `INDEX_MISSING`.
2. Does `schema_version` in `index_meta` match the tool's expected version? If not → trigger full re-index (in Phase 1, this translates to `INDEX_VERSION_MISMATCH` directing user to re-index manually).
3. Phase 1: `coq_version` and `mathcomp_version` are stored for informational purposes only. Library version checks are deferred to Phase 2.
4. All checks pass → create `PipelineContext` (loads WL histograms, inverted index, symbol frequencies into memory) → begin serving queries.

Proof interaction tools do not depend on the search index. They shall function even when the index is missing or version-mismatched. Visualization tools that operate on sessions (`visualize_proof_state`, `visualize_proof_tree`, `visualize_proof_sequence`) do not depend on the search index. `visualize_dependencies` requires the search index.

### 4.8 Response Formatting

All successful responses shall be formatted as MCP content with `type: "text"` containing a JSON-serialized result.

`SearchResult` serialization:
```json
{"name": "...", "statement": "...", "type": "...", "module": "...", "kind": "...", "score": 0.85}
```

`DeclKind` values are serialized as lowercase strings (e.g., `"lemma"`, `"theorem"`).

Proof interaction responses shall use the JSON serialization format defined in the proof-serialization specification. `ProofState`, `ProofTrace`, `PremiseAnnotation`, and `Session` objects are serialized using the corresponding `serialize_*` functions from the serialization layer.

Visualization responses shall be formatted as MCP content with `type: "text"` containing a JSON-serialized result. The `mermaid` field contains the raw Mermaid syntax string. Example:

```json
{"mermaid": "flowchart TD\n    s0g0[\"forall n, n + 0 = n\"]\n    ...", "step_index": 0}
```

For `visualize_proof_sequence`, the response contains a `diagrams` array:
```json
{"diagrams": [{"step_index": 0, "tactic": null, "mermaid": "..."}, {"step_index": 1, "tactic": "intro n", "mermaid": "..."}]}
```

### 4.9 Proof Error Response Enrichment

When a proof interaction tool returns a `TACTIC_ERROR`, the response shall include both the error object and the unchanged `ProofState` in the response body. This allows the LLM to report both the error and the current state without a separate `observe_proof_state` call.

```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"TACTIC_ERROR\", \"message\": \"...\", \"state\": {...}}}"}],
  "isError": true
}
```

## 5. Error Specification

All error responses use MCP's standard error format:

```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"...\", \"message\": \"...\"}}"}],
  "isError": true
}
```

### 5.1 Search Errors

| Condition | Error Code | Message Template |
|-----------|-----------|-----------------|
| No index database | `INDEX_MISSING` | `Index database not found at {path}. Run the indexing command to create it.` |
| Schema version mismatch | `INDEX_VERSION_MISMATCH` | `Index schema version {found} is incompatible with tool version {expected}. Re-indexing from scratch.` |
| Library version mismatch (Phase 2) | `INDEX_VERSION_MISMATCH` | `Installed library versions do not match the index. Re-index manually to update.` |
| Declaration not found | `NOT_FOUND` | `Declaration {name} not found in the index.` |
| Parse failure | `PARSE_ERROR` | `Failed to parse expression: {details}` |

Both server-side validation errors and pipeline-side parse errors use `PARSE_ERROR`. The `message` field distinguishes the origin.

### 5.2 Proof Interaction Errors

| Condition | Error Code | Message Template |
|-----------|-----------|-----------------|
| Session ID not found | `SESSION_NOT_FOUND` | `Proof session {session_id} not found or has expired.` |
| Session timed out (auto-closed) | `SESSION_EXPIRED` | `Proof session {session_id} was closed after 30 minutes of inactivity.` |
| File not found (open session) | `FILE_NOT_FOUND` | `File not found: {file_path}` |
| Proof not found in file | `PROOF_NOT_FOUND` | `Proof {proof_name} not found in {file_path}.` |
| Tactic failed in Coq | `TACTIC_ERROR` | `Tactic failed: {coq_error_message}` |
| Step index out of range | `STEP_OUT_OF_RANGE` | `Step {k} is out of range [0, {total_steps}].` |
| Already at initial state | `NO_PREVIOUS_STATE` | `Cannot step backward: already at the initial proof state.` |
| Already at final step | `PROOF_COMPLETE` | `Cannot step forward: proof is already complete at step {total_steps}.` |
| Backend process crashed | `BACKEND_CRASHED` | `The Coq backend for session {session_id} has crashed. Close the session and open a new one.` |

The MCP server translates `SessionError` exceptions from the session manager into the corresponding MCP error response by mapping `SessionError.code` to the error codes above.

### 5.3 Visualization Errors

| Condition | Error Code | Message Template |
|-----------|-----------|-----------------|
| Proof not complete (visualize_proof_tree) | `PROOF_INCOMPLETE` | `Cannot visualize proof tree: proof in session {session_id} is not yet complete.` |
| No original script (visualize_proof_sequence) | `PROOF_INCOMPLETE` | `Cannot visualize proof sequence: session {session_id} has no original proof script.` |
| Declaration not found (visualize_dependencies) | `NOT_FOUND` | `Declaration {name} not found in the index.` |
| Diagram truncated (max_nodes exceeded) | `DIAGRAM_TRUNCATED` | `Diagram truncated at {max_nodes} nodes. Reduce max_depth or max_nodes for a smaller diagram.` |

`DIAGRAM_TRUNCATED` is a warning, not a fatal error — the response includes a valid (truncated) diagram alongside the warning. The `truncated: true` flag in the response indicates truncation occurred.

Session-related errors for visualization tools (`SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `BACKEND_CRASHED`, `STEP_OUT_OF_RANGE`) use the same error codes and message templates as proof interaction tools (§5.2).

### 5.4 Proof Search Errors

| Condition | Error Code | Message Template |
|-----------|-----------|-----------------|
| Session not found (proof_search) | `SESSION_NOT_FOUND` | `Proof session {session_id} not found or has expired.` |
| Session expired (proof_search) | `SESSION_EXPIRED` | `Proof session {session_id} was closed after 30 minutes of inactivity.` |
| Backend crashed (proof_search) | `BACKEND_CRASHED` | `The Coq backend for session {session_id} has crashed. Close the session and open a new one.` |
| File not found (fill_admits) | `FILE_NOT_FOUND` | `File not found: {file_path}` |

Session-related errors for `proof_search` use the same error codes and message templates as proof interaction tools (§5.2). The `fill_admits` handler propagates `FILE_NOT_FOUND` from the orchestrator. Per-admit errors are included in the FillAdmitsResult, not raised as MCP errors.

## 6. Non-Functional Requirements

- The server is a thin adapter — it shall not implement search logic, manage storage directly, parse Coq expressions, manage proof session state, or generate Mermaid syntax directly.
- Startup time includes loading WL histograms into memory (~100MB for 100K declarations).
- SSE transport is the default in container deployment; stdio is retained for testing and direct invocation.
- Proof interaction tools are available immediately on startup, independent of index state.

## 7. Examples

### Successful search_by_name

Request: `search_by_name(pattern="Nat.add_comm", limit=10)`

Response:
```json
{
  "content": [{"type": "text", "text": "[{\"name\": \"Coq.Arith.PeanoNat.Nat.add_comm\", \"statement\": \"forall n m : nat, n + m = m + n\", \"type\": \"forall n m : nat, n + m = m + n\", \"module\": \"Coq.Arith.PeanoNat\", \"kind\": \"lemma\", \"score\": 0.95}]"}]
}
```

### Error: index missing

Request: any search tool call when database does not exist

Response:
```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"INDEX_MISSING\", \"message\": \"Index database not found at /path/to/index.db. Run the indexing command to create it.\"}}"}],
  "isError": true
}
```

### Error: declaration not found

Request: `get_lemma(name="nonexistent.declaration")`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"NOT_FOUND\", \"message\": \"Declaration nonexistent.declaration not found in the index.\"}}"}],
  "isError": true
}
```

### Successful open_proof_session

Request: `open_proof_session(file_path="/path/to/Nat.v", proof_name="Nat.add_comm")`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"session_id\": \"abc123\", \"state\": {\"schema_version\": 1, \"session_id\": \"abc123\", \"step_index\": 0, \"is_complete\": false, \"focused_goal_index\": 0, \"goals\": [{\"index\": 0, \"type\": \"forall n m : nat, n + m = m + n\", \"hypotheses\": []}]}}"}]
}
```

### Error: tactic failed

Request: `submit_tactic(session_id="abc123", tactic="invalid_tactic.")`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"TACTIC_ERROR\", \"message\": \"Tactic failed: No such tactic.\", \"state\": {\"schema_version\": 1, \"session_id\": \"abc123\", \"step_index\": 0, \"is_complete\": false, \"focused_goal_index\": 0, \"goals\": [...]}}}"}],
  "isError": true
}
```

### Error: session not found

Request: `observe_proof_state(session_id="nonexistent")`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"SESSION_NOT_FOUND\", \"message\": \"Proof session nonexistent not found or has expired.\"}}"}],
  "isError": true
}
```

### Successful visualize_proof_state

Request: `visualize_proof_state(session_id="abc123")`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"mermaid\": \"flowchart TD\\n    subgraph goal0[\\\"Goal 0 ✦\\\"]\\n        h0_0[\\\"n : nat\\\"]\\n        t0[\\\"⊢ n + 0 = n\\\"]\\n        h0_0 --> t0\\n    end\", \"step_index\": 0}"}]
}
```

### Successful visualize_proof_tree

Request: `visualize_proof_tree(session_id="abc123")`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"mermaid\": \"flowchart TD\\n    s0g0[\\\"forall n, n + 0 = n\\\"]\\n    s0g0 -->|\\\"intro n\\\"| s1g0[\\\"n + 0 = n\\\"]\\n    s1g0 -->|\\\"reflexivity\\\"| s2g0[\\\"✓\\\"]:::discharged\\n    classDef discharged fill:#d4edda,stroke:#28a745,stroke-dasharray:5 5\", \"total_steps\": 2}"}]
}
```

### Error: proof incomplete

Request: `visualize_proof_tree(session_id="abc123")` when proof is not yet complete

Response:
```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"PROOF_INCOMPLETE\", \"message\": \"Cannot visualize proof tree: proof in session abc123 is not yet complete.\"}}"}],
  "isError": true
}
```

### Successful proof_search

Request: `proof_search(session_id="abc123", timeout=30)`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"status\": \"success\", \"proof_script\": [\"intro n.\", \"simpl.\", \"reflexivity.\"], \"states_explored\": 12, \"unique_states\": 8, \"wall_time_ms\": 1500, \"steps\": [{\"tactic\": \"intro n.\", \"state_before\": {...}, \"state_after\": {...}}, ...]}"}]
}
```

### Proof search timeout

Request: `proof_search(session_id="abc123", timeout=5)`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"status\": \"failure\", \"proof_script\": null, \"states_explored\": 200, \"unique_states\": 150, \"wall_time_ms\": 5000, \"best_partial\": [\"intro n.\", \"simpl.\"], \"steps\": []}"}]
}
```

### Successful fill_admits

Request: `fill_admits(file_path="/path/to/example.v", timeout_per_admit=30)`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"total_admits\": 2, \"filled\": 1, \"unfilled\": 1, \"results\": [{\"proof_name\": \"foo\", \"admit_index\": 0, \"line_number\": 1, \"status\": \"filled\", \"replacement\": [\"reflexivity.\"], \"search_stats\": null, \"error\": null}, {\"proof_name\": \"bar\", \"admit_index\": 0, \"line_number\": 2, \"status\": \"unfilled\", \"replacement\": null, \"search_stats\": {\"states_explored\": 200, \"unique_states\": 150, \"wall_time_ms\": 30000}, \"error\": null}], \"modified_script\": \"...\"}"}]
}
```

### Successful visualize_dependencies

Request: `visualize_dependencies(name="Nat.add_comm", max_depth=1)`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"mermaid\": \"flowchart TD\\n    n0[\\\"Nat.add_comm\\\"]:::root\\n    n1[\\\"Nat.add_0_r\\\"]\\n    n0 --> n1\\n    classDef root fill:#fff3cd,stroke:#856404,stroke-width:2px\", \"node_count\": 2, \"truncated\": false}"}]
}
```

## 8. Language-Specific Notes (Python)

- Use the `mcp` Python SDK for MCP protocol handling. SSE transport uses `mcp.server.sse.SseServerTransport` with Starlette and uvicorn. Stdio transport uses `mcp.server.stdio.stdio_server`.
- Use `@server.tool()` decorator pattern for tool registration.
- Use `asyncio` for the server event loop.
- JSON serialization via `dataclasses.asdict()` + `json.dumps()` for search response types.
- Proof interaction responses use `serialize_*` functions from `poule.serialization.serialize`.
- Proof interaction handler functions are `async` to match the session manager's async interface.
- Visualization handler functions are `async` (session resolution is async); the renderer call itself is synchronous. When `diagram_dir` is set, handlers call `write_diagram_html` after rendering (fire-and-forget, exceptions caught).
- Proof search handler functions are `async`. `handle_proof_search` delegates to `search_engine.proof_search()`. `handle_fill_admits` delegates to `orchestrator.fill_admits()`.
- Package location: `src/poule/server/`.
- Handler naming convention: `handle_<tool_name>` (e.g., `handle_open_proof_session`, `handle_visualize_proof_state`, `handle_proof_search`, `handle_fill_admits`).
- Visualization handlers import from `poule.rendering.mermaid_renderer` and `poule.server.diagram_writer`.
