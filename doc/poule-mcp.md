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
| `submit_tactic` | `tactic` (string), optional `options` (object) | Returns new proof state or structured error. See **Hammer Automation** below for special tactic keywords. |
| `step_backward` | — | Undo last tactic |
| `step_forward` | — | Replay next tactic from original script |
| `submit_tactic_batch` | `tactics` (string[]) | Stops on first failure; returns error + last good state |
| `get_proof_premises` | — | Premise annotations for all steps |
| `get_step_premises` | `step` (integer, 1-based) | Premise annotations for one step |
| `suggest_tactics` | `session_id` (string) | Suggests tactics for the current proof state. Returns ranked list combining neural predictions (when a trained model is available) with rule-based suggestions. |

## Hammer Automation

The `submit_tactic` tool doubles as the entry point for CoqHammer. When the `tactic` string matches a recognized keyword, the handler delegates to the hammer engine instead of sending the tactic directly to Coq.

**Keywords:**

| Keyword | Description | Default timeout |
|---------|-------------|-----------------|
| `hammer` | Standard CoqHammer with ATP backend | 30 s |
| `sauto` | Semi-automated search tactic | 10 s |
| `qauto` | Quick automation tactic | 5 s |
| `auto_hammer` | Multi-strategy fallback — tries `hammer`, then `sauto`, then `qauto`, stops on first success | 90 s total |

**`options` parameter** (optional object, ignored for non-hammer tactics):

| Key | Type | Description |
|-----|------|-------------|
| `timeout` | number | Timeout in seconds (overrides the keyword default) |
| `hints` | string[] | Lemma names to pass as hints |
| `sauto_depth` | integer | Search depth for the `sauto` strategy |
| `qauto_depth` | integer | Search depth for the `qauto` strategy |
| `unfold` | string[] | Definitions to unfold (for `sauto`/`qauto`) |

**Return value** (replaces the normal proof-state response):

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `success` or `failure` |
| `proof_script` | string \| null | Successful tactic string, or null on failure |
| `atp_proof` | string \| null | ATP proof text (hammer strategy only) |
| `strategy_used` | string \| null | `hammer`, `sauto`, or `qauto` — whichever succeeded |
| `state` | ProofState | Updated proof state |
| `diagnostics` | StrategyDiagnostic[] | One entry per strategy attempted |
| `wall_time_ms` | number | Total wall-clock time |

**StrategyDiagnostic** (per failed strategy):

| Field | Type | Description |
|-------|------|-------------|
| `strategy` | string | `hammer`, `sauto`, or `qauto` |
| `failure_reason` | string | `timeout`, `no_proof_found`, `reconstruction_failed`, or `tactic_error` |
| `detail` | string | Human-readable error message |
| `partial_progress` | string \| null | ATP proof text when reconstruction failed |
| `wall_time_ms` | number | Time consumed by this strategy |
| `timeout_used` | number | Timeout value applied (seconds) |

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
