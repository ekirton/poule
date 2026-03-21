# CLI Proof Replay

Batch proof trace extraction from the terminal, for Coq developers, CI pipelines, and dataset-building scripts that do not use an MCP client.

---

## Problem

The proof interaction tools (open session, step forward, extract trace, get premises) are currently accessible only through the MCP server, which requires Claude Code or another MCP client. Terminal users, CI pipelines, and dataset-building scripts have no way to extract proof traces without that intermediary.

## Solution

A `replay-proof` CLI subcommand that opens a proof session, walks the entire proof non-interactively, outputs the trace (and optionally premise annotations), then cleans up. One command, one proof, complete output.

```
poule replay-proof <file_path> <proof_name> [--json] [--premises]
```

## Design Rationale

### Why batch-only (not REPL)

Interactive stepping, tactic submission, and branching are MCP-mediated behaviors — they require an LLM or tool builder maintaining conversational state. The CLI serves the batch use case: extract a complete proof trace in one shot for downstream consumption.

### Why no `--db`

Proof interaction is independent of the search index. The `replay-proof` command operates directly on .v files through the Coq backend — it never touches the SQLite index. Adding `--db` would be misleading.

### Why `--premises` is opt-in

Premise extraction requires additional backend calls for each tactic step. For users who only need the proof trace (the common case), making premises opt-in avoids unnecessary latency.

### Why reuse SessionManager

The CLI uses the same `SessionManager` that the MCP server uses. This means the CLI and MCP server exercise identical code paths for session lifecycle, trace extraction, and premise retrieval. No second implementation to maintain.

## Scope Boundaries

The CLI `replay-proof` command provides:

- Non-interactive, complete proof replay
- Human-readable and JSON output
- Optional premise annotations

It does **not** provide:

- Interactive stepping (that is MCP-mediated)
- Tactic submission or proof exploration (MCP-mediated)
- Partial trace extraction or step ranges
- Multiple proofs in a single invocation

## Acceptance Criteria

### Replay Proof Trace via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN a valid .v file and a named proof within it WHEN `replay-proof <file_path> <proof_name>` is executed THEN the command prints a human-readable trace to stdout showing each proof step with its tactic, goals, and hypotheses, and exits with code 0
- GIVEN a valid .v file and proof WHEN `replay-proof <file_path> <proof_name> --json` is executed THEN the command prints the serialized proof trace as JSON to stdout and exits with code 0
- GIVEN the JSON output WHEN it is parsed THEN it conforms to the `ProofTrace` schema produced by `serialize_proof_trace()`

**Traces to:** R2-P0-5

### Replay Proof with Premise Annotations

**Priority:** P0
**Stability:** Stable

- GIVEN a valid proof WHEN `replay-proof <file_path> <proof_name> --premises` is executed THEN the output includes per-step premise annotations alongside the proof trace
- GIVEN `--json --premises` flags WHEN the command is executed THEN the JSON output wraps the trace and premises as `{"trace": ..., "premises": [...]}`
- GIVEN the premise annotations WHEN they are inspected THEN each annotation includes the step index, tactic, and list of premises with name and kind

**Traces to:** R2-P0-6

### Replay Proof Error Handling

**Priority:** P0
**Stability:** Stable

- GIVEN a file path that does not exist WHEN `replay-proof` is executed THEN an error message is printed to stderr and the command exits with code 1
- GIVEN a valid file but a nonexistent proof name WHEN `replay-proof` is executed THEN an error message is printed to stderr and the command exits with code 1
- GIVEN a Coq backend crash during replay WHEN the error is detected THEN an error message is printed to stderr, the session is cleaned up, and the command exits with code 1
- GIVEN missing required arguments WHEN `replay-proof` is executed THEN the command exits with code 2 (usage error)
