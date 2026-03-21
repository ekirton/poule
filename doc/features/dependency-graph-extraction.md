# Dependency Graph Extraction

Extract the theorem-level dependency graph from a Coq project: which theorems, definitions, and axioms each proof depends on.

---

## Problem

Premise selection is not just a per-step annotation problem — the global structure of which theorems depend on which definitions and lemmas encodes significant retrieval signal. Research on Graph2Tac and RGCN-based premise selection shows that graph structure provides 25–34% additional retrieval performance over flat premise lists. But Coq has no tool that extracts this dependency graph in a structured, ML-consumable format.

## Solution

For each project, extract a structured adjacency list of theorem-level dependencies. Each entry identifies a theorem and lists the theorems, definitions, and axioms its proof depends on, with fully qualified names. The graph is output in a structured format consistent with the extraction trace schema.

## Design Rationale

### Why theorem-level rather than term-level or file-level granularity

File-level granularity (file A depends on file B) is too coarse for ML — a file may contain hundreds of theorems with different dependency profiles. Term-level granularity (every subterm reference) is too fine and produces enormous graphs dominated by noise (constructors, notation, coercions). Theorem-level granularity — which theorems and definitions does this proof use — aligns with what premise selection models need to predict: given a goal, which existing results are relevant.

### Why P1 rather than P0

The dependency graph adds retrieval signal for graph-based premise selection models, but the core extraction pipeline delivers value without it. Per-step premise annotations (P0) capture which premises each tactic used; the dependency graph captures the global structure of how theorems relate. Initial datasets can be built and used for tactic prediction and basic premise selection without graph data. The graph becomes important when researchers build graph-neural-network-based models.

### Why adjacency list rather than edge list or matrix

Adjacency lists are compact for sparse graphs (theorem dependency graphs are sparse — most theorems depend on a small fraction of the library), human-readable, and easy to convert to other representations. Edge lists lose the grouping-by-source that makes the data navigable. Matrices are impractical for large libraries (50K+ nodes).

## Scope Boundaries

Dependency graph extraction provides:

- Theorem-level dependency adjacency lists with fully qualified names
- Structured output consistent with the extraction schema

It does **not** provide:

- Term-level or definition-level dependency tracking
- Cross-project dependency graphs (dependencies stay within a single project's scope)
- Graph visualization or rendering
- Dependency-aware change propagation for incremental extraction

## Acceptance Criteria

### Theorem Dependency Graph

**Priority:** P1
**Stability:** Stable

- GIVEN a Coq project WHEN dependency graph extraction is run THEN it produces a structured adjacency list of theorem-level dependencies
- GIVEN a dependency graph entry for theorem T WHEN it is inspected THEN it lists the theorems, definitions, and axioms that T's proof depends on, each with a fully qualified name
- GIVEN the dependency graph WHEN it is serialized THEN it uses a structured format consistent with the extraction output schema

**Traces to:** R3-P1-2
