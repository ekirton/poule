# Deep Dependency Analysis

Transitive dependency analysis for Coq projects — full forward and reverse dependency closures, cycle detection, impact analysis, and module-level summaries — built on coq-dpdgraph and exposed as MCP tools. This extends Poule's existing `find_related` (direct dependency navigation) and `visualize_dependencies` (subgraph rendering) into a complete dependency intelligence layer that operates at project scale.

---

## Problem

Poule's `find_related` tool shows what a definition directly depends on — one hop in the dependency graph. `visualize_dependencies` renders a subgraph the user already knows to ask about. These tools are useful for local exploration, but they cannot answer the questions that matter most when working in large Coq developments: What is the full set of definitions this lemma ultimately rests on? If I change this definition, what breaks? Are there circular dependencies hiding in the project? Which modules are tightly coupled?

Answering these questions requires transitive analysis — walking the full dependency graph, not just immediate neighbors. In projects like CompCert, MathComp, or Iris, with thousands of interdependent definitions, manual inspection is impractical and ad-hoc scripts are fragile. Proof engineers planning a refactoring need to know the blast radius before they start. Library maintainers need to see architectural structure — cycles, coupling hotspots, module boundaries — to make informed decisions about modularization and technical debt.

## Solution

### Transitive Closure

Given any fully qualified definition, lemma, or theorem in a compiled Coq project, compute the complete set of definitions it transitively depends on. This is the forward closure: everything the target ultimately rests on, across all intermediate dependencies, no matter how many hops away. The result gives a proof engineer a complete picture of a definition's foundations — useful for understanding what assumptions a proof carries and what upstream changes could affect it.

When the full transitive closure is too large to be useful, depth-limited queries restrict the result to dependencies within a specified number of hops. A depth limit of one produces the same result as `find_related`, providing a smooth continuum from local exploration to full transitive analysis. Scope filters allow restricting results to a specific module or excluding the standard library, so engineers can focus on project-internal dependencies relevant to their current task.

### Impact Analysis

The reverse of transitive closure: given a definition, find everything that transitively depends on it. This answers the refactoring question directly — before changing a definition, a proof engineer sees every lemma, theorem, and downstream definition that would be affected. The result is the blast radius of the change.

Impact analysis turns what would otherwise be a risky, exploratory process (change something, see what breaks) into an informed decision. Engineers can assess whether a proposed change is safe, scope the downstream repair work, and choose the refactoring approach with the smallest impact.

### Cycle Detection

Dependency cycles in a Coq project — definitions that mutually depend on each other, directly or through intermediaries — create maintenance hazards and compilation complications. Cycle detection identifies every cycle in the project and reports each one as an ordered list of participants, making the circular structure explicit.

For projects with multiple overlapping cycles, each distinct cycle is reported separately. When no cycles exist, the tool confirms the project is cycle-free. This gives library maintainers a clear inventory of circular dependencies to address, rather than discovering them one at a time during compilation failures or refactoring attempts.

### Module-Level Summaries

Definition-level dependency graphs can contain thousands of nodes. Module-level summaries aggregate dependencies to the module boundary, reporting each module's inbound dependencies (which modules depend on it) and outbound dependencies (which modules it depends on), along with fan-in and fan-out counts.

This higher-level view reveals architectural structure: which modules are foundational (high fan-in), which are tightly coupled (high bidirectional dependencies), and where natural module boundaries exist. Library maintainers use this to plan modularization efforts, identify coupling hotspots, and assess architectural health without wading through individual definitions.

## Design Rationale

### Relationship to existing tools

`find_related` and `visualize_dependencies` serve local, interactive exploration — they answer "what is near this definition?" and "show me this subgraph." Deep dependency analysis serves project-scale understanding — it answers "what is the full dependency structure?" and "what are the architectural risks?" The two levels are complementary: engineers use `find_related` to explore locally, then invoke transitive analysis when they need the complete picture. Depth-limited transitive queries bridge the gap, with a depth of one producing the same result as `find_related`.

Extracted transitive closures, impact sets, and cycle reports integrate with `visualize_dependencies` for rendering. This means deep analysis produces the data and existing visualization presents it — no new rendering infrastructure is needed.

### Why coq-dpdgraph

coq-dpdgraph already solves the hard problem: extracting full dependency graphs from compiled Coq developments. It handles the complexities of Coq's module system, universe polymorphism, and opaque proofs, producing correct dependency data as structured output. Reimplementing this extraction would be substantial and error-prone.

What coq-dpdgraph lacks is interactive, on-demand access within an editing session. It is a command-line tool that produces static output files requiring manual post-processing. Wrapping it behind MCP tools brings its capabilities into the Claude Code workflow — engineers query dependencies conversationally without learning coq-dpdgraph's CLI, processing its output formats, or leaving their editor. The wrapper adds the query layer (transitive closure, reverse dependencies, cycle enumeration, module aggregation) on top of coq-dpdgraph's extraction layer.

---

## Acceptance Criteria

### Compute Forward Transitive Closure

**Priority:** P0
**Stability:** Stable

- GIVEN a fully qualified definition name in a compiled Coq project WHEN the transitive closure tool is invoked THEN it returns the complete set of definitions, lemmas, axioms, and constructors that the target transitively depends on
- GIVEN a definition with no dependencies beyond itself WHEN the transitive closure tool is invoked THEN it returns an empty dependency set
- GIVEN a definition in the Coq standard library WHEN the transitive closure tool is invoked THEN it returns results in under 5 seconds

**Traces to:** R7-P0-1, R7-P0-4, R7-P0-5

### Compute Reverse Dependencies (Impact Analysis)

**Priority:** P0
**Stability:** Stable

- GIVEN a fully qualified definition name WHEN the impact analysis tool is invoked THEN it returns all definitions, lemmas, and theorems in the project that transitively depend on the target
- GIVEN a definition that nothing depends on WHEN the impact analysis tool is invoked THEN it returns an empty set
- GIVEN a foundational definition used throughout a project WHEN the impact analysis tool is invoked THEN the result includes all transitive dependents, not just direct dependents

**Traces to:** R7-P0-2, R7-P0-4, R7-P0-5

### Detect Dependency Cycles

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq project with one or more dependency cycles WHEN the cycle detection tool is invoked THEN it returns each cycle as an ordered list of fully qualified participant names
- GIVEN a Coq project with no dependency cycles WHEN the cycle detection tool is invoked THEN it returns an empty result indicating no cycles were found
- GIVEN a project with multiple overlapping cycles WHEN the cycle detection tool is invoked THEN each distinct cycle is reported separately with zero false positives

**Traces to:** R7-P0-3, R7-P0-4, R7-P0-5

### Produce Module-Level Summaries

**Priority:** P1
**Stability:** Stable

- GIVEN a Coq project WHEN the module summary tool is invoked THEN it returns a list of modules, each with its inbound dependencies (modules that depend on it) and outbound dependencies (modules it depends on)
- GIVEN a module summary entry WHEN it is inspected THEN it includes fan-in count (number of modules depending on this module) and fan-out count (number of modules this module depends on)
- GIVEN a project with a single module WHEN the module summary tool is invoked THEN it returns that module with zero inbound and zero outbound module-level dependencies

**Traces to:** R7-P1-1, R7-P0-4

### Filter Dependencies by Depth

**Priority:** P1
**Stability:** Stable

- GIVEN a definition and a depth limit of N WHEN the transitive closure tool is invoked with depth=N THEN it returns only dependencies reachable within N hops
- GIVEN a depth limit of 1 WHEN the transitive closure tool is invoked THEN it returns only direct dependencies (equivalent to `find_related`)
- GIVEN a depth limit of 0 WHEN the transitive closure tool is invoked THEN it returns an empty dependency set

**Traces to:** R7-P1-2, R7-P0-4

### Filter Dependencies by Scope

**Priority:** P1
**Stability:** Stable

- GIVEN a scope filter restricting to a specific module WHEN a dependency query is invoked THEN only dependencies within that module are included in the result
- GIVEN a scope filter excluding the standard library WHEN a dependency query is invoked THEN no standard library definitions appear in the result
- GIVEN no scope filter WHEN a dependency query is invoked THEN all dependencies are included regardless of their module (default behavior)

**Traces to:** R7-P1-3, R7-P0-4

### Render Extracted Graphs with Existing Visualization

**Priority:** P1
**Stability:** Stable

- GIVEN a transitive closure result WHEN the user requests visualization THEN the result is rendered using Poule's `visualize_dependencies` tool
- GIVEN an impact analysis result WHEN the user requests visualization THEN the affected definitions are rendered as a dependency subgraph
- GIVEN a cycle detection result WHEN the user requests visualization THEN each cycle is highlighted in the rendered graph

**Traces to:** R7-P1-4, R7-P0-4

### Cache Extracted Dependency Graphs

**Priority:** P1
**Stability:** Stable

- GIVEN a project whose dependency graph has already been extracted WHEN a new dependency query is made against the same project THEN the cached graph is reused without re-extraction
- GIVEN a cached graph WHEN the underlying project source files have changed THEN the cache is invalidated and the graph is re-extracted on the next query
- GIVEN no prior extraction for a project WHEN a dependency query is made THEN the graph is extracted, the query is answered, and the graph is cached for future queries

**Traces to:** R7-P1-5

### Rank Impact by Coupling Metric

**Priority:** P2
**Stability:** Draft

- GIVEN an impact analysis result WHEN ranking is requested THEN the results are sorted by number of transitive dependents in descending order
- GIVEN a ranked result WHEN it is inspected THEN each entry includes the coupling metric value alongside the definition name

**Traces to:** R7-P2-1

### Identify Strongly Connected Components

**Priority:** P2
**Stability:** Draft

- GIVEN a Coq project WHEN strongly connected component analysis is invoked THEN it returns each component as a list of participant definitions with the component size
- GIVEN a project with no cycles WHEN the analysis is invoked THEN every strongly connected component has size 1

**Traces to:** R7-P2-2

### Export Dependency Graphs

**Priority:** P2
**Stability:** Draft

- GIVEN an extracted dependency graph WHEN export to DOT format is requested THEN the output is a valid DOT file loadable by Graphviz
- GIVEN an extracted dependency graph WHEN export to JSON adjacency list is requested THEN the output is valid JSON with each node listing its outbound edges

**Traces to:** R7-P2-4
