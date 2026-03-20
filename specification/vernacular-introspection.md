# Vernacular Introspection

Single MCP tool dispatching Coq vernacular introspection commands (Print, Check, About, Locate, Search, Compute, Eval) to either an active proof session or a standalone Coq process, returning structured query results.

**Architecture**: [vernacular-introspection.md](../doc/architecture/vernacular-introspection.md), [mcp-server.md](../doc/architecture/mcp-server.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the vernacular query handler that, given a command name and argument, constructs a Coq vernacular string, dispatches it to the appropriate backend (proof session or standalone process), parses the output, and returns a structured `QueryResult` through the MCP server.

## 2. Scope

**In scope**: Command dispatch (7 commands), vernacular string construction, session-aware vs session-free routing, output parsing (whitespace normalization, warning extraction, search truncation), error classification, response formatting.

**Out of scope**: MCP protocol handling (owned by mcp-server), session lifecycle management (owned by proof-session), standalone process pool management (owned by coq-proof-backend), proof state mutation (introspection commands are read-only).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Vernacular command | A Coq toplevel command that queries the environment without modifying it |
| Command dispatcher | The mapping from `(command, argument)` to a Coq vernacular string |
| Session-aware execution | Execution within an existing proof session's import context (loaded files, imported modules) via a coqtop subprocess; local proof state (hypotheses, let-bindings) is not available |
| Session-free execution | Execution against a short-lived or pooled Coq process with only the default global environment |
| Query result | The structured response containing the command echo, argument echo, parsed output, and extracted warnings |
| Output parser | The transformation from raw Coq output to the `output` and `warnings` fields of `QueryResult` |
| Prelude | A configurable sequence of Coq vernacular commands executed before each session-free query to establish the default global environment. Configurable at server startup; default: `From Coq Require Import Arith.` |
| Search truncation limit | The maximum number of result entries returned for `Search` commands before truncation (default: 50) |

## 4. Behavioral Requirements

### 4.1 Tool Entry Point

#### coq_query(command, argument, session_id?)

- REQUIRES: `command` is one of `"Print"`, `"Check"`, `"About"`, `"Locate"`, `"Search"`, `"Compute"`, `"Eval"`. `argument` is a non-empty string. `session_id`, when provided, references an active proof session.
- ENSURES: Constructs a Coq vernacular string from `command` and `argument`. Dispatches the string to the backend determined by `session_id`. Parses the output. Returns a `QueryResult` wrapped in an MCP content block with `isError: false`.
- MAINTAINS: The proof session state is not modified by any introspection command. Session-aware execution is read-only with respect to proof state.

> **Given** `command = "Check"`, `argument = "Nat.add_comm"`, and no `session_id`
> **When** `coq_query` is called
> **Then** the handler sends `Check Nat.add_comm.` to a standalone Coq process and returns a `QueryResult` with `output` containing the type of `Nat.add_comm`

> **Given** `command = "Print"`, `argument = "nat"`, and `session_id = "abc123"` referencing an active session
> **When** `coq_query` is called
> **Then** the handler sends `Print nat.` to the session's coqtop subprocess and returns a `QueryResult` with `output` containing the inductive definition of `nat`

> **Given** `command = "Eval"`, `argument = "cbv in 1 + 1"`, and no `session_id`
> **When** `coq_query` is called
> **Then** the handler sends `Eval cbv in 1 + 1.` to a standalone Coq process and returns a `QueryResult` with `output` containing `= 2 : nat`

### 4.2 Command Dispatch

The command dispatcher shall map each `(command, argument)` pair to a Coq vernacular string.

| `command` | Vernacular string | Notes |
|-----------|-------------------|-------|
| `Print` | `Print {argument}.` | When argument starts with `Assumptions`, emits `Print Assumptions {rest}.` |
| `Check` | `Check {argument}.` | Argument may be a name or an arbitrary Coq expression |
| `About` | `About {argument}.` | |
| `Locate` | `Locate {argument}.` | Argument may be a name or a notation string in double quotes |
| `Search` | `Search {argument}.` | Argument follows Coq `Search` syntax (patterns, constraints, scope qualifiers) |
| `Compute` | `Compute {argument}.` | |
| `Eval` | `Eval {argument}.` | Argument must include reduction strategy (e.g., `cbv in expr`) |

- REQUIRES: `command` is a valid command enum value. `argument` is a non-empty string.
- ENSURES: The dispatcher appends a terminating period if the argument does not already end with one. No further parsing or validation of the argument is performed — Coq validates the command and returns errors for malformed input.
- MAINTAINS: The argument text is passed verbatim to Coq after command prefixing and period termination. No escaping, quoting, or rewriting is applied.

> **Given** `command = "Print"`, `argument = "Assumptions my_lemma"`
> **When** the dispatcher constructs the vernacular string
> **Then** the result is `Print Assumptions my_lemma.`

> **Given** `command = "Check"`, `argument = "fun x => x + 1."`
> **When** the dispatcher constructs the vernacular string
> **Then** the result is `Check fun x => x + 1.` (no duplicate period)

### 4.3 Execution Routing

The `session_id` parameter determines the execution backend.

#### Session-aware execution (session_id provided)

1. The handler shall resolve the session via the Proof Session Manager's session registry.
2. The handler shall submit the vernacular command string to the session via `submit_command`. The session manager routes this through a coqtop subprocess (not the session's coq-lsp backend), because coq-lsp's LSP protocol does not expose vernacular command output. See [proof-session.md](proof-session.md) §4.4.1.
3. The command shall execute in the session's import context: loaded files and imported modules. Local proof hypotheses and let-bindings from the coq-lsp proof state are not available in the coqtop subprocess.

- MAINTAINS: The session's proof state (managed by the CoqBackend) is not modified. The coqtop subprocess environment may be modified by side-effecting commands, but this does not affect the proof state.

> **Given** a proof session with `Require Import Arith.` in the file preamble and `command = "Check"`, `argument = "Nat.add_comm"`
> **When** `coq_query` executes in session context
> **Then** the output contains the type of `Nat.add_comm` (i.e., `forall n m : nat, n + m = m + n`)

#### Session-free execution (session_id omitted)

1. The handler shall obtain a Coq process (spawned or drawn from a pool).
2. The standalone process shall inherit the server process's environment variables, including `PATH` and `COQPATH`. This makes opam-installed Coq packages reachable via `Require Import` without explicit `-R` / `-Q` flags.
3. Before executing the user's command, the process shall execute a configurable **prelude** — a sequence of Coq vernacular commands (typically `Require Import` statements) that establish the default global environment.
4. The prelude shall be configurable at server startup. When no prelude is configured, the default prelude loads the Coq standard library arithmetic module: `From Coq Require Import Arith.`
5. The command shall execute after the prelude completes. The process shall be released (returned to pool or terminated) after the command completes.

- REQUIRES: The prelude is a valid sequence of Coq vernacular commands that terminates without error.
- ENSURES: The user's command executes in an environment where (a) all prelude imports are available and (b) all opam-installed Coq packages are reachable via `Require Import` through the inherited `COQPATH`.
- MAINTAINS: Each session-free invocation starts from a clean environment (prelude + command only). No state persists between invocations.

> **Given** no `session_id` and `command = "Locate"`, `argument = "Nat.add"`
> **When** `coq_query` executes session-free
> **Then** the output contains the module path of `Nat.add` from the standard library

> **Given** no `session_id`, MathComp is opam-installed, and `command = "Print"`, `argument = "leq"`
> **When** `coq_query` executes session-free with prelude `From Coq Require Import Arith. From mathcomp Require Import all_ssreflect.`
> **Then** the output contains MathComp's definition of `leq`

### 4.4 Output Parsing

The output parser shall transform raw Coq output into the `output` and `warnings` fields of `QueryResult`.

| Step | Transformation | Detail |
|------|---------------|--------|
| 1 | Whitespace normalization | Collapse runs of blank lines to a single blank line. Trim leading and trailing whitespace. |
| 2 | Warning extraction | Lines matching Coq warning patterns are removed from `output` and collected into the `warnings` array. |
| 3 | Search truncation | For `Search` commands, when the result set exceeds the search truncation limit (default: 50 entries), truncate and append `(... truncated, {total} results total)`. |
| 4 | No semantic restructuring | Coq's pretty-printed output is preserved verbatim after steps 1–3. No reformatting into alternative structures. |

- REQUIRES: Raw Coq output is a string (may be empty for errors handled separately).
- ENSURES: `output` contains the transformed text. `warnings` contains zero or more extracted warning strings. The order of non-warning output lines is preserved.
- MAINTAINS: No information loss beyond the specified transformations. Coq's own formatting is the authoritative representation.

> **Given** raw Coq output containing `Warning: Notation "_ + _" was already used.` followed by `nat : Set`
> **When** the output parser runs
> **Then** `output` is `nat : Set` and `warnings` contains `Notation "_ + _" was already used.`

> **Given** a `Search` command returning 120 result entries
> **When** the output parser runs
> **Then** `output` contains the first 50 entries followed by `(... truncated, 120 results total)`

## 5. Data Model

### QueryResult

| Field | Type | Constraints |
|-------|------|-------------|
| `command` | string | Required; one of `Print`, `Check`, `About`, `Locate`, `Search`, `Compute`, `Eval` |
| `argument` | string | Required; the argument as provided by the caller |
| `output` | string | Required; parsed Coq output after whitespace normalization, warning extraction, and search truncation |
| `warnings` | ordered list of string | Required; may be empty; Coq warnings extracted during output parsing |

### MCP Response Envelope

Success responses use the standard MCP content block:

```json
{
  "content": [{"type": "text", "text": "<JSON-encoded QueryResult>"}],
  "isError": false
}
```

Error responses use the standard MCP error format:

```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"...\", \"message\": \"...\"}}"}],
  "isError": true
}
```

## 6. Interface Contracts

### Vernacular Query Handler → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `submit_command` — routes through the session's coqtop subprocess (not the CoqBackend); see [proof-session.md](proof-session.md) §4.4.1 |
| Concurrency | Serialized — one command at a time per session |
| Error strategy | `SESSION_NOT_FOUND` → return error to caller. `BACKEND_CRASHED` → return error to caller. |
| Idempotency | Introspection commands are idempotent; re-executing the same command produces the same output given the same session state. |

### Vernacular Query Handler → Standalone Coq Process

| Property | Value |
|----------|-------|
| Operations used | Send vernacular command string, receive output |
| Concurrency | Each invocation uses one process; no shared state between invocations |
| Error strategy | `BACKEND_CRASHED` → return error to caller. `TIMEOUT` → return error to caller. |
| Lifecycle | Process acquired before command execution, released after output is received |

### MCP Server → Vernacular Query Handler

| Property | Value |
|----------|-------|
| Operations used | `coq_query(command, argument, session_id?)` |
| Input validation | MCP server validates `command` enum membership and `argument` non-emptiness before delegation |
| Output | `QueryResult` on success; structured error on failure |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Error Code | Message |
|-----------|-----------|---------|
| `command` not in valid enum | `INVALID_COMMAND` | `Unknown command "{command}". Valid commands: Print, Check, About, Locate, Search, Compute, Eval.` |
| `argument` is empty string | `INVALID_ARGUMENT` | `Argument must not be empty.` |

### 7.2 Session Errors

| Condition | Error Code | Message |
|-----------|-----------|---------|
| `session_id` provided but session not found or expired | `SESSION_NOT_FOUND` | `Proof session "{session_id}" not found or has expired.` |

### 7.3 Coq Execution Errors

Error classification is performed by pattern-matching on Coq's error output. When an error does not match a known pattern, it is returned as `PARSE_ERROR` with the raw Coq error message preserved.

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Name not found (Print, Check, About, Locate) | `NOT_FOUND` | `"{name}" not found in the current environment.` |
| Ill-typed expression (Check, Compute, Eval) | `TYPE_ERROR` | `Type error: {coq_error_message}` |
| Malformed command syntax | `PARSE_ERROR` | `Failed to parse: {coq_error_message}` |
| Invalid reduction strategy (Eval) | `INVALID_STRATEGY` | `Unknown reduction strategy. Valid strategies: cbv, lazy, cbn, simpl, hnf, unfold.` |
| Computation timeout (Compute, Eval) | `TIMEOUT` | `Computation exceeded time limit.` |
| Unclassified Coq error | `PARSE_ERROR` | `Failed to parse: {raw_coq_error_message}` |

### 7.4 Backend Errors

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Coq backend process crashes (session or standalone) | `BACKEND_CRASHED` | `The Coq backend has crashed.` |

### 7.5 Non-Error Conditions

| Condition | Behavior |
|-----------|----------|
| `Search` returns no results | Normal `QueryResult` with `output` indicating no matches; not an error |

## 8. Non-Functional Requirements

- Command dispatch (vernacular string construction) shall complete in < 1 ms.
- Output parsing shall complete in < 10 ms for outputs up to 100 KB.
- The handler shall not buffer more than 1 MB of Coq output per invocation; outputs exceeding this limit shall be truncated with a trailing notice.
- The search truncation limit shall be configurable at server startup (default: 50).

## 9. Examples

### Session-free Check

```
coq_query(command="Check", argument="Nat.add_comm")

Vernacular: Check Nat.add_comm.
Backend: standalone Coq process

Response:
{
  "content": [{"type": "text", "text": "{\"command\": \"Check\", \"argument\": \"Nat.add_comm\", \"output\": \"Nat.add_comm\\n     : forall n m : nat, n + m = m + n\", \"warnings\": []}"}],
  "isError": false
}
```

### Session-aware Print with warnings

```
coq_query(command="Print", argument="nat", session_id="abc123")

Vernacular: Print nat.
Backend: session abc123 (coqtop subprocess)

Response:
{
  "content": [{"type": "text", "text": "{\"command\": \"Print\", \"argument\": \"nat\", \"output\": \"Inductive nat : Set :=  O : nat | S : nat -> nat.\", \"warnings\": []}"}],
  "isError": false
}
```

### Error — name not found

```
coq_query(command="About", argument="nonexistent_lemma")

Vernacular: About nonexistent_lemma.
Backend: standalone Coq process

Response:
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"NOT_FOUND\", \"message\": \"\\\"nonexistent_lemma\\\" not found in the current environment.\"}}"}],
  "isError": true
}
```

### Search with truncation

```
coq_query(command="Search", argument="(_ + _ = _ + _)")

Vernacular: Search (_ + _ = _ + _).
Backend: standalone Coq process
Raw output: 120 matching entries

Response:
{
  "content": [{"type": "text", "text": "{\"command\": \"Search\", \"argument\": \"(_ + _ = _ + _)\", \"output\": \"Nat.add_comm: forall n m : nat, ...\\n... (first 50 entries) ...\\n(... truncated, 120 results total)\", \"warnings\": []}"}],
  "isError": false
}
```

### Eval with reduction strategy

```
coq_query(command="Eval", argument="cbv in 2 + 3", session_id="def456")

Vernacular: Eval cbv in 2 + 3.
Backend: session def456 (coqtop subprocess)

Response:
{
  "content": [{"type": "text", "text": "{\"command\": \"Eval\", \"argument\": \"cbv in 2 + 3\", \"output\": \"= 5\\n     : nat\", \"warnings\": []}"}],
  "isError": false
}
```

## 10. Language-Specific Notes (Python)

- Package location: `src/poule/query/`.
- Entry point: `async def coq_query(command: str, argument: str, session_id: str | None = None, session_manager=None, process_pool=None) -> QueryResult`.
- Use an `enum.StrEnum` for the `command` parameter with values matching the 7 valid commands.
- Command dispatch: a `dict[str, Callable[[str], str]]` mapping command names to vernacular string constructors.
- Output parsing: a standalone `parse_output(raw: str, command: str, truncation_limit: int = 50) -> tuple[str, list[str]]` function returning `(output, warnings)`.
- Warning detection: compile Coq warning regex patterns once at module load time.
- Error classification: a `classify_error(raw: str) -> tuple[str, str]` function returning `(error_code, message)`, using compiled regex patterns.
- Use the `anthropic` Python SDK's MCP server utilities for response envelope construction.
- Timeout for `Compute` and `Eval`: enforce via `asyncio.wait_for` on the backend call (default: 30 seconds, configurable).
- The standalone process pool accepts a `prelude` string parameter at construction time (default: `"From Coq Require Import Arith.\n"`). The MCP server passes this from its startup configuration.
