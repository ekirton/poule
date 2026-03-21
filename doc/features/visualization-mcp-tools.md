# Visualization MCP Tools

The set of MCP tools that expose proof visualization capabilities through the existing MCP server, alongside the [search tools](mcp-tool-surface.md) and [proof interaction tools](proof-mcp-tools.md).

---

## Combined Server

Visualization tools are added to the same MCP server that hosts the search and proof interaction tools. A single server process, a single stdio transport connection, a single Claude Code configuration entry. Users do not need to manage a separate server for visualization.

This means the server exposes three tool families:
- **Search tools** (7 tools from Phase 1): `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules`
- **Proof interaction tools** (Phase 2): session management, state observation, tactic submission, premise extraction, trace retrieval
- **Visualization tools** (Phase 2): proof state diagrams, proof tree diagrams, dependency subgraph diagrams, proof sequence diagrams

## Visualization Tools

| Tool | Purpose |
|------|---------|
| `visualize_proof_state` | Render a proof state (goals, hypotheses, local context) as a Mermaid diagram |
| `visualize_proof_tree` | Render a completed proof trace as a Mermaid proof tree diagram |
| `visualize_dependencies` | Render a theorem's dependency subgraph as a Mermaid diagram |
| `visualize_proof_sequence` | Render a proof trace as a sequence of Mermaid diagrams showing step-by-step evolution |

All tools accept structured JSON input and return Mermaid diagram text as output. The returned Mermaid syntax is valid for rendering by the Mermaid Chart MCP service or any Mermaid-compatible renderer.

## Rendering Pipeline

Visualization tools generate Mermaid syntax and return it as text in the MCP response. Each visualization tool also writes a self-contained HTML file (`proof-diagram.html`) to the project directory as a side effect, rendering the diagram(s) via client-side mermaid.js. This file replaces the previous SSE-based live diagram viewer. See [Diagram File Output](diagram-file-output.md) for the file output feature.

This means:

- The visualization tools have no server-side rendering dependencies (no headless browser, no Puppeteer, no SSE viewer)
- Any MCP client that can display Mermaid gets visualization for free via the returned text
- The HTML file provides a visual rendering channel without requiring a running server or network connection to the container
- Diagram generation stays fast — it is string construction, not image rendering

## Design Rationale

### Why 4 visualization tools rather than 1

Each tool has a distinct input shape and output structure:
- `visualize_proof_state` takes a single proof state snapshot
- `visualize_proof_tree` takes a complete proof trace
- `visualize_dependencies` takes a theorem name and depth parameters
- `visualize_proof_sequence` takes a proof trace and returns multiple diagrams

A single `visualize` tool with a mode parameter would require the LLM to construct different input schemas depending on the mode — a pattern that increases error rates and obscures intent.

### Why these tools stay within the tool count budget

With 7 search tools + ~11 proof interaction tools + 4 visualization tools, the server reaches ~22 tools. This is at the lower end of the 20–30 tool range where research shows accuracy begins to degrade. If future phases push beyond this, dynamic tool loading should be considered. For now, the visualization tools earn their place because each represents a visually and semantically distinct operation that the LLM benefits from selecting explicitly.

### Why Mermaid rather than Graphviz, D2, or custom SVG

Mermaid has the widest rendering support across the environments where Coq developers work: GitHub Markdown, VS Code preview, Jupyter notebooks, and the Mermaid Chart MCP service already connected to this project. Graphviz produces better layouts for large graphs but requires a local installation and has no MCP rendering path. D2 is newer with less ecosystem support. Custom SVG would require a rendering engine in the server — the opposite of the "generate text, render elsewhere" principle.

### Why visualization tools consume proof interaction data rather than Coq directly

Visualization tools accept the same structured proof state and trace data that the proof interaction tools produce. This means a user can: open a session, step through a proof, then visualize any state they've observed — all within a single conversation. It also means visualization works on saved traces from the training data extraction pipeline, not just live sessions.

## Scope Boundaries

The visualization MCP tools provide:

- Mermaid diagram generation from structured proof data
- Tools integrated into the existing combined MCP server
- Structured JSON input, Mermaid text output

They do **not** provide:

- Image rendering (that is the Mermaid Chart MCP service's concern)
- A separate server or separate configuration
- Interactive diagram features (pan, zoom, collapse — these are client-side rendering concerns)
- Visualization of raw Coq source code or Gallina terms
