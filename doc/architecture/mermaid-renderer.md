# Mermaid Renderer

The component that transforms proof interaction data structures into Mermaid diagram syntax. It consumes ProofState, ProofTrace, and dependency data produced by the Proof Session Manager, and returns Mermaid text strings that can be rendered by any Mermaid-compatible service.

**Feature**: [Proof State Visualization](../features/proof-state-visualization.md), [Proof Tree Visualization](../features/proof-tree-visualization.md), [Dependency Visualization](../features/dependency-visualization.md), [Visualization MCP Tools](../features/visualization-mcp-tools.md)
**Data models**: [proof-types.md](data-models/proof-types.md)

---

## Component Diagram

```
MCP Server
  │
  │ visualization tool calls
  ▼
┌──────────────────────────────────────────────────┐
│              Mermaid Renderer                     │
│                                                   │
│  ┌─────────────────┐  ┌──────────────────────┐   │
│  │ Text Sanitizer   │  │ Layout Configuration │   │
│  │  escape special  │  │  detail_level        │   │
│  │  chars for       │  │  max_depth           │   │
│  │  Mermaid syntax  │  │  max_nodes           │   │
│  └────────┬────────┘  └──────────┬───────────┘   │
│           │                       │               │
│           ▼                       ▼               │
│  ┌────────────────────────────────────────────┐   │
│  │ Rendering Modes                            │   │
│  │                                            │   │
│  │  render_proof_state(ProofState, config)    │   │
│  │    → Mermaid flowchart                     │   │
│  │                                            │   │
│  │  render_proof_tree(ProofTrace)             │   │
│  │    → Mermaid top-down tree                 │   │
│  │                                            │   │
│  │  render_dependencies(name, graph, config)  │   │
│  │    → Mermaid directed graph                │   │
│  │                                            │   │
│  │  render_proof_sequence(ProofTrace, config) │   │
│  │    → list of Mermaid flowcharts            │   │
│  └────────────────────────────────────────────┘   │
│                                                   │
│  Input: ProofState | ProofTrace | DependencyGraph │
│  Output: string (Mermaid syntax)                  │
└──────────────────────────────────────────────────┘
```

## Text Sanitizer

Coq expressions contain characters that conflict with Mermaid syntax: parentheses, angle brackets, curly braces, pipes, quotes, and Unicode symbols. The text sanitizer escapes or transliterates these characters so that Mermaid renders them as literal text rather than interpreting them as diagram syntax.

### Escaping Strategy

```
sanitize(text)
  │
  ├─ Replace Mermaid-significant characters:
  │    [ ] → ⟦ ⟧  (or HTML entities in quoted strings)
  │    { } → escaped within quotes
  │    | → escaped within quotes
  │    < > → &lt; &gt;
  │    " → &quot;
  │
  ├─ Truncate text exceeding max_label_length (default: 80 chars)
  │    └─ Append "…" if truncated
  │
  └─ Return sanitized string safe for Mermaid node labels
```

All Coq expressions appearing as node labels or edge labels pass through the sanitizer. This is a single choke point — no rendering mode constructs labels directly from raw Coq text.

## Rendering Modes

### Proof State Rendering

Transforms a ProofState into a Mermaid flowchart with one subgraph per goal.

```
render_proof_state(state: ProofState, detail: DetailLevel)
  │
  ├─ If state.is_complete:
  │    Return single-node diagram: "Proof complete (Qed)"
  │
  ├─ For each goal in state.goals:
  │    ├─ Create a subgraph labeled "Goal {index}"
  │    │
  │    ├─ If detail ≥ STANDARD:
  │    │    For each hypothesis in goal.hypotheses:
  │    │      ├─ Create node: "{name} : {sanitize(type)}"
  │    │      └─ If detail = DETAILED and hypothesis.body is not null:
  │    │           Append body: ":= {sanitize(body)}"
  │    │
  │    ├─ Create target node: "⊢ {sanitize(goal.type)}"
  │    │
  │    └─ Draw edges from hypothesis nodes to target node
  │
  ├─ Highlight focused goal (goal at state.focused_goal_index)
  │    └─ Use distinct node styling (e.g., thicker border, different fill)
  │
  └─ Return Mermaid flowchart string
```

#### Detail Levels

| Level | Goals shown | Hypotheses shown | Types expanded | Let-bodies shown |
|-------|-------------|------------------|----------------|------------------|
| `SUMMARY` | Count + focused goal type only | No | No | No |
| `STANDARD` | All, with focused highlighted | Yes, names + types | No | No |
| `DETAILED` | All, with focused highlighted | Yes, names + types | Yes | Yes |

### Proof Tree Rendering

Transforms a ProofTrace into a Mermaid top-down tree diagram.

```
render_proof_tree(trace: ProofTrace)
  │
  ├─ Build tree structure from trace steps:
  │    ├─ Root node: theorem statement from step 0
  │    │
  │    ├─ For each step k (1..N):
  │    │    ├─ Determine parent: the goal that step k's tactic acted on
  │    │    │
  │    │    ├─ Create edge: parent_goal --"{tactic}"--> child_goal(s)
  │    │    │
  │    │    ├─ If tactic produced multiple subgoals (branching):
  │    │    │    Create one child node per new subgoal
  │    │    │
  │    │    └─ If tactic discharged the goal (no remaining subgoals for this branch):
  │    │         Mark child node as discharged
  │    │
  │    └─ Assign node IDs for Mermaid cross-referencing
  │
  ├─ Apply node styles:
  │    ├─ Open goals: default node style
  │    ├─ Discharged goals: distinct style (e.g., dashed border, green fill)
  │    └─ Root: bold/emphasized
  │
  └─ Return Mermaid flowchart string (top-down direction: TD)
```

#### Tree Construction from Linear Trace

ProofTrace stores steps linearly. The tree structure is reconstructed by tracking goal focus:

```
build_proof_tree(trace: ProofTrace)
  │
  ├─ Initialize: root = theorem goal from step 0
  │    goal_stack = [root]
  │
  ├─ For each step k (1..N):
  │    ├─ state_before = trace.steps[k-1].state
  │    ├─ state_after  = trace.steps[k].state
  │    ├─ tactic       = trace.steps[k].tactic
  │    │
  │    ├─ Compare goals:
  │    │    ├─ Goals in state_before but not state_after → discharged by this tactic
  │    │    ├─ Goals in state_after but not state_before → introduced by this tactic
  │    │    └─ Goals in both → unchanged (other branches)
  │    │
  │    ├─ Create tree node for each new goal, parented to the focused goal of state_before
  │    │
  │    └─ Mark discharged goals
  │
  └─ Return tree structure (nodes + edges)
```

### Dependency Subgraph Rendering

Transforms a dependency adjacency list into a Mermaid directed graph, scoped to a configurable depth.

```
render_dependencies(
  theorem_name: string,
  dependencies: DependencyGraph,
  max_depth: integer,
  max_nodes: integer
)
  │
  ├─ BFS from theorem_name through dependencies:
  │    ├─ Visit each dependency up to max_depth hops
  │    ├─ Stop expanding a branch if total nodes exceed max_nodes
  │    └─ Collect (source, target, kind) edges
  │
  ├─ Classify nodes:
  │    ├─ Theorem/Lemma → default rectangle
  │    ├─ Definition → rounded rectangle
  │    ├─ Axiom → hexagon (visually distinct)
  │    └─ Root theorem → bold/emphasized
  │
  ├─ Create Mermaid directed graph:
  │    ├─ One node per unique entity
  │    ├─ Directed edges: source --> target (uses relationship)
  │    └─ Apply node shapes based on classification
  │
  └─ Return Mermaid flowchart string (top-down direction: TD)
```

#### Dependency Data Source

The renderer does not query Coq or the search index directly. It receives a pre-resolved dependency adjacency list from the MCP Server, which obtains it from:

- **Live sessions**: The Proof Session Manager can extract dependencies for the current proof via premise extraction
- **Search index**: The `find_related` tool provides `uses` relationships for indexed declarations
- **Extraction data**: Batch-extracted dependency graphs from Phase 3

The renderer is agnostic to the data source — it renders whatever adjacency list it receives.

### Proof Sequence Rendering

Transforms a ProofTrace into a list of proof state diagrams, one per step, with diff highlighting.

```
render_proof_sequence(trace: ProofTrace, detail: DetailLevel)
  │
  ├─ diagrams = []
  │
  ├─ diagrams.append(render_proof_state(trace.steps[0].state, detail))
  │
  ├─ For each step k (1..N):
  │    ├─ Compute diff between trace.steps[k-1].state and trace.steps[k].state
  │    │    (produces ProofStateDiff: goals_added, goals_removed,
  │    │     hypotheses_added, hypotheses_removed, etc.)
  │    │
  │    ├─ Render trace.steps[k].state with diff annotations:
  │    │    ├─ New goals → highlighted node style (e.g., bold border)
  │    │    ├─ Removed goals → omitted (they're discharged)
  │    │    ├─ New hypotheses → highlighted node style
  │    │    ├─ Changed hypotheses → annotated with before/after
  │    │    └─ Tactic label shown as diagram title or annotation
  │    │
  │    └─ diagrams.append(annotated_diagram)
  │
  └─ Return diagrams (list of Mermaid strings, length = total_steps + 1)
```

Diff computation reuses the ProofStateDiff type defined in [data-models/proof-types.md](data-models/proof-types.md).

## Configuration

| Parameter | Default | Used by |
|-----------|---------|---------|
| `detail_level` | `STANDARD` | Proof state, proof sequence |
| `max_depth` | `2` | Dependency subgraph |
| `max_nodes` | `50` | Dependency subgraph |
| `max_label_length` | `80` | All modes (text sanitizer) |

These are passed per-request via the MCP tool parameters. There are no persistent configuration files — each tool call is self-contained.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Empty proof state (no goals, not complete) | Return a diagram with a single "Empty state" node |
| Proof trace with 0 steps | Return diagram of the initial state only |
| Dependency graph with no edges for the named theorem | Return single-node diagram with just the theorem |
| Sanitizer encounters unrepresentable Unicode | Replace with `?` and continue |
| Generated Mermaid exceeds practical rendering limits (> 200 nodes) | Truncate with a "... and N more nodes" summary node |

The renderer never fails with an exception for valid input types. Degenerate inputs produce degenerate but valid Mermaid diagrams.

## Design Rationale

### Why a single component rather than one per visualization type

All four rendering modes share the text sanitizer, configuration handling, node ID generation, and Mermaid syntax construction utilities. Splitting into four components would duplicate this infrastructure and create coordination overhead when the shared conventions change (e.g., updating the escaping strategy).

### Why the renderer does not access Coq or the search index

The renderer's single responsibility is: structured data in, Mermaid text out. If it also queried the Coq backend or search index, it would become coupled to session state and database availability. By receiving pre-resolved data from the MCP Server, the renderer is a pure function — easy to test, easy to reuse outside the MCP context (e.g., in the batch extraction CLI).

### Why BFS with max_nodes for dependency graphs rather than exact depth limiting

Exact depth limiting can produce diagrams that are too large if a theorem has high fan-out at shallow depths (e.g., a theorem that directly depends on 50 lemmas at depth 1). The max_nodes cap provides a hard upper bound on diagram size regardless of graph shape. BFS ensures that closer dependencies are always included before more distant ones.

### Why ProofStateDiff for sequence rendering rather than custom diff logic

The ProofStateDiff type is already defined in the proof types data model and used by the proof serialization layer. Reusing it avoids defining a parallel diff representation and ensures consistency between the diff data available in traces and the diff data used for visualization.

## Language-Specific Notes

### Python

The renderer is a pure module with no runtime dependencies beyond string operations. It does not import `mermaid`, `graphviz`, or any rendering library — it produces text strings only.

Detail levels can be represented as an enum:

```
class DetailLevel(Enum):
    SUMMARY = "summary"
    STANDARD = "standard"
    DETAILED = "detailed"
```
