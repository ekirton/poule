# Diagram File Output

Self-contained HTML file output for proof visualization diagrams — visualization tools write a file the user opens in their browser.

---

## Problem

Poule's visualization tools generate Mermaid diagram syntax — text that describes a diagram. In Claude Code's terminal interface, this text is returned to the LLM, which can display it as raw text. But the whole point of visualization is to *see* a rendered graphic. The user needs a visual channel alongside the terminal.

## Solution

Visualization tools write a self-contained HTML file (`proof-diagram.html`) to the project directory as a side effect of each call. The user opens this file in their browser to see the rendered diagram. Since the project directory is bind-mounted at the same host path, the file is directly accessible from the host machine.

The user experience is:
1. Work with Claude: "Visualize the proof tree for `app_nil_r`"
2. Open `proof-diagram.html` in a browser (bookmark it once)
3. Diagram is visible — refresh the browser tab after each new visualization call

The tools still return Mermaid text to Claude Code as before. The HTML file replaces the previous SSE-based live diagram viewer, which has been removed.

## Design Rationale

### Why file output rather than an SSE viewer

A static HTML file works across container boundaries via bind mounts with no server connection needed. It handles multi-diagram sequences naturally (all diagrams in one scrollable page). There is no connection state to manage, no reconnection logic, and no port mapping beyond what MCP already requires.

### Why a single overwritten file

Avoids clutter in the project directory. The user bookmarks the file once. Each visualization call produces fresh content. There is no need for diagram history — the user re-runs the visualization tool to regenerate.

### Why mermaid.js from CDN

No bundling needed, browser caches it after the first load, and the Docker image stays lean. The HTML file remains self-contained (no local assets to manage).

## Scope Boundaries

Provides: self-contained HTML file with CDN mermaid.js, dark theme, multi-diagram support with step labels, client-side `mermaid.render()`.

Does **not** provide: persistent diagram history, image export (PNG/SVG), interactive features (pan, zoom, collapse), offline mermaid.js (CDN required on first load).

## Acceptance Criteria

### Write Rendered Diagram to Project Directory

**Priority:** P1
**Stability:** Stable

- GIVEN a call to `visualize_proof_tree` WHEN the tool returns THEN a file `proof-diagram.html` exists in the project directory containing valid HTML that renders the Mermaid diagram in a browser
- GIVEN the HTML file is opened in a browser without network access to the container THEN the diagram renders (mermaid.js loaded from CDN, no SSE/server dependency)

**Traces to:** R4-P1-6

### Multi-Diagram Sequence in Single File

**Priority:** P1
**Stability:** Stable

- GIVEN a proof trace with 6 tactic steps WHEN `visualize_proof_sequence` is called THEN the HTML file contains 7 rendered diagrams (initial + 6 steps) with step labels
- GIVEN the HTML file WHEN opened in a browser THEN all diagrams render in order with their tactic labels visible

**Traces to:** R4-P1-6, R4-P1-1

### Overwrite on Subsequent Calls

**Priority:** P1
**Stability:** Stable

- GIVEN a previous `proof-diagram.html` exists WHEN a new visualization tool is called THEN the file is overwritten with the new diagram

**Traces to:** R4-P1-6
