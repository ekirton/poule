# Proof Search MCP Tools

The MCP tools that expose proof search and fill-admits capabilities through the existing MCP server, alongside the [search tools](mcp-tool-surface.md) from Phase 1 and [proof interaction tools](proof-mcp-tools.md) from Phase 2.

---

## Combined Server

Proof search tools are added to the same MCP server that hosts the search and proof interaction tools. A single server process, a single stdio transport connection, a single Claude Code configuration entry.

This means the server now exposes three tool families:

- **Search tools** (7 tools from Phase 1): `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules`
- **Proof interaction tools** (~11 tools from Phase 2): session management, state observation, tactic submission, premise extraction, trace retrieval
- **Proof search tools** (Phase 4): automated proof search and fill-admits

## Proof Search Tools

| Tool | Purpose |
|------|---------|
| `proof_search` | Run best-first proof search on the current goal in a proof session; returns verified proof script or structured failure |
| `fill_admits` | Scan a proof script file for `admit` calls, invoke proof search on each, and return the script with filled admits |

## Tool Parameters

### proof_search

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| session_id | Yes | — | Active proof session ID |
| timeout | No | 30 | Wall-clock time limit in seconds |
| max_depth | No | 10 | Maximum tactic sequence length |
| max_breadth | No | 20 | Maximum candidates expanded per node |

### fill_admits

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| file_path | Yes | — | Path to the .v file containing admits |
| timeout_per_admit | No | 30 | Wall-clock time limit per admit in seconds |
| max_depth | No | 10 | Maximum tactic sequence length per admit |
| max_breadth | No | 20 | Maximum candidates per node per admit |

## Response Formats

### proof_search — success

- Status: `"success"`
- Proof script: ordered list of tactics
- Per-step proof states: proof state after each tactic
- Stats: states explored, unique states, wall-clock time

### proof_search — failure

- Status: `"failure"`
- Best partial proof: deepest tactic sequence that made progress
- Frontier: open proof states at termination
- Stats: states explored, unique states, wall-clock time

### fill_admits — result

- Total admits found
- Admits filled (count and list with replacement tactic sequences)
- Admits unfilled (count and list with failure information from proof search)
- Modified script content (with filled admits replaced)

## Error Responses

| Condition | Behavior |
|-----------|----------|
| Session ID not found or expired | Structured error indicating session is no longer active |
| File not found (fill_admits) | Structured error with file path |
| No admits found in file (fill_admits) | Success response with zero admits found |
| Search timeout | Normal failure response (not an error) with partial results |

## Tool Count

With 2 new tools, the server reaches ~20 tools total (7 search + 11 proof interaction + 2 proof search). This is at the edge of the research-supported range of 20–30 tools before accuracy degrades. If future phases add more tools, dynamic tool loading should be considered — see the [tool surface rationale](mcp-tool-surface.md#why-7-tools-is-near-the-upper-bound) for background.

The proof search tools have low risk of selection confusion because their names and purposes are distinct from existing tools: `proof_search` operates on a proof session (like proof interaction tools) but returns a complete proof (unlike `submit_tactic` which returns one step). `fill_admits` operates on a file path (unique among all tools).

## Design Rationale

### Why only 2 tools

Proof search and fill-admits are the two user-facing operations. Everything else — candidate generation, diversity filtering, state caching, solver interleaving — is internal to these tools. Exposing internal search mechanics as separate MCP tools would bloat the tool surface without benefit: Claude Code never needs to invoke "generate candidates" or "filter duplicates" independently. It invokes proof search, and the search handles the rest.

### Why proof_search requires a session

Proof search needs to submit tactics to Coq and observe results. It uses the existing proof session infrastructure from Phase 2 for this. Requiring a session ID means Claude Code must first open a session (positioning at the right proof and step), then invoke search — a two-step workflow that keeps the session lifecycle explicit and reusable. Claude can inspect the proof state before deciding whether search is worth attempting.

### Why fill_admits takes a file path, not a session

Fill-admits is a batch operation across an entire file, potentially touching multiple independent proofs. It manages its own sessions internally — one per admit — and cleans them up when done. Requiring the caller to open sessions for each admit would defeat the purpose of batch automation.

## Acceptance Criteria

### Proof Search MCP Tool

**Priority:** P0
**Stability:** Stable

- GIVEN a running MCP server WHEN the proof search tool is invoked with a proof session ID THEN it attempts to find a complete proof for the current proof state
- GIVEN the proof search tool WHEN it is invoked without a timeout parameter THEN the default timeout of 30 seconds is applied
- GIVEN the proof search tool WHEN it is invoked with a custom timeout THEN that timeout is respected
- GIVEN the MCP server WHEN its tool list is inspected THEN a proof search tool is present with a documented schema

**Traces to:** R4-P0-4, R4-P0-5

### Fill-Admits MCP Tool

**Priority:** P1
**Stability:** Stable

- GIVEN a running MCP server WHEN the fill-admits tool is invoked with a file path THEN it processes the file and returns results for each `admit`
- GIVEN the MCP server WHEN its tool list is inspected THEN a fill-admits tool is present with a documented schema

**Traces to:** R4-P1-6
