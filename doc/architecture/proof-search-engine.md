# Proof Search Engine

The component that executes best-first tree search over tactic candidates, verifying each candidate against Coq via the Proof Session Manager. Claude Code invokes proof search as an MCP tool; the engine runs the tight explore-verify loop internally.

**Feature**: [Proof Search](../features/proof-search.md), [Few-Shot Context Retrieval](../features/few-shot-context-retrieval.md)
**Data models**: [proof-types.md](data-models/proof-types.md)

---

## Component Diagram

```
MCP Server
  │
  │ proof_search(session_id, timeout, max_depth, max_breadth)
  ▼
┌───────────────────────────────────────────────────────────────┐
│                   Proof Search Engine                          │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Search Loop (best-first)                                │  │
│  │                                                         │  │
│  │  Priority Queue: SearchNode[]                          │  │
│  │    ranked by score (higher = more promising)           │  │
│  │                                                         │  │
│  │  For each node popped from the queue:                  │  │
│  │    1. Generate candidates (Candidate Generator)        │  │
│  │    2. Filter duplicates (Diversity Filter)             │  │
│  │    3. Verify each candidate (→ Proof Session Manager)  │  │
│  │    4. Score successes, push to queue                   │  │
│  │    5. If proof complete → return success               │  │
│  │    6. If timeout/budget exhausted → return failure     │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────┐  ┌────────────────┐  ┌──────────────┐ │
│  │ Candidate         │  │ Diversity      │  │ State Cache  │ │
│  │ Generator         │  │ Filter         │  │              │ │
│  │                   │  │                │  │ proof state  │ │
│  │ LLM candidates   │  │ Dedup exact   │  │ hash → bool  │ │
│  │ Solver candidates │  │ De-prioritize │  │              │ │
│  │ Few-shot context  │  │  near-dupes   │  │ Prunes nodes │ │
│  │ Premise context   │  │               │  │ already seen │ │
│  └────────┬──────────┘  └───────────────┘  └──────────────┘ │
│           │                                                   │
│           │ premise retrieval (optional)                       │
│           ▼                                                   │
│  ┌───────────────────┐                                        │
│  │ Retrieval Pipeline │ (optional; only when search index     │
│  │ (search_by_type,   │  is available)                        │
│  │  search_by_symbols)│                                       │
│  └───────────────────┘                                        │
└───────────────────────────────────────────────────────────────┘
  │                           │
  │ tactic verification       │ few-shot retrieval (optional)
  ▼                           ▼
Proof Session Manager     Extracted Training Data
  │                       (JSON Lines files from Phase 3)
  ▼
Coq Backend Process
```

## Search Algorithm

### Data Structures

**SearchNode** — a node in the search tree:

| Field | Type | Description |
|-------|------|-------------|
| `proof_state` | ProofState | The proof state at this node |
| `state_hash` | bytes | Hash of (goals, hypotheses) for deduplication |
| `tactic_path` | list of string | Tactic sequence from root to this node |
| `depth` | non-negative integer | Length of `tactic_path` |
| `score` | float | Priority score (higher = expand first) |
| `parent` | reference to SearchNode or null | Parent in the search tree |

**SearchResult** — the output of a search run:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `"success"` or `"failure"` | Whether a complete proof was found |
| `proof_script` | list of ProofStep or null | On success: the verified tactic sequence with per-step states |
| `best_partial` | list of ProofStep or null | On failure: the deepest partial proof |
| `states_explored` | non-negative integer | Total nodes expanded |
| `unique_states` | non-negative integer | Distinct proof states (after dedup) |
| `wall_time_ms` | non-negative integer | Wall-clock time in milliseconds |

**ProofStep** — one step in a proof script:

| Field | Type | Description |
|-------|------|-------------|
| `tactic` | string | The tactic text |
| `state_before` | ProofState | Proof state before this tactic |
| `state_after` | ProofState | Proof state after this tactic |

### Main Loop

```
proof_search(session_id, timeout=30, max_depth=10, max_breadth=20)
  │
  ├─ Observe current proof state via Proof Session Manager
  │
  ├─ Initialize:
  │    root = SearchNode(state=current_state, depth=0, score=1.0)
  │    queue = PriorityQueue([root])
  │    state_cache = { hash(current_state) }
  │    deadline = now + timeout
  │    stats = { explored: 0, unique: 0 }
  │
  ├─ While queue is not empty AND now < deadline:
  │    │
  │    ├─ node = queue.pop_highest_score()
  │    ├─ stats.explored += 1
  │    │
  │    ├─ If node.depth >= max_depth → skip (too deep)
  │    │
  │    ├─ Generate candidates for node.proof_state (see Candidate Generation)
  │    ├─ Filter candidates through Diversity Filter
  │    ├─ Limit to max_breadth candidates
  │    │
  │    ├─ For each candidate tactic:
  │    │    │
  │    │    ├─ Fork session state to node's position
  │    │    │    (step backward/forward to replay tactic_path, then submit candidate)
  │    │    │
  │    │    ├─ Submit tactic to Proof Session Manager
  │    │    │    ├─ On failure → discard candidate, continue
  │    │    │    └─ On success → new_state
  │    │    │
  │    │    ├─ If new_state.is_complete → return SUCCESS with tactic_path + candidate
  │    │    │
  │    │    ├─ Compute state_hash for new_state
  │    │    ├─ If state_hash in state_cache → skip (already explored)
  │    │    ├─ state_cache.add(state_hash)
  │    │    ├─ stats.unique += 1
  │    │    │
  │    │    ├─ Score new_state (see Scoring)
  │    │    └─ Push SearchNode(new_state, depth+1, score) to queue
  │    │
  │    └─ Continue to next node
  │
  └─ Timeout or queue exhausted:
       Return FAILURE with best_partial (deepest node), stats
```

### Session State Management During Search

The search engine operates on a single proof session. To explore different branches, it must navigate the session's state:

1. Before verifying a candidate at depth k, replay the tactic path from the root to depth k-1
2. Submit the candidate tactic as step k
3. Observe the resulting state
4. Before exploring the next branch, step backward to restore the parent state

This means the search uses `submit_tactic` and `step_backward` from the Proof Session Manager. The session's linear history model (see [proof-session.md](proof-session.md)) means branching requires replay — stepping backward discards the forward branch, and the new tactic path must be replayed.

**Optimization**: Since the Proof Session Manager caches states in `step_history`, replay of previously visited paths is cheap (states are already cached). The cost is proportional to the number of new tactic submissions, not the full path length.

**Alternative (future)**: If search performance is bottlenecked by replay overhead, a pool of sessions could be used — one per active branch. This trades memory (multiple Coq backend processes) for replay cost. The current single-session approach is simpler and sufficient for the target of ≥ 50 states/second.

## Candidate Generation

The Candidate Generator produces a set of tactic candidates for a given proof state. Candidates come from multiple sources, combined into a single ranked list.

### LLM Candidates

```
generate_llm_candidates(proof_state, premises, few_shot_examples)
  │
  ├─ Construct prompt:
  │    - System: "You are a Coq tactic generator. Given a proof state,
  │      suggest candidate tactics. Return only tactic text, one per line."
  │    - Few-shot examples (if available): (state, successful_tactic) pairs
  │    - Premises (if available): retrieved lemma names and types
  │    - Current state: goals, hypotheses, local context
  │
  ├─ Call Claude API (hosted, no GPU required)
  │
  ├─ Parse response into list of tactic strings
  │
  └─ Return tactic strings with source="llm"
```

The prompt is conditioned on:
- **Proof state**: Goals, hypotheses, and local context (always available)
- **Retrieved premises**: When the Retrieval Pipeline is available, `search_by_type` and `search_by_symbols` are called with the current goal to retrieve relevant lemmas. Their names and types are included in the prompt, enabling candidates like `apply retrieved_lemma` or `rewrite retrieved_lemma`.
- **Few-shot examples**: When extracted training data is available, similar proof states are retrieved by structural/symbolic overlap and included as (state, tactic) pairs (see Few-Shot Retrieval below).

### Solver Candidates

At every search node, a fixed set of solver tactics is included:

```
SOLVER_TACTICS = [
  "auto",
  "auto with *",
  "eauto",
  "omega",     // or "lia" depending on Coq version
  "lia",
  "intuition",
  "tauto",
  "congruence",
  "reflexivity",
  "assumption",
  "trivial",
]
```

Solver tactics are tried first before LLM candidates. They are fast to verify (milliseconds) and handle mechanical sub-goals without an LLM API call. When a solver tactic closes a sub-goal, the LLM is not called for that node — the solver result is used directly.

### Candidate Ordering

Candidates are ordered for verification:
1. Solver tactics (fast, no API cost)
2. LLM candidates (ordered by model confidence if available, otherwise by position in output)

## Diversity Filter

Before candidates are submitted to Coq for verification, near-duplicates are filtered:

1. **Exact dedup**: Syntactically identical tactic strings are deduplicated (keep first occurrence)
2. **Semantic dedup**: Tactics that differ only in whitespace or surface syntax (e.g., `rewrite H` vs `rewrite -> H`) are collapsed to a single representative
3. **Similarity threshold**: If two LLM-generated candidates share > 90% token overlap, keep only the first

The filter runs before verification, so it reduces Coq round-trips rather than post-filtering verified results.

## State Cache

The state cache maps proof state hashes to a boolean "already explored" flag. It prevents the search from wasting budget on proof states that have already been reached by a different tactic path.

### State Hashing

A proof state is hashed by:
1. Sorting goals by their type string (order-independent)
2. For each goal, sorting hypotheses by name
3. Concatenating the sorted goal types and hypothesis (name, type) pairs
4. Computing a cryptographic hash (SHA-256) of the concatenation

This hash is sensitive to the mathematical content (goals and hypotheses) but insensitive to goal ordering and metadata (step index, session ID).

### Cache Size

The cache grows by at most one entry per unique state explored. For a 30-second search exploring ~1500 states (at 50 states/second), the cache holds at most 1500 entries — negligible memory.

## Scoring

The score function ranks search nodes in the priority queue. Higher scores are expanded first.

```
score(node) = goal_reduction_weight * goal_progress
            + depth_penalty * (1 / (1 + node.depth))
```

Where:
- **goal_progress**: Fraction of goals closed relative to the root state. If the root had 3 goals and this node has 1, progress = 2/3.
- **depth_penalty**: Bias toward shallower proofs. Shallower proofs are more likely to succeed and produce more readable output.
- **goal_reduction_weight** and **depth_penalty** are tunable parameters (defaults to be determined empirically).

This scoring function is deliberately simple. More sophisticated scoring (learned value functions, proof distance estimation) is deferred to P2 (R4-P2-2).

## Few-Shot Retrieval

When extracted training data (Phase 3 JSON Lines files) is available:

```
retrieve_few_shot(proof_state, training_data_index, k=5)
  │
  ├─ Extract query features from proof_state:
  │    - Goal type tokens
  │    - Hypothesis type tokens
  │    - Symbol set (constants, inductives, constructors referenced)
  │
  ├─ Query training data index for top-k similar proof states
  │    (similarity = weighted Jaccard over symbol sets + token overlap)
  │
  ├─ For each matched state, retrieve the tactic that succeeded
  │
  └─ Return list of (state_summary, successful_tactic) pairs
```

The training data index is built lazily on first search invocation by scanning the JSON Lines files and constructing an in-memory symbol-set index. This is a one-time cost per server session.

Few-shot retrieval is optional. When no training data is available, the LLM prompt omits the few-shot section and candidate generation proceeds with proof state and premises only.

## Premise Retrieval Integration

When the Retrieval Pipeline (Semantic Lemma Search index) is available, the search engine retrieves premises at each search node:

```
retrieve_premises(proof_state)
  │
  ├─ Extract the focused goal type
  │
  ├─ Call search_by_type(goal_type, limit=20)
  │
  ├─ Call search_by_symbols(symbols_in_goal, limit=20)
  │
  ├─ Deduplicate and merge results (union, re-ranked by score)
  │
  └─ Return top-k premises (name, type, score)
```

Premises are cached per unique goal type — if two search nodes have the same focused goal, the cached premises are reused.

When the search index is not available (no database configured, or `INDEX_MISSING`), premise retrieval is skipped silently and candidate generation proceeds without premise context.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Session not found or expired | Return structured error immediately (no search attempted) |
| Backend crash during search | Return failure result with partial progress and `backend_crashed: true` flag |
| LLM API error during candidate generation | Skip LLM candidates for this node; continue with solver candidates only. If all nodes fail LLM generation, return failure with `llm_unavailable: true` flag |
| Timeout | Return failure result with best partial proof and stats |

## Design Rationale

### Why single-session search rather than multi-session

A pool of sessions (one per branch) would eliminate replay overhead but multiply memory consumption (one Coq process per branch). For the initial implementation, single-session search with replay is simpler, has bounded resource usage, and achieves the target throughput. Multi-session search can be added as an optimization if replay becomes the bottleneck.

### Why hash-based state deduplication rather than structural comparison

Cryptographic hashing is O(1) for lookup and O(n) for computation (where n is proof state size). Structural comparison is O(n) per pair, and checking against all previously seen states would be O(k*n) where k is the cache size. Hashing amortizes comparison cost and handles large caches efficiently.

### Why solver-first candidate ordering

Solver tactics are deterministic, fast (milliseconds), and free (no API call). Trying them first means mechanical sub-goals are discharged without any LLM cost. This is the same insight behind CoqHammer + Tactician complementarity: solvers handle the mechanical, LLMs handle the strategic.

### Why score by goal reduction rather than learned value function

A learned value function requires training data specific to the search task — (state, distance_to_proof_completion) pairs. This data does not exist for Coq. Goal reduction is a reasonable proxy (closing goals is progress) and requires no training. When training data becomes available (Phase 3 + evaluation), a learned value function can replace or augment the heuristic (R4-P2-2).
