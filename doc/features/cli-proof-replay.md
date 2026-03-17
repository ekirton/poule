# CLI Proof Replay

Batch proof trace extraction from the terminal, for Coq developers, CI pipelines, and dataset-building scripts that do not use an MCP client.

**Stories**: [Epic 8: Batch Proof Replay CLI](../requirements/stories/proof-interaction-protocol.md#epic-8-batch-proof-replay-cli)

---

## Problem

The proof interaction tools (open session, step forward, extract trace, get premises) are currently accessible only through the MCP server, which requires Claude Code or another MCP client. Terminal users, CI pipelines, and dataset-building scripts have no way to extract proof traces without that intermediary.

## Solution

A `replay-proof` CLI subcommand that opens a proof session, walks the entire proof non-interactively, outputs the trace (and optionally premise annotations), then cleans up. One command, one proof, complete output.

```
wily-rooster replay-proof <file_path> <proof_name> [--json] [--premises]
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
