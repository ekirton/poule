# Proof Search

Algorithmic best-first tree search over tactic candidates, with every candidate verified against Coq before the search expands further. Claude Code invokes proof search as a tool when it wants to automatically discharge a proof obligation — the tight explore-verify loop runs orders of magnitude faster than conversational back-and-forth.

---

## Problem

Claude Code, combined with the Proof Interaction Protocol and Semantic Lemma Search, already functions as a proof copilot: it reasons about tactics, retrieves lemmas, and submits tactics conversationally. But conversational proof search is slow — each tactic attempt requires a full LLM reasoning turn, user-visible output, and a round-trip through MCP. A proof that requires exploring 50 candidate tactics across 5 search depths would take minutes of visible back-and-forth.

What's needed is a tool that Claude Code invokes once and gets back either a complete verified proof or a structured failure report. The tool runs a tight internal loop — generate candidates, verify against Coq, backtrack, prune — evaluating hundreds of proof states in the time it takes Claude to produce a single conversational response.

## Solution

A best-first tree search that, given a proof session and current proof state:

1. Generates a set of candidate tactics for the current goal
2. Submits each candidate to Coq via the Proof Interaction Protocol
3. For candidates that succeed, scores the resulting proof state and adds it to the search frontier
4. Expands the most promising frontier node next
5. Terminates when all goals are closed (success) or the timeout/budget is exhausted (failure)

On success, the tool returns the complete proof script — every tactic and the proof state after each step — verified end-to-end against Coq. On failure, it returns the deepest partial proof achieved and the number of states explored, giving Claude enough context to adjust its strategy.

## Tactic Candidate Generation

Each search node generates candidates from multiple sources:

- **LLM-generated tactics**: Claude generates candidate tactics conditioned on the current proof state, local context, and any retrieved premises. When Semantic Lemma Search is available, relevant lemmas for the current goal are retrieved and included in the generation prompt — enabling candidates like `apply retrieved_lemma` or `rewrite retrieved_lemma` that the LLM might not produce from context alone.
- **Symbolic solver tactics**: Standard automation tactics (`auto`, `omega`, `lia`, CoqHammer's `sauto`) are included in the candidate set at every node. These are fast to verify and handle mechanical sub-goals without consuming LLM budget. When a solver tactic closes a sub-goal, the search avoids generating LLM candidates for that node entirely.
- **Few-shot augmented candidates**: When extracted training data (Phase 3) is available, similar proof states and their successful tactics are retrieved and included as few-shot context for LLM generation. This is optional — search works without training data, but benefits from it when available.

### Diversity Filtering

Before candidates are verified against Coq, near-duplicate candidates are filtered. Syntactically identical tactics are deduplicated; semantically equivalent tactics (e.g., `rewrite H` and `rewrite -> H`) are de-prioritized so the search budget is spent on genuinely different proof directions.

## Search Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| Timeout | 30 seconds | Wall-clock time limit for the entire search |
| Max depth | 10 | Maximum tactic sequence length |
| Max breadth | 20 | Maximum candidates expanded per node |

All parameters are configurable per invocation.

## State Caching

The search maintains a cache of explored proof states (keyed by a hash of the goal and hypothesis set). When two different tactic sequences reach the same proof state, the duplicate is detected and pruned — the search does not re-explore from a state it has already visited. This is critical for efficiency: in practice, many tactic sequences converge to the same intermediate state, and without caching the search would waste budget on redundant exploration.

## Failure Reporting

When search exhausts its budget without finding a complete proof, it returns:

- The deepest partial proof achieved (longest tactic sequence that made progress)
- Total states explored and unique states explored (after deduplication)
- The frontier at termination (open proof states that could be expanded with more budget)

This gives Claude enough information to explain to the user what was tried, where the search got stuck, and whether increasing the budget might help.

## Design Rationale

### Why best-first search

BFS-Prover (ACL 2025) demonstrated that best-first search with a strong policy model outperforms MCTS variants without requiring a separate value model. The policy model (Claude's tactic generation) implicitly encodes a value function through its ranking of candidates. This simplifies the architecture — no need to train or maintain a separate proof state evaluator.

### Why verify every candidate

Unverified tactic sequences are worthless — a single invalid tactic invalidates the entire sequence. Eager verification (verify before expanding) prunes the search tree early: a tactic that fails in Coq is never expanded, saving all downstream exploration. The cost is one Coq round-trip per candidate, but this is fast (10s–100s of milliseconds) compared to LLM generation time.

### Why interleave solvers with LLM candidates

CoqHammer + Tactician combined solve 56.7% of theorems (more than either alone). The complementarity is structural: LLMs are good at high-level strategy (which lemma to apply, which induction scheme to use) while solvers are good at mechanical discharge (arithmetic, propositional logic, first-order reasoning). Interleaving captures both strengths. Solver tactics are also much faster to verify than to generate via LLM, so they serve as cheap pruning at every node.

### Why this is a tool, not a conversational strategy

Claude Code could, in principle, perform proof search conversationally — generating tactics, submitting them, reasoning about results. But the overhead per step is high: each tactic requires an LLM reasoning turn (~1-3 seconds), visible output rendering, and MCP protocol overhead. A dedicated tool runs the same loop internally at ~50+ states per second, making search over hundreds of candidates feasible within a 30-second budget. The tool returns a single result that Claude can reason about and explain — the best of both worlds.

## Acceptance Criteria

### Best-First Proof Search

**Priority:** P0
**Stability:** Stable

- GIVEN a proof session with an open goal WHEN proof search is invoked THEN it explores a tree of tactic sequences using best-first search, verifying each candidate tactic against Coq before expanding further
- GIVEN a successful proof search WHEN the result is returned THEN it includes the complete verified proof script with each tactic and the proof state after each step
- GIVEN a proof search that does not find a complete proof within the timeout WHEN the result is returned THEN it includes the deepest partial proof achieved and the number of states explored

**Traces to:** R4-P0-1, R4-P0-2, R4-P0-3

### Search State Caching

**Priority:** P0
**Stability:** Stable

- GIVEN a proof search WHEN two different tactic sequences lead to the same proof state THEN the system recognizes the duplicate and does not re-explore from that state
- GIVEN a proof search with caching WHEN it completes THEN the total number of Coq verification calls is strictly less than the total number of candidate tactics considered

**Traces to:** R4-P0-6

### Configurable Search Parameters

**Priority:** P1
**Stability:** Stable

- GIVEN a proof search request with a specified maximum search depth WHEN search runs THEN it does not explore tactic sequences longer than the specified depth
- GIVEN a proof search request with a specified breadth limit WHEN search runs THEN it does not expand more than the specified number of candidate tactics at each node
- GIVEN a proof search request with a specified timeout WHEN the timeout elapses THEN search terminates and returns the best partial progress

**Traces to:** R4-P1-3

### Premise-Augmented Candidate Generation

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library database and a proof state WHEN proof search generates tactic candidates THEN relevant premises are retrieved and included as context for candidate generation
- GIVEN no indexed library database is available WHEN proof search generates candidates THEN candidates are generated using only the proof state and local context
- GIVEN retrieved premises WHEN candidates are generated THEN some candidates reference retrieved lemmas (e.g., `apply retrieved_lemma`, `rewrite retrieved_lemma`)

**Traces to:** R4-P0-7, R4-P0-8, R4-P0-9

### Neuro-Symbolic Interleaving

**Priority:** P1
**Stability:** Draft

- GIVEN a proof search node WHEN candidates are generated THEN the candidate set includes both LLM-generated tactics and invocations of symbolic solvers
- GIVEN a proof state that is dischargeable by `omega` or `auto` WHEN proof search encounters it THEN the solver tactic is tried and, if successful, used to close the sub-goal without an LLM call
- GIVEN a completed proof found by search WHEN it is inspected THEN it may contain a mix of LLM-generated and solver tactics

**Traces to:** R4-P1-1

### Diversity-Aware Candidate Selection

**Priority:** P1
**Stability:** Draft

- GIVEN a set of tactic candidates for a proof state WHEN candidates are selected for verification THEN near-duplicate candidates (syntactically or semantically equivalent) are filtered or de-prioritized
- GIVEN diversity-aware selection WHEN proof search completes THEN the explored tactic sequences cover a broader range of proof strategies compared to non-diverse selection

**Traces to:** R4-P1-2

### Few-Shot Context from Training Data

**Priority:** P1
**Stability:** Stable

- GIVEN extracted training data for a Coq project WHEN proof search generates candidates for a proof state THEN similar proof states and their successful tactics are retrieved and included as few-shot context
- GIVEN few-shot examples WHEN they are used THEN search success rate improves compared to search without few-shot context (measured on a held-out evaluation set)

**Traces to:** R4-P1-4
