# Proof Search Engine

Algorithmic best-first tree search over tactic candidates with Coq verification, candidate generation from LLM and solver sources, state caching, and diversity filtering.

**Architecture**: [proof-search-engine.md](../doc/architecture/proof-search-engine.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [proof-types.md](../doc/architecture/data-models/proof-types.md)

---

## 1. Purpose

Define the proof search engine that, given an active proof session, executes best-first tree search over tactic candidates — generating candidates from LLM and solver sources, verifying each against Coq via the Proof Session Manager, caching explored states, filtering duplicate candidates, and returning a verified proof script or structured failure report.

## 2. Scope

**In scope**: Search algorithm (best-first tree search), search data model (SearchNode, SearchResult, ProofStep), candidate generation (LLM, solver, few-shot), premise retrieval integration, diversity filtering, state caching, scoring, timeout and budget enforcement, error handling.

**Out of scope**: MCP protocol handling (owned by mcp-server), session lifecycle management (owned by proof-session), premise retrieval logic (owned by retrieval-pipeline), proof state serialization (owned by proof-serialization), fill-admits orchestration (owned by fill-admits-orchestrator).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Search node | A node in the search tree, representing a proof state reachable by a specific tactic sequence from the root |
| Search frontier | The priority queue of unexpanded search nodes, ordered by score |
| Candidate | A tactic string generated for evaluation at a search node |
| State cache | A set of proof state hashes used to detect and prune duplicate states |
| Diversity filter | A pre-verification filter that removes near-duplicate candidates |
| Solver tactic | A deterministic Coq automation tactic (e.g., `auto`, `lia`) included alongside LLM candidates |
| Few-shot context | (state, tactic) pairs retrieved from extracted training data, included in the LLM prompt |

## 4. Behavioral Requirements

### 4.1 Search Entry Point

#### proof_search(session_id, timeout, max_depth, max_breadth)

- REQUIRES: `session_id` references an active proof session in the Proof Session Manager. `timeout` is a positive number (seconds), default 30. `max_depth` is a positive integer, default 10. `max_breadth` is a positive integer, default 20.
- ENSURES: Observes the current proof state. Executes best-first tree search. On success (all goals closed), returns a SearchResult with `status = "success"` and a complete verified proof script. On failure (timeout or frontier exhausted), returns a SearchResult with `status = "failure"`, the deepest partial proof, and search statistics.
- MAINTAINS: Every tactic in the returned proof script has been verified against Coq. No unverified tactics are included in any result.

> **Given** a proof session at a goal `n + 0 = n` with `n : nat` in context
> **When** `proof_search(session_id, timeout=30)` is called
> **Then** the engine explores candidates, and if `reflexivity` or `lia` closes the goal, returns a SearchResult with `status = "success"` and `proof_script` containing the successful tactic

> **Given** a proof session at a complex goal that cannot be solved within the timeout
> **When** `proof_search(session_id, timeout=5)` is called
> **Then** a SearchResult with `status = "failure"` is returned, containing the deepest partial proof and `states_explored > 0`

> **Given** a proof session at a goal that is already complete (`is_complete = true`)
> **When** `proof_search(session_id)` is called
> **Then** a SearchResult with `status = "success"` is returned with an empty proof script

### 4.2 Search Algorithm

The search engine shall implement best-first tree search:

1. The engine shall initialize the search frontier with a single root node containing the current proof state, depth 0, and score 1.0.
2. While the frontier is not empty and the deadline has not passed, the engine shall pop the highest-scoring node from the frontier.
3. When a node's depth equals `max_depth`, the engine shall skip the node without expansion.
4. The engine shall generate candidates for the popped node (see §4.3).
5. The engine shall filter candidates through the diversity filter (see §4.5).
6. The engine shall limit candidates to at most `max_breadth` after filtering.
7. For each candidate, the engine shall navigate the session to the node's position and submit the candidate tactic.
8. When a candidate tactic succeeds, the engine shall check the resulting proof state for completion (`is_complete = true`). On completion, the engine shall return success immediately with the complete tactic path.
9. When a candidate tactic succeeds but the proof is not complete, the engine shall compute a state hash and check the state cache. If the state is already in the cache, the engine shall skip it. Otherwise, the engine shall add the hash to the cache, score the new state (see §4.6), and push a new SearchNode to the frontier.
10. When a candidate tactic fails in Coq, the engine shall discard the candidate and continue with the next.

> **Given** a frontier with two nodes: node A (score 0.8, depth 2) and node B (score 0.5, depth 1)
> **When** the next expansion step occurs
> **Then** node A is expanded first (higher score)

> **Given** a node at depth equal to max_depth
> **When** it is popped from the frontier
> **Then** it is skipped without generating candidates

### 4.3 Candidate Generation

#### generate_candidates(proof_state, premises, few_shot_examples)

- REQUIRES: `proof_state` is a valid ProofState. `premises` is a list of (name, type) pairs (may be empty). `few_shot_examples` is a list of (state_summary, tactic) pairs (may be empty).
- ENSURES: Returns an ordered list of candidate tactic strings. Solver tactics appear first, followed by LLM-generated tactics.

**Solver candidates**: The engine shall include the following solver tactics at every search node, in this order:

```
auto, eauto, omega, lia, intuition, tauto, congruence, reflexivity, assumption, trivial
```

Solver tactics shall be tried before LLM candidates. When a solver tactic closes a sub-goal, the engine shall not generate LLM candidates for that node.

> **Given** a proof state where `reflexivity` succeeds
> **When** candidates are generated
> **Then** `reflexivity` is tried before any LLM candidates, succeeds, and no LLM API call is made

**LLM candidates**: The engine shall call the Claude API with a prompt containing:
- The current proof state (goals, hypotheses, local context)
- Retrieved premises (names and types), when available
- Few-shot examples (state/tactic pairs), when available
- Instructions to return one candidate tactic per line

- REQUIRES: The Claude API is reachable.
- ENSURES: The response is parsed into a list of tactic strings. Empty lines and malformed responses are discarded.
- On LLM API error: the engine shall continue with solver candidates only for this node. If all nodes in the search fail LLM generation, the SearchResult shall include `llm_unavailable = true`.

> **Given** a proof state with hypotheses `H : a = b` and retrieved premise `eq_sym : forall x y, x = y -> y = x`
> **When** LLM candidates are generated
> **Then** the prompt includes both `H` and `eq_sym`, and candidates may include `rewrite H` or `apply eq_sym`

> **Given** the Claude API returns a 500 error
> **When** LLM candidates are requested
> **Then** an empty LLM candidate list is returned and solver candidates are used for this node

### 4.4 Premise Retrieval

#### retrieve_premises(proof_state)

- REQUIRES: The Retrieval Pipeline is available (search index exists and is loaded).
- ENSURES: Returns a list of (name, type, score) triples for premises relevant to the focused goal.
- When the Retrieval Pipeline is not available: returns an empty list silently. No error is raised.

The engine shall query the Retrieval Pipeline with the focused goal's type:
1. Call `search_by_type(goal_type, limit=20)`.
2. Call `search_by_symbols(symbols_in_goal, limit=20)`.
3. Deduplicate by name (union), re-rank by maximum score.
4. Return the top 20 results.

Results shall be cached per unique goal type string. When two search nodes have the same focused goal type, the cached premises shall be reused.

> **Given** a search index with Coq standard library declarations
> **When** premises are retrieved for goal `forall n, n + 0 = n`
> **Then** results include `Nat.add_0_r` and other relevant arithmetic lemmas

> **Given** no search index is configured
> **When** premises are retrieved
> **Then** an empty list is returned and candidate generation proceeds without premises

### 4.5 Diversity Filter

#### filter_candidates(candidates)

- REQUIRES: `candidates` is a non-empty list of tactic strings.
- ENSURES: Returns a deduplicated and filtered list. Exact duplicates are removed (keep first occurrence). Tactics differing only in whitespace are collapsed. Tactics differing only in surface syntax (e.g., `rewrite H` vs `rewrite -> H`) are collapsed to the first variant. Among LLM-generated candidates, pairs with > 90% token overlap are collapsed to the first.
- MAINTAINS: The relative order of non-filtered candidates is preserved. Solver tactics are never filtered against LLM candidates.

> **Given** candidates `["auto", "auto", "rewrite H", "rewrite -> H", "apply lemma1"]`
> **When** the diversity filter runs
> **Then** the result is `["auto", "rewrite H", "apply lemma1"]`

> **Given** LLM candidates `["apply Nat.add_comm.", "apply Nat.add_comm ."]` (differ only in whitespace)
> **When** the diversity filter runs
> **Then** only one is retained

### 4.6 State Cache

The engine shall maintain a state cache mapping proof state hashes to a visited flag.

#### hash_proof_state(proof_state)

- REQUIRES: `proof_state` is a valid ProofState.
- ENSURES: Returns a cryptographic hash (SHA-256) of the proof state's mathematical content. The hash is computed by: sorting goals by their type string (order-independent), sorting each goal's hypotheses by name, concatenating all (goal_type, [(hyp_name, hyp_type), ...]) tuples, and hashing the concatenation.
- MAINTAINS: Two proof states with the same goals and hypotheses (regardless of goal order, step index, or session ID) produce the same hash. Two proof states with different goals or hypotheses produce different hashes (with cryptographic collision probability).

> **Given** two proof states with goals `[A, B]` and `[B, A]` and identical hypotheses
> **When** both are hashed
> **Then** the hashes are equal (goal order is normalized)

> **Given** two proof states with the same goals but different hypotheses
> **When** both are hashed
> **Then** the hashes are different

### 4.7 Scoring

#### score_node(node, root_state)

- REQUIRES: `node` is a SearchNode. `root_state` is the initial ProofState at the search root.
- ENSURES: Returns a non-negative float. Higher scores indicate more promising nodes.

The scoring function shall compute:

```
score = goal_reduction_weight * goal_progress + depth_penalty_weight * (1 / (1 + depth))
```

Where:
- `goal_progress` = `(root_goal_count - node_goal_count) / root_goal_count` (fraction of goals closed relative to root). When `root_goal_count = 0`, `goal_progress = 1.0`.
- `depth` = length of the tactic path from root to this node.
- `goal_reduction_weight` = 0.7 (provisional).
- `depth_penalty_weight` = 0.3 (provisional).

> **Given** a root state with 3 goals and a node at depth 2 with 1 goal
> **When** the node is scored
> **Then** `goal_progress = 2/3`, `depth_factor = 1/3`, `score = 0.7 * (2/3) + 0.3 * (1/3) = 0.567`

### 4.8 Session Navigation

When verifying a candidate at a search node, the engine shall navigate the proof session to the node's position:

1. Step backward to the root state (step 0).
2. Replay the node's `tactic_path` by submitting each tactic in sequence.
3. Submit the candidate tactic.

- MAINTAINS: After navigation, the session's `current_step` equals the node's depth. The proof state at `current_step` matches `node.proof_state`.
- When a replay tactic fails (should not happen for previously verified paths): the engine shall abort the current candidate and log the failure.

> **Given** a search node at depth 3 with tactic path `["intro n.", "induction n.", "simpl."]`
> **When** the engine navigates to this node
> **Then** the session is at step 3 and the proof state matches the node's state

### 4.9 Few-Shot Retrieval

#### retrieve_few_shot(proof_state, training_data_index, k)

- REQUIRES: `training_data_index` is a loaded in-memory index over extracted training data. `k` is a positive integer, default 5.
- ENSURES: Returns a list of at most `k` (state_summary, tactic) pairs, ranked by similarity to the given proof state.
- When no training data index is available: returns an empty list silently.

Similarity is computed as weighted Jaccard overlap over:
- Symbol sets (constants, inductives, constructors referenced in the proof state)
- Goal type token sets

The training data index shall be built lazily on first invocation by scanning JSON Lines files from Phase 3 extraction output and constructing an in-memory symbol-set index.

> **Given** training data containing a proof state with `Nat.add_comm` in context, solved by `rewrite Nat.add_comm`
> **When** few-shot retrieval is called with a proof state mentioning `Nat.add_comm`
> **Then** the (state, `rewrite Nat.add_comm`) pair is returned as a few-shot example

> **Given** no training data files are configured
> **When** few-shot retrieval is called
> **Then** an empty list is returned

## 5. Data Model

### SearchNode

| Field | Type | Constraints |
|-------|------|-------------|
| `proof_state` | ProofState | Required; the proof state at this node |
| `state_hash` | bytes | Required; SHA-256 hash of the proof state's mathematical content |
| `tactic_path` | ordered list of string | Required; tactic sequence from root to this node; empty for root |
| `depth` | non-negative integer | Required; equals `len(tactic_path)` |
| `score` | non-negative float | Required; priority in the search frontier |
| `parent` | reference to SearchNode or null | Null for root node |

### SearchResult

| Field | Type | Constraints |
|-------|------|-------------|
| `status` | `"success"` or `"failure"` | Required |
| `proof_script` | ordered list of ProofStep or null | Required on success; null on failure |
| `best_partial` | ordered list of ProofStep or null | Required on failure; the deepest tactic sequence that made progress; null on success |
| `states_explored` | non-negative integer | Required; total nodes popped from the frontier |
| `unique_states` | non-negative integer | Required; distinct proof states (after cache dedup) |
| `wall_time_ms` | non-negative integer | Required; wall-clock time of the search in milliseconds |
| `llm_unavailable` | boolean | Required; true when all LLM API calls failed during search |

### ProofStep

| Field | Type | Constraints |
|-------|------|-------------|
| `tactic` | string | Required; the tactic text |
| `state_before` | ProofState | Required; proof state before this tactic |
| `state_after` | ProofState | Required; proof state after this tactic |

## 6. Interface Contracts

### Proof Search Engine → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `observe_state`, `submit_tactic`, `step_backward` |
| Concurrency | Serialized — one tactic submission at a time per session |
| Error strategy | `TACTIC_ERROR` → discard candidate, continue search. `BACKEND_CRASHED` → abort search, return failure with `backend_crashed: true`. `SESSION_NOT_FOUND`/`SESSION_EXPIRED` → abort, return error. |
| Idempotency | Not required — search is stateful and non-retriable. A failed search leaves the session at an unspecified step. |

### Proof Search Engine → Retrieval Pipeline (optional)

| Property | Value |
|----------|-------|
| Operations used | `search_by_type`, `search_by_symbols` |
| Error strategy | Any error → silently return empty premises; search continues without premise augmentation |
| Caching | Results cached per goal type string for the duration of one search invocation |

### Proof Search Engine → Claude API

| Property | Value |
|----------|-------|
| Operations used | Chat completions with system and user messages |
| Error strategy | API error → return empty LLM candidates for this node; search continues with solver candidates. Set `llm_unavailable = true` in result if all nodes failed. |
| Timeout | Per-request timeout of 10 seconds (does not consume the search timeout budget directly, but wall-clock time counts toward the overall search timeout) |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Behavior |
|-----------|----------|
| `session_id` references a non-existent session | Return `SESSION_NOT_FOUND` error immediately |
| `session_id` references an expired session | Return `SESSION_EXPIRED` error immediately |
| `timeout` ≤ 0 | Clamp to 1 second |
| `max_depth` ≤ 0 | Clamp to 1 |
| `max_breadth` ≤ 0 | Clamp to 1 |

### 7.2 Dependency Errors

| Condition | Behavior |
|-----------|----------|
| Coq backend crashes during search | Abort search, return SearchResult with `status = "failure"` and partial progress |
| Claude API returns errors for all nodes | Return SearchResult with `status = "failure"` and `llm_unavailable = true` |
| Retrieval Pipeline unavailable | Continue without premises (graceful degradation) |
| Training data unavailable | Continue without few-shot context (graceful degradation) |

### 7.3 Search Termination

| Condition | Behavior |
|-----------|----------|
| All goals closed | Return `status = "success"` with complete proof script |
| Wall-clock timeout exceeded | Return `status = "failure"` with best partial proof and stats |
| Frontier exhausted (queue empty) | Return `status = "failure"` with best partial proof and stats |
| All candidates at all frontier nodes fail verification | Return `status = "failure"` with stats showing `states_explored > 0` but `unique_states = 0` beyond root |

## 8. Non-Functional Requirements

- The engine shall explore ≥ 50 unique proof states per second (excluding LLM API latency).
- State hashing shall complete in < 1 ms per proof state.
- The state cache shall support at least 10,000 entries without degradation.
- The engine shall not allocate more than 100 MB of memory for the state cache and search frontier combined.
- The engine shall operate without a GPU; LLM calls use hosted APIs.

## 9. Examples

### Successful search — simple goal

```
proof_search(session_id="abc123", timeout=30, max_depth=10, max_breadth=20)

Initial state: ⊢ 0 + 0 = 0

Search:
  Node 0 (root): state_hash=h0, depth=0, score=1.0
    Solver candidates tried: auto → fail, reflexivity → SUCCESS (is_complete=true)

Result:
{
  "status": "success",
  "proof_script": [
    {"tactic": "reflexivity.", "state_before": {..., "goals": [{"type": "0 + 0 = 0"}]}, "state_after": {..., "is_complete": true, "goals": []}}
  ],
  "states_explored": 1,
  "unique_states": 1,
  "wall_time_ms": 45,
  "llm_unavailable": false
}
```

### Failed search — timeout

```
proof_search(session_id="def456", timeout=5, max_depth=10, max_breadth=20)

Initial state: ⊢ complex_theorem

Search:
  Explored 250 nodes, 180 unique states
  Deepest partial: 4 tactics, 1 of 3 goals closed
  Timeout at 5000ms

Result:
{
  "status": "failure",
  "proof_script": null,
  "best_partial": [
    {"tactic": "intros.", ...},
    {"tactic": "induction n.", ...},
    {"tactic": "simpl.", ...},
    {"tactic": "rewrite IHn.", ...}
  ],
  "states_explored": 250,
  "unique_states": 180,
  "wall_time_ms": 5000,
  "llm_unavailable": false
}
```

### Degraded search — LLM unavailable

```
proof_search(session_id="ghi789", timeout=30)

Claude API returns 503 for all requests.
Search proceeds with solver candidates only.

Result:
{
  "status": "failure",
  "proof_script": null,
  "best_partial": [...],
  "states_explored": 10,
  "unique_states": 8,
  "wall_time_ms": 1200,
  "llm_unavailable": true
}
```

## 10. Language-Specific Notes (Python)

- Use `asyncio` for the search loop to enable async tactic submission via the session manager.
- Use `heapq` (negated scores) for the priority queue, or a dedicated priority queue implementation with O(log n) push/pop.
- Use `hashlib.sha256` for state hashing.
- Use the `anthropic` Python SDK for Claude API calls.
- LLM prompt construction and response parsing should be isolated in a `CandidateGenerator` class for testability and future backend pluggability (R4-P2-1).
- State cache: `set` of `bytes` (SHA-256 digests).
- Premise cache: `dict` mapping goal type string to list of (name, type, score).
- Package location: `src/poule/search/`.
- Entry point: `async def proof_search(session_manager, session_id, timeout, max_depth, max_breadth, retrieval_pipeline=None, training_data_path=None) -> SearchResult`.
