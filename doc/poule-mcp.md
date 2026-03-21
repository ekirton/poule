# MCP Tools Reference

Full human-readable reference: this file. See also [doc/claude-skills.md](claude-skills.md) for compound workflows.

All search tools accept an optional `limit` (integer, default 50, max 200).
All proof interaction tools accept `session_id` (string, required) — returned by `open_proof_session`.

## Search Tools

| Tool | Required params | Notes |
|------|----------------|-------|
| `search_by_name` | `pattern` (string) | Glob `*` and substring matching |
| `search_by_type` | `type_expr` (string) | Multi-channel: structural + symbol + lexical + neural via RRF |
| `search_by_structure` | `expression` (string) | WL graph kernels + tree edit distance |
| `search_by_symbols` | `symbols` (string[]) | Fully qualified names; MePo-style relevance filtering |
| `get_lemma` | `name` (string) | Full declaration detail: statement, type, module, deps |
| `find_related` | `name` (string), `relation` (string) | Relations: `uses`, `used_by`, `same_module`, `same_typeclass` |
| `list_modules` | — | Optional `prefix` (string) filter, e.g. `Coq.Arith` |

## Proof Interaction Tools

No search index required — communicates with a live Coq process via coq-lsp or SerAPI.

| Tool | Additional params | Notes |
|------|-----------------|-------|
| `open_proof_session` | `file_path` (string), `proof_name` (string) | Returns `session_id` |
| `close_proof_session` | — | Releases the backend process |
| `list_proof_sessions` | — | No params; lists active sessions with metadata |
| `observe_proof_state` | — | Current goals, hypotheses, focused goal |
| `get_proof_state_at_step` | `step` (integer, 0-based) | Non-destructive — does not move current position |
| `extract_proof_trace` | — | Full state+tactic history from start to current position |
| `submit_tactic` | `tactic` (string) | Returns new proof state or structured error |
| `step_backward` | — | Undo last tactic |
| `step_forward` | — | Replay next tactic from original script |
| `submit_tactic_batch` | `tactics` (string[]) | Stops on first failure; returns error + last good state |
| `get_proof_premises` | — | Premise annotations for all steps |
| `get_step_premises` | `step` (integer, 1-based) | Premise annotations for one step |

## Visualization Tools

Generate Mermaid diagram syntax. If the Mermaid Chart MCP server is configured, diagrams render automatically.

| Tool | Additional params | Notes |
|------|-----------------|-------|
| `visualize_proof_state` | `step` (integer, optional), `detail_level` (string, optional) | `detail_level`: `summary`/`standard`/`detailed` (default: `standard`) |
| `visualize_proof_tree` | — | Proof must be complete |
| `visualize_dependencies` | `name` (string), `max_depth` (integer, default 2), `max_nodes` (integer, default 50) | No `session_id` — uses search index |
| `visualize_proof_sequence` | `detail_level` (string, optional) | Step-by-step evolution with diff highlighting |
