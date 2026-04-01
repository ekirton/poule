# MCP Tools Reference

Full human-readable reference: this file. See also [doc/claude-skills.md](claude-skills.md) for compound workflows.

All search tools accept an optional `limit` (integer, default 50, max 200).
All proof interaction tools accept `session_id` (string, required) — returned by `open_proof_session`.

## Search Tools

| Tool | Required params | Notes |
|------|----------------|-------|
| `search_by_name` | `pattern` (string) | Glob `*` and substring matching |
| `search_by_type` | `type_expr` (string) | Multi-channel: structural + symbol + lexical via RRF |
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
| `suggest_tactics` | `session_id` (string) | Suggests tactics for the current proof state. Returns ranked list combining neural predictions (when a trained model is available) with rule-based suggestions. |

## Profiling Tools

No search index required — invokes `coqc` directly or instruments a proof session.

| Tool | Required params | Optional params | Notes |
|------|----------------|-----------------|-------|
| `profile_proof` | `file_path` (string) | `lemma_name` (string), `mode` (string), `baseline_path` (string), `timeout_seconds` (integer) | See modes below |

**Modes** (`mode` parameter):

| Mode | Description | Additional requirements |
|------|-------------|----------------------|
| `timing` (default) | Compiles with `coqc -time-file`, returns per-sentence timing ranked slowest-first. If `lemma_name` is set, filters to that proof. | — |
| `ltac` | Opens a proof session, instruments `Set Ltac Profiling`, replays proof, returns Ltac call-tree breakdown | `lemma_name` required |
| `compare` | Parses a baseline `.v.timing` file, runs a fresh timing pass, returns per-sentence diff with regression/improvement classification | `baseline_path` required |

**Bottleneck classification:** All modes classify bottlenecks by category (`SlowQed`, `SlowReduction`, `TypeclassBlowup`, `HighSearchDepth`, `ExpensiveMatch`, `General`) with severity levels and optimization suggestion hints.

## Education Tools

| Tool | Required params | Optional params | Notes |
|------|----------------|-----------------|-------|
| `education_context` | `query` (string) | `limit` (integer, default 3, max 10), `volume` (string) | Retrieves relevant passages from Software Foundations. `volume` filters by book: `lf`, `plf`, `vfa`, `qc`, `secf`, `slf`, `vc`. Returns text, code blocks, source citation, and browser path. |

## Visualization Tools

Generate Mermaid diagram syntax. If the Mermaid Chart MCP server is configured, diagrams render automatically.

| Tool | Additional params | Notes |
|------|-----------------|-------|
| `visualize_proof_state` | `step` (integer, optional), `detail_level` (string, optional) | `detail_level`: `summary`/`standard`/`detailed` (default: `standard`) |
| `visualize_proof_tree` | — | Proof must be complete |
| `visualize_dependencies` | `name` (string), `max_depth` (integer, default 2), `max_nodes` (integer, default 50) | No `session_id` — uses search index |
| `visualize_proof_sequence` | `detail_level` (string, optional) | Step-by-step evolution with diff highlighting |
