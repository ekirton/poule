# Deep Dependency Analysis

The component that builds an in-memory dependency graph from Storage and coq-dpdgraph output, then answers transitive queries — forward closure, reverse closure (impact analysis), cycle detection, and module-level aggregation — over that graph. The MCP Server delegates deep dependency tool calls to this component; results integrate with the existing Mermaid Renderer for visualization.

**Feature**: [Deep Dependency Analysis](../features/deep-dependency-analysis.md)

---

## Component Diagram

```
Claude Code / LLM
  │
  │ MCP tool calls (stdio)
  ▼
MCP Server
  │         │          │
  │ deep    │ viz      │ find_related
  │ dep     │ dispatch │ (existing)
  │ tools   │          │
  ▼         ▼          ▼
┌─────────────────────────────────────────────────────────────────┐
│              Deep Dependency Analysis Engine                     │
│                                                                  │
│  ┌──────────────────────┐                                        │
│  │  Graph Builder        │                                       │
│  │                       │                                       │
│  │  Storage (SQLite)  ───┼──→ In-memory DependencyGraph          │
│  │  coq-dpdgraph .dot ──┘    (adjacency lists: forward + reverse)│
│  └──────────────────────┘                                        │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐  │
│  │  Transitive Closure   │  │  Impact Analysis                │  │
│  │  (forward BFS/DFS)    │  │  (reverse BFS/DFS)              │  │
│  │  depth + scope filter │  │  depth + scope filter           │  │
│  └──────────────────────┘  └──────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐  │
│  │  Cycle Detection      │  │  Module Aggregation             │  │
│  │  (Tarjan's SCC)       │  │  (project from nodes to modules)│  │
│  └──────────────────────┘  └──────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────┐                                        │
│  │  Graph Cache          │                                       │
│  │  project_key → graph  │                                       │
│  │  + invalidation       │                                       │
│  └──────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
  │                              │
  │ query results                │ adjacency list (for rendering)
  ▼                              ▼
MCP Server                   Mermaid Renderer
  │                          (render_dependencies — existing)
  ▼
Claude Code / LLM
```

The Deep Dependency Analysis Engine sits between the MCP Server and Storage. It reads dependency data, constructs the in-memory graph, and exposes query operations. It does not own or modify Storage — it is a read-only consumer. The Mermaid Renderer remains a pure function that receives pre-resolved adjacency lists; it does not know whether those lists come from `find_related` (one-hop) or deep analysis (transitive).

## Graph Construction

The engine builds a `DependencyGraph` — a pair of adjacency lists (forward and reverse) indexed by fully qualified declaration name — from one of two sources:

### Source 1: Storage (existing `dependencies` table)

For projects already indexed by Coq Library Extraction, the graph is constructed by reading all rows from the `dependencies` table where `relation = 'uses'`:

```
build_graph_from_storage(index_reader)
  │
  ├─ Query: SELECT d1.name, d2.name
  │         FROM dependencies dep
  │         JOIN declarations d1 ON dep.src = d1.id
  │         JOIN declarations d2 ON dep.dst = d2.id
  │         WHERE dep.relation = 'uses'
  │
  ├─ For each (src_name, dst_name):
  │    forward_adj[src_name].add(dst_name)
  │    reverse_adj[dst_name].add(src_name)
  │
  ├─ Load declaration metadata (name → module, kind) for all declarations
  │
  └─ Return DependencyGraph(forward_adj, reverse_adj, metadata)
```

This reuses the same dependency data that `find_related` queries one hop at a time, but loads the full graph into memory for transitive traversal.

### Source 2: coq-dpdgraph DOT output

For projects not yet indexed, or when richer dependency data is needed (coq-dpdgraph captures dependencies that the indexing pipeline may not extract), the engine parses `.dot` files produced by `coq-dpdgraph`:

```
build_graph_from_dpdgraph(dot_file_path)
  │
  ├─ Parse DOT file:
  │    ├─ Extract node declarations: node_id → fully qualified name
  │    └─ Extract directed edges: (src_id, dst_id) with optional edge attributes
  │
  ├─ Resolve node IDs to fully qualified names
  │
  ├─ For each edge (src_name, dst_name):
  │    forward_adj[src_name].add(dst_name)
  │    reverse_adj[dst_name].add(src_name)
  │
  ├─ Infer module from fully qualified name (prefix up to last dot-separated component)
  │
  └─ Return DependencyGraph(forward_adj, reverse_adj, metadata)
```

The DOT parser handles the specific output format of `coq-dpdgraph dpd2dot` — quoted node names with fully qualified Coq identifiers, directed edges representing `uses` relationships.

### Source Selection

The MCP Server determines which source to use:

1. If an index database is available and loaded, use Storage (preferred — faster, already in-process).
2. If a `.dot` file path is provided as a tool parameter, use coq-dpdgraph output.
3. If both are available, the tool parameter selects the source explicitly.

## Transitive Closure Algorithm

Given a root declaration, compute all declarations it transitively depends on.

```
transitive_closure(graph, root, max_depth, scope_filter)
  │
  ├─ Validate root exists in graph.forward_adj
  │    └─ If not → NOT_FOUND error
  │
  ├─ Initialize:
  │    visited = { root }
  │    frontier = { root }
  │    depth = 0
  │    closure_by_depth = { 0: { root } }
  │
  ├─ While frontier is not empty AND depth < max_depth (if specified):
  │    │
  │    ├─ next_frontier = {}
  │    │
  │    ├─ For each node in frontier:
  │    │    For each neighbor in graph.forward_adj[node]:
  │    │      │
  │    │      ├─ If neighbor in visited → skip
  │    │      ├─ If scope_filter rejects neighbor → skip
  │    │      │
  │    │      ├─ visited.add(neighbor)
  │    │      └─ next_frontier.add(neighbor)
  │    │
  │    ├─ depth += 1
  │    ├─ closure_by_depth[depth] = next_frontier
  │    └─ frontier = next_frontier
  │
  └─ Return TransitiveClosure(
       root = root,
       nodes = visited,
       edges = { (u, v) for u in visited for v in graph.forward_adj[u] if v in visited },
       depth_map = closure_by_depth,
       total_depth = depth
     )
```

The algorithm is BFS-based to produce the depth map (which level each node appears at). Depth-limited queries terminate early when `depth >= max_depth`. A `max_depth` of 1 produces the same result as `find_related` with `relation = "uses"`, providing continuity between the two interfaces.

### Scope Filtering

The `scope_filter` predicate restricts which nodes are followed during traversal:

| Filter | Behavior |
|--------|----------|
| `module_prefix(prefix)` | Include only nodes whose module starts with `prefix` (e.g., `"Coq.Arith"`) |
| `exclude_prefix(prefix)` | Exclude nodes whose module starts with `prefix` (e.g., `"Coq.Init"` to exclude standard library) |
| `same_project` | Include only nodes whose module shares the top-level namespace with the root |
| No filter | Include all nodes (default) |

Filters compose: multiple filters are combined as a conjunction (all must pass).

## Impact Analysis (Reverse Transitive Closure)

Given a root declaration, compute all declarations that transitively depend on it. This is the same BFS algorithm as transitive closure, but traversing `reverse_adj` instead of `forward_adj`:

```
impact_analysis(graph, root, max_depth, scope_filter)
  │
  ├─ Validate root exists in graph.reverse_adj
  │    └─ If root has no reverse edges → return empty ImpactSet (nothing depends on it)
  │
  ├─ BFS over graph.reverse_adj (same algorithm as transitive_closure)
  │
  └─ Return ImpactSet(
       root = root,
       impacted_nodes = visited,
       edges = { (u, v) for u in visited for v in graph.reverse_adj[u] if v in visited },
       depth_map = closure_by_depth,
       total_depth = depth
     )
```

The `ImpactSet` is structurally identical to `TransitiveClosure` but carries reverse-direction semantics. The depth map indicates how many hops separate each impacted definition from the changed root — depth 1 nodes are direct dependents, deeper nodes are transitively affected.

## Cycle Detection

Identify all strongly connected components (SCCs) with more than one member. Each non-trivial SCC represents a set of definitions involved in mutual (possibly indirect) dependency cycles.

### Tarjan's SCC Algorithm

```
detect_cycles(graph)
  │
  ├─ Initialize:
  │    index_counter = 0
  │    stack = []
  │    on_stack = {}
  │    node_index = {}
  │    node_lowlink = {}
  │    sccs = []
  │
  ├─ For each node in graph.forward_adj:
  │    If node not in node_index:
  │      strongconnect(node)
  │
  │  strongconnect(v):
  │    node_index[v] = index_counter
  │    node_lowlink[v] = index_counter
  │    index_counter += 1
  │    stack.push(v)
  │    on_stack[v] = true
  │
  │    For each w in graph.forward_adj[v]:
  │      If w not in node_index:
  │        strongconnect(w)
  │        node_lowlink[v] = min(node_lowlink[v], node_lowlink[w])
  │      Else if on_stack[w]:
  │        node_lowlink[v] = min(node_lowlink[v], node_index[w])
  │
  │    If node_lowlink[v] == node_index[v]:
  │      scc = []
  │      Repeat:
  │        w = stack.pop()
  │        on_stack[w] = false
  │        scc.append(w)
  │      Until w == v
  │      If |scc| > 1:
  │        sccs.append(scc)
  │
  └─ Return CycleReport(
       cycles = sccs,
       total_cycle_count = |sccs|,
       total_nodes_in_cycles = sum(|scc| for scc in sccs),
       is_acyclic = |sccs| == 0
     )
```

Tarjan's algorithm runs in O(V + E) time, visiting each node and edge exactly once. It is the standard choice for SCC detection — correct, linear, and well-understood.

### Cycle Representation

Each SCC is reported as an ordered list of participants. The ordering follows Tarjan's stack pop order, which gives a reverse topological ordering within the SCC. For presentation purposes, the MCP tool rotates the list to start with the lexicographically smallest member, providing a canonical ordering for stable output.

## Module-Level Aggregation

Project definition-level dependency data to module boundaries, producing a coarser graph suitable for architectural assessment.

```
module_summary(graph)
  │
  ├─ Build module-level edges:
  │    For each (src, dst) in graph.forward_adj:
  │      src_module = graph.metadata[src].module
  │      dst_module = graph.metadata[dst].module
  │      If src_module != dst_module:
  │        module_forward[src_module].add(dst_module)
  │        module_reverse[dst_module].add(src_module)
  │
  ├─ Compute per-module metrics:
  │    For each module m:
  │      fan_out = |module_forward[m]|    (modules m depends on)
  │      fan_in  = |module_reverse[m]|    (modules that depend on m)
  │      internal_nodes = count of declarations in m
  │
  ├─ Detect module-level cycles (reuse Tarjan's SCC on module graph)
  │
  └─ Return ModuleSummary(
       modules = { m: { fan_in, fan_out, internal_nodes } for each m },
       module_edges = module_forward,
       module_cycles = module_level_sccs,
       total_modules = count of modules
     )
```

Self-edges (dependencies within the same module) are excluded from the module graph — they do not contribute to inter-module coupling.

## Depth and Scope Filtering

Filtering applies uniformly across transitive closure, impact analysis, and visualization integration:

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `max_depth` | positive integer or null | null (unlimited) | BFS terminates after this many hops; null means full closure |
| `scope` | list of scope filter predicates | empty (no filter) | Nodes failing the filter are not visited or included in results |

A `max_depth` of 1 for transitive closure produces the same set as `find_related(name, "uses")`. A `max_depth` of 1 for impact analysis produces the same set as `find_related(name, "used_by")`. This provides a continuum from existing single-hop tools to full transitive analysis.

## Integration with Existing `visualize_dependencies`

The existing `visualize_dependencies` MCP tool currently receives a subgraph from `find_related` and passes it to the Mermaid Renderer's `render_dependencies` function. Deep dependency analysis extends this by providing larger, transitively computed subgraphs as input to the same renderer.

The MCP Server routes visualization as follows:

1. `visualize_dependencies(name, max_depth=2)` — existing behavior: MCP Server calls `find_related` to build a small subgraph, passes it to `render_dependencies`.
2. `visualize_transitive_closure(name, max_depth, scope)` — new: MCP Server calls the Deep Dependency Analysis Engine for transitive closure, extracts the edge set, passes it to `render_dependencies`.
3. `visualize_impact(name, max_depth, scope)` — new: same pattern with reverse edges.
4. `visualize_module_dependencies(scope)` — new: MCP Server calls for a module summary, passes the module-level edge set to `render_dependencies`.

The Mermaid Renderer requires no changes. It already accepts an arbitrary adjacency list and renders it with BFS truncation at `max_nodes`. The only difference is that the adjacency lists are now larger and carry depth annotations.

For large transitive closures that exceed practical rendering limits, the MCP Server applies `max_nodes` truncation before passing data to the renderer, consistent with the existing `DIAGRAM_TRUNCATED` warning behavior.

## Data Structures

### DependencyGraph

The in-memory representation of the full project dependency graph.

| Field | Type | Description |
|-------|------|-------------|
| `forward_adj` | map of name to set of names | For each declaration, the set of declarations it directly depends on |
| `reverse_adj` | map of name to set of names | For each declaration, the set of declarations that directly depend on it |
| `metadata` | map of name to NodeMetadata | Per-declaration metadata: module, kind |
| `node_count` | non-negative integer | Total declarations in the graph |
| `edge_count` | non-negative integer | Total dependency edges |

### NodeMetadata

| Field | Type | Description |
|-------|------|-------------|
| `module` | qualified name | Module containing this declaration |
| `kind` | enumeration | Declaration kind (lemma, theorem, definition, etc.) |

### TransitiveClosure

| Field | Type | Description |
|-------|------|-------------|
| `root` | qualified name | The declaration whose closure was computed |
| `nodes` | set of names | All declarations in the closure (including root) |
| `edges` | set of (name, name) pairs | All edges within the closure subgraph |
| `depth_map` | map of integer to set of names | Nodes at each BFS depth level |
| `total_depth` | non-negative integer | Maximum depth reached |

### ImpactSet

| Field | Type | Description |
|-------|------|-------------|
| `root` | qualified name | The declaration whose impact was analyzed |
| `impacted_nodes` | set of names | All declarations transitively depending on root |
| `edges` | set of (name, name) pairs | All edges within the impact subgraph |
| `depth_map` | map of integer to set of names | Impacted nodes at each BFS depth level |
| `total_depth` | non-negative integer | Maximum reverse depth reached |

### CycleReport

| Field | Type | Description |
|-------|------|-------------|
| `cycles` | list of lists of names | Each inner list is one SCC, canonically ordered |
| `total_cycle_count` | non-negative integer | Number of non-trivial SCCs |
| `total_nodes_in_cycles` | non-negative integer | Sum of SCC sizes |
| `is_acyclic` | boolean | True when no cycles exist |

### ModuleSummary

| Field | Type | Description |
|-------|------|-------------|
| `modules` | map of module name to ModuleMetrics | Per-module fan-in, fan-out, internal node count |
| `module_edges` | map of module name to set of module names | Module-level forward adjacency |
| `module_cycles` | list of lists of module names | Module-level SCCs (from Tarjan's on the module graph) |
| `total_modules` | non-negative integer | Count of distinct modules |

### ModuleMetrics

| Field | Type | Description |
|-------|------|-------------|
| `fan_in` | non-negative integer | Number of modules that depend on this module |
| `fan_out` | non-negative integer | Number of modules this module depends on |
| `internal_nodes` | positive integer | Number of declarations in this module |

## Error Handling

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Root declaration not found in graph | `NOT_FOUND` | Declaration `{name}` not found in the dependency graph. |
| No index database and no DOT file provided | `INDEX_MISSING` | No dependency data available. Provide a coq-dpdgraph DOT file or ensure the index database exists. |
| DOT file not found at provided path | `FILE_NOT_FOUND` | DOT file not found: `{path}` |
| DOT file parse failure (malformed syntax) | `PARSE_ERROR` | Failed to parse DOT file: `{details}` |
| Graph not yet built (query before construction) | `GRAPH_NOT_READY` | Dependency graph has not been constructed. Call with a valid index or DOT file first. |
| Transitive closure exceeds node safety limit | `RESULT_TOO_LARGE` | Transitive closure contains `{count}` nodes, exceeding the limit of `{limit}`. Use max_depth or scope filters to narrow the query. |
| coq-dpdgraph not installed (DOT source requested) | `TOOL_MISSING` | coq-dpdgraph is not installed or not on PATH. Install it to use DOT-based dependency analysis. |

All errors use the MCP standard error format defined in [mcp-server.md](mcp-server.md) § Error Contract.

## Design Rationale

### Extend existing Storage vs. external tool only

The engine supports both sources. Storage is preferred when available because it is already in-process, requires no additional tooling, and covers the dependencies extracted during indexing. coq-dpdgraph is the fallback for unindexed projects and for cases where its extraction captures dependencies the indexing pipeline does not (e.g., opaque proof internals, universe constraints). Supporting both avoids a hard dependency on coq-dpdgraph while preserving access to its richer extraction when needed.

### In-memory graph vs. SQL-based traversal

Transitive closure over SQL requires recursive CTEs or repeated queries — both are slow for large graphs and awkward for cycle detection. Loading the full graph into memory (two adjacency maps) is straightforward, supports all query types (BFS, Tarjan's SCC, module projection) with standard graph algorithms, and is feasible for Coq project sizes. A project with 10,000 declarations and 50,000 edges requires roughly 5–10 MB of memory for the adjacency representation — negligible.

### Caching strategy

The in-memory `DependencyGraph` is cached per project (keyed by index database path or DOT file path). The cache is invalidated when:

1. The index database's `schema_version` or `created_at` timestamp changes (detected on next query).
2. A different DOT file path is provided.
3. The MCP server restarts (cache is process-scoped, not persisted).

This avoids redundant graph construction when multiple queries target the same project within a session, which is the expected usage pattern (engineer explores one project, asks multiple dependency questions). The cache holds at most one graph per project — there is no unbounded growth.

### Tarjan's SCC over alternatives

Tarjan's algorithm is O(V + E) and identifies all SCCs in a single pass. Alternatives include Kosaraju's algorithm (also O(V + E) but requires two passes) and Johnson's algorithm (enumerates all elementary cycles, which can be exponentially many). Tarjan's is the right choice because the requirement is to identify cycle participants (SCCs), not to enumerate every distinct cycle path.

### Module aggregation as projection, not separate extraction

Module-level dependencies are derived by projecting the definition-level graph onto module boundaries, rather than extracting module dependencies separately. This ensures consistency — the module graph is always a faithful summary of the definition graph, with no possibility of divergence. It also means module summaries are available immediately once the definition graph is built, with no additional data extraction step.

### Depth-1 equivalence with find_related

A `max_depth` of 1 for forward closure produces the same result as `find_related(name, "uses")`, and depth 1 for impact analysis matches `find_related(name, "used_by")`. This is a deliberate design constraint that ensures the deep analysis tools are a strict superset of the existing one-hop tools, providing a smooth upgrade path and consistent mental model for users.

## Boundary Contracts

### MCP Server → Deep Dependency Analysis Engine

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | Query type (closure, impact, cycles, module summary) + parameters (root name, max_depth, scope filters) |
| Output | TransitiveClosure, ImpactSet, CycleReport, or ModuleSummary |
| Dependencies | Storage (read-only, for graph construction from index) |

### Deep Dependency Analysis Engine → Storage

| Property | Value |
|----------|-------|
| Mechanism | SQLite queries (via existing IndexReader) |
| Direction | Read-only |
| Tables read | `declarations`, `dependencies` |
| Purpose | Graph construction from indexed dependency data |

### MCP Server → Mermaid Renderer (extended)

The existing contract (adjacency list in, Mermaid text out) is unchanged. The MCP Server passes larger adjacency lists derived from deep analysis results, using the same `render_dependencies` interface.
