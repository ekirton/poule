# Vernacular Introspection

The component that dispatches Coq vernacular introspection commands through a single MCP tool, executing them against either an active proof session or a standalone Coq process.

**Feature**: [Vernacular Introspection](../features/vernacular-introspection.md)

---

## Component Diagram

```
MCP Server
  │
  │ coq_query(command, argument, session_id?)
  ▼
┌──────────────────────────────────────────────────────────┐
│              Vernacular Query Handler                      │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Command Dispatcher                                  │  │
│  │                                                     │  │
│  │  command ∈ {Print, Check, About, Locate, Search,    │  │
│  │            Compute, Eval}                           │  │
│  │                                                     │  │
│  │  Maps (command, argument) → Coq vernacular string   │  │
│  └────────────────────┬────────────────────────────────┘  │
│                       │                                    │
│            ┌──────────┴──────────┐                         │
│            │                     │                         │
│      session_id provided   no session_id                   │
│            │                     │                         │
│            ▼                     ▼                         │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │ Proof Session     │  │ Standalone Coq   │               │
│  │ Manager           │  │ Process          │               │
│  │ (execute in       │  │ (short-lived,    │               │
│  │  session context) │  │  global env only)│               │
│  └──────────────────┘  └──────────────────┘               │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Output Parser                                       │  │
│  │                                                     │  │
│  │  Raw Coq output → QueryResult                       │  │
│  └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Tool Signature

```typescript
coq_query(
  command: "Print" | "Check" | "About" | "Locate" | "Search" | "Compute" | "Eval",
  argument: string,       // command-specific argument (name, expression, pattern)
  session_id?: string     // if provided, execute in this session's context
) → QueryResult
```

The `argument` field carries the full text that follows the command keyword in a Coq toplevel. For `Eval`, this includes the reduction strategy prefix (e.g., `"cbv in 1 + 1"`). For `Print`, the optional `Assumptions` modifier is passed as part of the argument (e.g., `"Assumptions my_lemma"`).

## Command Dispatch

The Command Dispatcher maps each `(command, argument)` pair to a Coq vernacular command string for execution.

| `command` | Coq vernacular string | Notes |
|-----------|----------------------|-------|
| `Print` | `Print {argument}.` | If argument starts with `Assumptions`, emits `Print Assumptions {name}.` |
| `Check` | `Check {argument}.` | Argument may be a name or an arbitrary Coq expression |
| `About` | `About {argument}.` | |
| `Locate` | `Locate {argument}.` | Argument may be a name or a notation string in quotes |
| `Search` | `Search {argument}.` | Argument follows Coq `Search` syntax (patterns, constraints, scope qualifiers) |
| `Compute` | `Compute {argument}.` | |
| `Eval` | `Eval {argument}.` | Argument must include strategy: e.g., `cbv in expr`, `unfold foo in expr` |

The dispatcher appends the terminating period if absent. No further parsing or validation of the argument is performed by the handler — Coq itself validates the command and returns errors for malformed input.

## Session-Aware vs Session-Free Execution

The `session_id` parameter determines the execution context:

**When `session_id` is provided:**

1. The handler resolves the session via the Proof Session Manager's session registry.
2. The vernacular command string is submitted to the session's Coq backend process.
3. The command executes in the session's full context: loaded files, imported modules, and the current proof state including local hypotheses and let-bindings.
4. The session's proof state is not modified — introspection commands are read-only.

**When `session_id` is omitted:**

1. The handler spawns a short-lived Coq process (or reuses a pooled idle process).
2. The command executes against the default global environment (standard library and any project-level imports configured for the MCP server).
3. The process is released (returned to pool or terminated) after the command completes.

Session-aware execution is the primary mode during proof development. Session-free execution serves standalone queries outside any proof context (e.g., looking up a type signature before starting work).

## Response Type

```typescript
QueryResult = {
  command: string,        // the command that was executed (e.g., "Print", "Check")
  argument: string,       // the argument as provided by the caller
  output: string,         // the Coq output, structured for LLM consumption
  warnings: string[]      // any Coq warnings emitted during execution (may be empty)
}
```

The response is returned as an MCP content block:

```json
{
  "content": [{"type": "text", "text": "<JSON-encoded QueryResult>"}],
  "isError": false
}
```

## Output Parsing

The Output Parser transforms raw Coq output into the `output` field of `QueryResult`. The goals are readability for an LLM consumer and faithful preservation of Coq's output.

1. **Whitespace normalization**: Collapse runs of blank lines to a single blank line. Trim leading and trailing whitespace.
2. **Warning extraction**: Lines matching Coq warning patterns are removed from the main output and collected into the `warnings` array.
3. **Search result truncation**: For `Search` commands, if the result set exceeds a configurable limit (default: 50 entries), the output is truncated and a trailing line is appended: `(... truncated, {total} results total)`. This prevents large result sets from consuming excessive context window tokens.
4. **No semantic restructuring**: The output is not reformatted into a different structure (e.g., JSON fields for each constructor of an inductive). Coq's own pretty-printing is preserved, since LLMs parse it reliably and any restructuring risks information loss.

## Error Handling

All errors use the MCP standard error format (see [mcp-server.md](mcp-server.md) § Error Contract).

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Unrecognized `command` value | `INVALID_COMMAND` | Unknown command `{command}`. Valid commands: Print, Check, About, Locate, Search, Compute, Eval. |
| Empty `argument` | `INVALID_ARGUMENT` | Argument must not be empty. |
| Name not found (Print, Check, About, Locate) | `NOT_FOUND` | `{name}` not found in the current environment. |
| Ill-typed expression (Check, Compute, Eval) | `TYPE_ERROR` | Type error: `{coq_error_message}` |
| Malformed command syntax | `PARSE_ERROR` | Failed to parse: `{coq_error_message}` |
| Invalid reduction strategy (Eval) | `INVALID_STRATEGY` | Unknown reduction strategy. Valid strategies: cbv, lazy, cbn, simpl, hnf, unfold. |
| Computation timeout (Compute, Eval) | `TIMEOUT` | Computation exceeded time limit. |
| Session not found (when session_id provided) | `SESSION_NOT_FOUND` | Proof session `{session_id}` not found or has expired. |
| Backend crash (session or standalone) | `BACKEND_CRASHED` | The Coq backend has crashed. |
| Search returned no results | (normal response) | `QueryResult` with `output` indicating no matches; not an error. |

Error classification is performed by pattern-matching on Coq's error output. When an error does not match a known pattern, it is returned as `PARSE_ERROR` with the raw Coq error message preserved in the message field.

## Design Rationale

### Single tool with command parameter

Seven separate MCP tools (one per vernacular command) would inflate the tool count and consume context window tokens for seven nearly identical schemas. Because all seven commands share the same shape — a command name, a textual argument, and textual output — a single `coq_query` tool with a `command` enum parameter is equivalent in expressiveness while occupying one tool slot. The command enum makes tool selection unambiguous for the LLM.

### Session awareness

Introspection commands are most valuable during proof development, where the local proof context (hypotheses, let-bindings, partially applied terms) is essential for accurate results. Routing queries through an existing proof session avoids the cost of reconstructing context and ensures `Check`, `Compute`, and `Eval` see the same environment the developer is working in. The fallback to a standalone process ensures the tool remains useful outside proof sessions.

### Output structuring

Coq's built-in pretty-printer produces output that LLMs read reliably. Restructuring the output (e.g., parsing inductive types into JSON fields) would add complexity and risk information loss without a clear benefit for the LLM consumer. The minimal transformations — whitespace normalization, warning extraction, and search truncation — address the practical concerns (token budget, signal extraction) without altering the content.

### Argument pass-through

The `argument` field is passed to Coq verbatim (after command prefixing and period termination). This avoids the handler needing to understand Coq syntax for each command variant. Coq itself validates the input and produces error messages that the handler classifies and returns. This keeps the handler thin and avoids duplicating Coq's parser.
