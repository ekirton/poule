# MCP Tools Reference

Poule exposes its functionality to Claude Code through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). The tools below are called automatically by Claude based on your natural-language requests — you do not need to invoke them directly.

## Search Tools

### search_by_name

Search for Coq declarations by name pattern (glob or substring).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | yes | Name pattern — supports `*` glob wildcard and substring matching |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

### search_by_type

Multi-channel search for Coq declarations matching a type expression. Combines structural, symbol, lexical, and neural channels via reciprocal rank fusion.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type_expr` | string | yes | A Coq type expression (e.g., `forall n : nat, n + 0 = n`) |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

### search_by_structure

Find Coq declarations with structurally similar expressions using WL graph kernels and tree edit distance.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `expression` | string | yes | A Coq expression to match structurally |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

### search_by_symbols

Find Coq declarations sharing mathematical symbols with the query, using MePo-style iterative relevance filtering.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbols` | array of strings | yes | List of fully qualified symbol names |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

### get_lemma

Retrieve full details for a specific Coq declaration by its fully qualified name, including its statement, type, module, dependencies, and dependents.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Fully qualified declaration name |

### find_related

Navigate the dependency graph from a Coq declaration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Fully qualified declaration name |
| `relation` | string | yes | One of: `uses`, `used_by`, `same_module`, `same_typeclass` |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

### list_modules

Browse the Coq module hierarchy indexed in the database.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prefix` | string | no | Module path prefix filter (e.g., `Coq.Arith`) |

## Proof Interaction Tools

Proof interaction tools work independently of the search index — no indexing step is required. They communicate with a live Coq process through coq-lsp or SerAPI.

### open_proof_session

Start an interactive proof session for a named proof in a `.v` file. Returns a `session_id` used by all other proof tools.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | yes | Absolute path to a `.v` file |
| `proof_name` | string | yes | Fully qualified proof name within the file |

### close_proof_session

Terminate a proof session and release its Coq backend process.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID returned by `open_proof_session` |

### list_proof_sessions

List all active proof sessions with metadata (file path, proof name, current step).

*No parameters.*

### observe_proof_state

Get the current proof state: goals, hypotheses, and the focused goal.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |

### get_proof_state_at_step

Get the proof state at a specific step index without changing the session's current position.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `step` | integer | yes | Step index (0-based) |

### extract_proof_trace

Get the full proof trace — every state and tactic from the beginning of the proof to the current position.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |

### submit_tactic

Submit a single tactic and receive the resulting proof state or a structured error.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `tactic` | string | yes | Coq tactic to execute |

### step_backward

Undo the last tactic, returning to the previous proof state.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |

### step_forward

Replay the next tactic from the original proof script.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |

### submit_tactic_batch

Submit multiple tactics in sequence. Execution stops on the first failure and returns the error along with the last successful state.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `tactics` | array of strings | yes | List of tactics to execute in order |

### get_proof_premises

Get premise annotations for all tactic steps in the proof — which lemmas, hypotheses, constructors, and definitions each tactic used.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |

### get_step_premises

Get premise annotations for a single proof step.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `step` | integer | yes | Step index (1-based, range [1, total_steps]) |

## Visualization Tools

Visualization tools generate [Mermaid](https://mermaid.js.org/) diagram syntax. When the [Mermaid Chart MCP server](https://github.com/Mermaid-Chart/mermaid-mcp-server) is also configured, Claude can render these diagrams as images automatically.

### visualize_proof_state

Render the current proof state (goals, hypotheses, local context) as a Mermaid flowchart.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `step` | integer | no | Step index to visualize (defaults to current step) |
| `detail_level` | string | no | One of: `summary`, `standard`, `detailed` (default: `standard`) |

### visualize_proof_tree

Render a completed proof as a top-down Mermaid tree showing tactic applications and branching structure. The proof must be complete.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |

### visualize_dependencies

Render a theorem's dependency neighborhood as a Mermaid directed graph with depth limiting.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Fully qualified declaration name |
| `max_depth` | integer | no | Maximum BFS depth (default: 2) |
| `max_nodes` | integer | no | Maximum nodes in the graph (default: 50) |

### visualize_proof_sequence

Render step-by-step proof evolution as a sequence of Mermaid diagrams with diff highlighting for added, removed, and changed elements.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session ID |
| `detail_level` | string | no | One of: `summary`, `standard`, `detailed` (default: `standard`) |
