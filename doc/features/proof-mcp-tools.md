# Proof Interaction MCP Tools

The set of MCP tools that expose proof interaction capabilities through the existing MCP server, alongside the [search tools](mcp-tool-surface.md) from Phase 1.

---

## Combined Server

Proof interaction tools are added to the same MCP server that hosts the search tools. A single server process, a single stdio transport connection, a single Claude Code configuration entry. Users do not need to manage a separate server for proof interaction.

This means the server exposes two tool families:
- **Search tools** (7 tools from Phase 1): `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules`
- **Proof interaction tools** (Phase 2): session management, state observation, tactic submission, premise extraction, trace retrieval

## Proof Interaction Tools

### Session Management

| Tool | Purpose |
|------|---------|
| `open_proof_session` | Start a session on a .v file and named proof; returns session ID and initial state |
| `close_proof_session` | Terminate a session and release resources |
| `list_proof_sessions` | Enumerate active sessions with metadata |

### State Observation

| Tool | Purpose |
|------|---------|
| `observe_proof_state` | Get the current proof state (goals, hypotheses, step index) |
| `get_proof_state_at_step` | Get proof state at step k in a completed proof |
| `extract_proof_trace` | Get the full proof trace (all states + tactics) in one call |

### Tactic Interaction

| Tool | Purpose |
|------|---------|
| `submit_tactic` | Submit a tactic and receive the resulting state or error |
| `step_backward` | Undo the last tactic |
| `step_forward` | Replay the next tactic from the original proof script |

### Premise Extraction

| Tool | Purpose |
|------|---------|
| `get_proof_premises` | Get premise annotations for all steps of a completed proof |
| `get_step_premises` | Get premise annotations for a single tactic step |

## Proof State Response Format

All tools that return proof state use a consistent schema:

**ProofState** — the top-level response for any proof state observation:
- Schema version
- Session ID
- Step index (0 = initial state)
- Focused goal index
- List of Goal objects

**Goal** — a single proof obligation:
- Goal index
- Goal type (as a Coq expression string)
- List of Hypothesis objects

**Hypothesis** — a named assumption in the proof context:
- Name
- Type (as a Coq expression string)
- Body (optional, for let-bound hypotheses)

This schema is shared across all tools that return proof state — `open_proof_session`, `observe_proof_state`, `submit_tactic`, `step_backward`, `step_forward`, `get_proof_state_at_step`, and within `extract_proof_trace` entries.

## Error Responses

All proof interaction tools return structured errors:

| Condition | Behavior |
|-----------|----------|
| File not found | Structured error with file path |
| Proof not found in file | Structured error with proof name and file path |
| Session ID not found or expired | Structured error indicating session is no longer active |
| Tactic fails in Coq | Structured error with Coq error message; proof state unchanged |
| Step index out of range | Structured error with valid range |
| Backend process crashed | Structured error indicating the session's backend is unavailable |

## Design Rationale

### Why add to the existing server rather than a second server

Multiple MCP servers create configuration overhead for users, increase context window consumption (duplicate capability descriptions), and prevent the LLM from combining search and proof interaction in a single reasoning turn. A combined server is simpler for users and more capable for the LLM.

### Why this many tools

The proof interaction domain has more distinct operations than search. Unlike search (where all tools share a "query in, results out" pattern), proof interaction has fundamentally different operation types: session lifecycle, state observation, tactic execution, and premise extraction. Collapsing these into fewer tools would require complex mode parameters that obscure what each tool does.

With 7 search tools + ~11 proof interaction tools, the server approaches ~18 tools total. This is within the research-supported range of 20–30 tools before accuracy degrades (see [MCP tool surface rationale](mcp-tool-surface.md#why-7-tools-is-near-the-upper-bound)). If future phases push beyond this range, dynamic tool loading should be considered.

### Why consistent ProofState schema across all tools

A tool builder or AI researcher should be able to write one ProofState parser and use it everywhere. Schema consistency eliminates a class of integration bugs where different tools return subtly different state representations.

## Acceptance Criteria

### MCP Server with Proof Interaction Tools

**Priority:** P0
**Stability:** Stable

- GIVEN a valid MCP configuration WHEN the server starts via stdio transport THEN it exposes all search tools and all proof interaction tools
- GIVEN a connected server WHEN the tool list is requested THEN proof interaction tools include at minimum: open-session, close-session, list-sessions, observe-state, submit-tactic, step-backward, step-forward, extract-trace, get-premises
- GIVEN a connected server WHEN any proof interaction tool is called THEN it returns well-formed MCP tool responses

### Proof State Response Format

**Priority:** P0
**Stability:** Stable

- GIVEN any tool that returns proof state WHEN the response is inspected THEN it uses the ProofState schema containing: schema version, session ID, step index, focused goal index, and a list of Goal objects
- GIVEN a Goal object WHEN it is inspected THEN it contains: goal index, goal type (as a string), and a list of Hypothesis objects
- GIVEN a Hypothesis object WHEN it is inspected THEN it contains: name, type (as a string), and optionally a body (for let-bound hypotheses)

### Coq Backend Errors

**Priority:** P0
**Stability:** Stable

- GIVEN a tactic that fails in Coq WHEN the error is returned THEN the MCP response includes a structured error object with the Coq error message, error location (if available), and the unchanged proof state
- GIVEN a file that fails to load WHEN the error is returned THEN the response includes a structured error with the Coq error message
