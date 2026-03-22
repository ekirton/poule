# MCP Server

The thin adapter layer between Claude Code, the search backend, the proof session manager, and the Mermaid renderer. The [CLI](cli.md) is a peer adapter that provides the same search capabilities for terminal users.

**Feature**: [MCP Tool Surface](../features/mcp-tool-surface.md), [Proof Interaction MCP Tools](../features/proof-mcp-tools.md), [Visualization MCP Tools](../features/visualization-mcp-tools.md), [Proof Search MCP Tools](../features/proof-search-mcp-tools.md)

---

## Transport

The server runs as a persistent HTTP daemon and communicates via SSE transport. Claude Code connects to it using a `url` entry in `mcp.json` (`http://127.0.0.1:3000/sse`) rather than spawning a subprocess. This allows the server to be stopped and restarted independently — by the developer or by Claude itself — without terminating the Claude session.

The stdio transport (`--transport stdio`) remains available for direct invocation and testing but is not used in the standard container deployment.

## Tool Signatures

```typescript
// Structural search: find declarations with similar expression structure
search_by_structure(
  expression: string,  // Coq expression or type (parsed by backend)
  limit: number = 50   // candidates to return (bias toward high recall)
) → SearchResult[]

// Symbol search: find declarations sharing symbols with the query
// Accepts names at any qualification level (short, partial, or fully qualified);
// resolved to FQNs by the retrieval pipeline before matching.
search_by_symbols(
  symbols: string[],   // constant/inductive names (any qualification level)
  limit: number = 50
) → SearchResult[]

// Name search: find declarations by name pattern
search_by_name(
  pattern: string,     // search query (preprocessed to FTS5 expression by pipeline)
  limit: number = 50
) → SearchResult[]

// Type search: find declarations whose type matches a pattern
search_by_type(
  type_expr: string,    // Coq type expression
  limit: number = 50
) → SearchResult[]

// Get full details for a specific declaration
get_lemma(
  name: string         // fully qualified name
) → LemmaDetail

// Navigate the dependency graph
find_related(
  name: string,
  relation: "uses" | "used_by" | "same_module" | "same_typeclass",
  limit: number = 50
) → SearchResult[]

// Browse module structure
list_modules(
  prefix: string = ""  // e.g., "Coq.Arith", "Corelib.Arith", or "mathcomp.algebra"
) → Module[]
```

## Response Types

```typescript
SearchResult = {
  name: string,          // fully qualified name
  statement: string,     // pretty-printed statement
  type: string,          // pretty-printed type
  module: string,        // containing module
  kind: string,          // "lemma" | "theorem" | "definition" | "instance" | ...
  score: number          // relevance score (0-1)
}

LemmaDetail = SearchResult & {
  dependencies: string[],  // names this declaration uses
  dependents: string[],    // names that use this declaration
  proof_sketch: string,    // tactic script or proof term; Phase 1: always empty string (no extraction source)
  symbols: string[],       // constant symbols appearing in the statement
  node_count: number       // expression tree size (for diagnostics)
}
```

## Proof Interaction Tool Signatures

```typescript
// Session management
open_proof_session(
  file_path: string,     // absolute path to .v file
  proof_name: string     // fully qualified proof name
) → { session_id: string, state: ProofState }

close_proof_session(
  session_id: string
) → { closed: true }

list_proof_sessions() → Session[]

// State observation
observe_proof_state(
  session_id: string
) → ProofState

get_proof_state_at_step(
  session_id: string,
  step: number           // 0 ≤ step ≤ total_steps
) → ProofState

extract_proof_trace(
  session_id: string
) → ProofTrace

// Tactic interaction
submit_tactic(
  session_id: string,
  tactic: string         // Coq tactic string
) → ProofState

step_backward(
  session_id: string
) → ProofState

step_forward(
  session_id: string
) → { tactic: string, state: ProofState }

// Batch tactic submission (P1 — should-have)
submit_tactic_batch(
  session_id: string,
  tactics: string[]      // Coq tactic strings, executed in order
) → { tactic: string, state: ProofState }[]  // one entry per successful tactic; stops on first failure

// Premise extraction
get_proof_premises(
  session_id: string
) → PremiseAnnotation[]

get_step_premises(
  session_id: string,
  step: number           // 1 ≤ step ≤ total_steps
) → PremiseAnnotation
```

Proof interaction response types are defined in [data-models/proof-types.md](data-models/proof-types.md). Serialization format is defined in [proof-serialization.md](proof-serialization.md).

## Visualization Tool Signatures

```typescript
// Render a proof state as a Mermaid diagram
visualize_proof_state(
  session_id: string,              // active session to read state from
  step?: number,                   // step index (default: current step)
  detail_level?: "summary" | "standard" | "detailed"  // default: "standard"
) → { mermaid: string, step_index: number }

// Render a completed proof as a Mermaid tree diagram
visualize_proof_tree(
  session_id: string               // session with a completed proof
) → { mermaid: string, total_steps: number }

// Render a theorem's dependency subgraph as a Mermaid diagram
visualize_dependencies(
  name: string,                    // fully qualified theorem name
  max_depth?: number,              // default: 2
  max_nodes?: number               // default: 50
) → { mermaid: string, node_count: number, truncated: boolean }

// Render step-by-step proof evolution as a sequence of Mermaid diagrams
visualize_proof_sequence(
  session_id: string,              // session with a completed proof
  detail_level?: "summary" | "standard" | "detailed"  // default: "standard"
) → { diagrams: { step_index: number, tactic: string | null, mermaid: string }[] }
```

Visualization tools delegate to the [Mermaid Renderer](mermaid-renderer.md) for diagram generation. The MCP server is responsible for:
- Resolving `session_id` to proof state / trace data via the Proof Session Manager
- Resolving `name` to dependency data via the search index (`find_related` with `uses`)
- Passing resolved data and configuration to the renderer
- Returning the renderer's Mermaid text in the response
- Writing a self-contained HTML file to the project directory via `write_diagram_html` when `diagram_dir` is configured (fire-and-forget side effect; see [Diagram File Output](diagram-file-output.md))

Visualization handlers accept `diagram_dir: Path | None`. When set, they write an HTML file containing the rendered diagram(s) as a side effect after generating Mermaid text. The HTML file replaces the previous SSE-based live diagram viewer (`/viewer` endpoint and `DiagramBroadcaster`), which has been removed. Visualization tools continue to return Mermaid syntax text in the MCP response.

## Proof Search Tool Signatures

```typescript
// Run best-first proof search on the current goal
proof_search(
  session_id: string,            // active proof session
  timeout?: number,              // wall-clock limit in seconds (default: 30)
  max_depth?: number,            // max tactic sequence length (default: 10)
  max_breadth?: number           // max candidates per node (default: 20)
) → SearchResult                 // see proof-search-engine.md for SearchResult type

// Scan a file for admits and attempt to fill each via proof search
fill_admits(
  file_path: string,             // absolute path to .v file
  timeout_per_admit?: number,    // wall-clock limit per admit in seconds (default: 30)
  max_depth?: number,            // max tactic sequence length per admit (default: 10)
  max_breadth?: number           // max candidates per node per admit (default: 20)
) → FillAdmitsResult             // see fill-admits-orchestrator.md for FillAdmitsResult type
```

Proof search tool response types are defined in [proof-search-engine.md](proof-search-engine.md) (SearchResult, ProofStep) and [fill-admits-orchestrator.md](fill-admits-orchestrator.md) (FillAdmitsResult, AdmitResult).

## Server Responsibilities

The MCP server is a thin adapter. It:
- Validates inputs (non-empty strings, limit range clamping to [1, 200])
- Delegates Coq expression parsing to the retrieval pipeline — pipeline parse errors are translated to `PARSE_ERROR` responses
- Translates MCP tool calls to search backend queries
- Delegates proof interaction tool calls to the [Proof Session Manager](proof-session.md)
- Delegates proof search tool calls to the [Proof Search Engine](proof-search-engine.md) and [Fill Admits Orchestrator](fill-admits-orchestrator.md)
- Delegates visualization tool calls to the [Mermaid Renderer](mermaid-renderer.md)
- Formats search backend, session manager, and renderer results into MCP response objects
- Serializes proof interaction types using the [proof serialization](proof-serialization.md) conventions
- Handles errors (unknown declarations, parse failures, session errors, visualization errors) with structured error responses

It does **not** implement search logic, manage storage, parse Coq expressions, manage proof session state, execute proof search algorithms, or generate Mermaid syntax directly.

### `find_related` query strategies

| Relation | Strategy |
|----------|----------|
| `uses` | Direct lookup: `dependencies` where `src = decl_id` and `relation = 'uses'` |
| `used_by` | Reverse lookup: `dependencies` where `dst = decl_id` and `relation = 'uses'` |
| `same_module` | Lookup: `declarations` where `module = decl.module` and `id != decl_id` |
| `same_typeclass` | Two-hop: find typeclasses via `dependencies` where `src = decl_id` and `relation = 'instance_of'`, then find other declarations with `instance_of` edges to the same typeclasses |

## Error Contract

All error responses use MCP's standard error format:

```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"...\", \"message\": \"...\"}}"}],
  "isError": true
}
```

| Condition | Error Code | Message |
|-----------|-----------|---------|
| No index database at configured path | `INDEX_MISSING` | Index database not found at `{path}`. Run the indexing command to create it. |
| Index schema version does not match tool version | `INDEX_VERSION_MISMATCH` | Index schema version `{found}` is incompatible with tool version `{expected}`. Re-indexing from scratch. |
| Library version changed (stale index detected) | `INDEX_VERSION_MISMATCH` | Installed library versions do not match the index. Re-index manually to update. |
| `get_lemma` with unknown name | `NOT_FOUND` | Declaration `{name}` not found in the index. |
| Malformed query expression | `PARSE_ERROR` | Failed to parse expression: `{details}` (both server-side validation and pipeline-side parse errors use `PARSE_ERROR`; the `message` field distinguishes the origin) |
| Session ID not found or expired | `SESSION_NOT_FOUND` | Proof session `{session_id}` not found or has expired. |
| Session timed out (auto-closed) | `SESSION_EXPIRED` | Proof session `{session_id}` was closed after 30 minutes of inactivity. |
| File not found (open session) | `FILE_NOT_FOUND` | File not found: `{file_path}` |
| Proof not found in file (open session) | `PROOF_NOT_FOUND` | Proof `{proof_name}` not found in `{file_path}`. |
| Tactic failed in Coq | `TACTIC_ERROR` | Tactic failed: `{coq_error_message}` (proof state unchanged; the unchanged ProofState is included in the response alongside the error) |
| Step index out of range | `STEP_OUT_OF_RANGE` | Step `{k}` is out of range [0, `{total_steps}`]. |
| Already at initial state (step backward) | `NO_PREVIOUS_STATE` | Cannot step backward: already at the initial proof state. |
| Already at final step (step forward) | `PROOF_COMPLETE` | Cannot step forward: proof is already complete at step `{total_steps}`. |
| Backend process crashed | `BACKEND_CRASHED` | The Coq backend for session `{session_id}` has crashed. Close the session and open a new one. |
| Proof not complete (visualize_proof_tree, visualize_proof_sequence) | `PROOF_INCOMPLETE` | Cannot visualize proof tree: proof in session `{session_id}` is not yet complete. |
| Declaration not found (visualize_dependencies) | `NOT_FOUND` | Declaration `{name}` not found in the index. |
| Diagram too large (renderer hit max_nodes) | `DIAGRAM_TRUNCATED` | Diagram truncated at `{max_nodes}` nodes. Reduce max_depth or max_nodes for a smaller diagram. (Warning, not error — included alongside a valid diagram.) |
| Proof search timeout (not an error) | (normal response) | Proof search returns a failure result with partial progress; no error code — the timeout is an expected outcome. |
| No admits found in file (fill_admits) | (normal response) | Success response with `total_admits: 0` and unmodified script; no error code. |
| File not found (fill_admits) | `FILE_NOT_FOUND` | File not found: `{file_path}` |
| LLM API unavailable during search | (normal response) | Search continues with solver candidates only; failure result includes `llm_unavailable: true` flag. |

On startup, the server checks the index in this order:
1. Does the database file exist? If not → `INDEX_MISSING`.
2. Does the `schema_version` in `index_meta` match the tool's expected version? If not → full re-index.
3. Do the library versions in `index_meta` match the currently installed versions? If not → `INDEX_VERSION_MISMATCH`; the user must re-index manually. Phase 1 validates `schema_version` only. `coq_version` and `library_versions` are stored for informational purposes; library version checks are deferred to Phase 2.

Proof interaction errors include the unchanged ProofState in the response body (alongside the error object) when the session is still active. This allows the LLM to report both the error and the current state to the user without a separate `observe_proof_state` call.
