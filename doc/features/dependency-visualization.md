# Dependency Visualization

Visual diagrams of theorem dependency subgraphs — which lemmas, definitions, and axioms a proof depends on — rendered as Mermaid diagrams for understanding proof context and library structure.

---

## Problem

Before modifying a proof or refactoring a library module, a developer needs to understand the dependency context: what does this theorem rely on, and what relies on it? Coq's `Print Assumptions` command lists axioms but not the full dependency subgraph. coq-dpdgraph extracts full dependency graphs to Graphviz files, but produces whole-library graphs that are too large to be useful for inspecting a single theorem's neighborhood.

For educators, dependency diagrams answer: "what prior results does this theorem build on?" — a question central to teaching mathematical structure.

## Solution

A Mermaid diagram that renders the dependency subgraph rooted at a named theorem. Nodes are theorems, definitions, and axioms. Edges show "depends on" relationships. The diagram is scoped to a configurable depth, so users see the immediate neighborhood without drowning in the full transitive closure.

The diagram answers questions like: "What lemmas does this proof use?", "Does this proof depend on any axioms?", and "How deep is the dependency chain to foundational results?"

## Depth Limiting

Theorem dependency graphs can be deep — a MathComp result may transitively depend on hundreds of definitions and lemmas. Rendering the full transitive closure produces unreadable diagrams. Depth limiting controls how many hops from the root theorem are included:

- **Depth 1** — only direct dependencies. The most common view for understanding a single proof's immediate context.
- **Depth 2–3** — includes dependencies of dependencies. Useful for understanding a theorem's broader context within a library module.
- **Deeper** — available but likely to produce large diagrams. Suitable for analysis tasks, not quick inspection.

## Design Rationale

### Why dependency visualization is separate from the existing dependency graph extraction feature

The [dependency graph extraction](dependency-graph-extraction.md) feature (Phase 3, Training Data Extraction) produces structured adjacency lists for ML consumption — whole-project, batch-oriented, no rendering. Dependency visualization is interactive, scoped to a single theorem, and produces human-readable Mermaid diagrams. They share the same underlying data but serve different users (AI researchers vs. developers and educators) through different interfaces (batch CLI vs. MCP tool).

### Why depth-limited subgraphs rather than full project graphs

A full dependency graph for the Coq standard library has thousands of nodes. No diagram of that size is useful for human inspection. Depth limiting is not a compromise — it is the design. The user names a theorem and a depth, and gets a diagram sized for comprehension.

### Why Mermaid graph diagrams rather than force-directed layouts

Mermaid's flowchart/graph layout produces deterministic, reproducible diagrams — the same input always produces the same layout. Force-directed layouts (Graphviz `neato`, D3) can produce better layouts for large graphs but are non-deterministic without pinning, which complicates reproducibility. For depth-limited subgraphs (typically under 100 nodes), Mermaid's layout is sufficient and reproducible.

### Why axiom nodes deserve visual distinction

Axioms are qualitatively different from theorems and definitions — they are assumed, not proved. A proof that transitively depends on `Axiom Classical_Prop` has different epistemic status than one that does not. Making axioms visually distinct in the dependency diagram surfaces this information without requiring the user to inspect each node.

## Scope Boundaries

Dependency visualization provides:

- Mermaid diagrams of theorem dependency subgraphs
- Configurable depth limiting
- Visual distinction between theorems, definitions, and axioms
- Scoped to a single named theorem per diagram

It does **not** provide:

- Whole-project or whole-library dependency graphs (that is the batch extraction feature's domain)
- Cross-project dependency visualization
- Reverse dependency queries ("what depends on this theorem?") as diagrams — this may be a future extension
- Dependency-aware impact analysis for refactoring

## Acceptance Criteria

### Render Dependency Subgraph for a Theorem

**Priority:** P0
**Stability:** Stable

- GIVEN a theorem that depends on 5 lemmas, 2 definitions, and 1 axiom WHEN the dependency visualization MCP tool is called with the theorem name THEN it returns a Mermaid diagram showing all 8 dependencies with edges from the theorem to each dependency
- GIVEN a dependency that is itself a theorem with its own dependencies WHEN the diagram is rendered THEN transitive dependencies are included up to the configured depth
- GIVEN a theorem name WHEN the dependency tool is called THEN the input is a JSON object containing the theorem name and the output is Mermaid diagram text

**Traces to:** R4-P0-6, R4-P0-7

### Limit Dependency Graph Depth

**Priority:** P1
**Stability:** Stable

- GIVEN a theorem with transitive dependencies extending 10 levels deep WHEN the dependency tool is called with a depth limit of 3 THEN only dependencies within 3 hops of the target theorem are included
- GIVEN a dependency graph with 200 transitive nodes WHEN a depth limit of 2 is applied THEN the resulting diagram has no more than 100 nodes and renders readably

**Traces to:** R4-P1-4, R4-P1-5
