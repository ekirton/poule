# Semantic Search for Coq/Rocq Libraries

The core feature: natural-language and structural search over Coq/Rocq libraries, mediated by an LLM via MCP.

---

## Problem

Coq/Rocq has no semantic search for its libraries. Users are limited to the built-in `Search` command, which requires knowing the approximate syntactic shape of what they seek. Lean has six search tools; Coq has zero.

A Coq developer looking for "a lemma about commutativity of addition on natural numbers" has no way to find it without already knowing its name (`Nat.add_comm`) or its type shape (`forall n m, n + m = m + n`).

## Solution

A tree-based structural search system that indexes Coq library declarations and exposes them via both MCP tools (for LLM-mediated retrieval) and standalone CLI commands (for direct terminal use). The system combines multiple retrieval channels — structural, symbolic, and lexical — to maximize recall. In the MCP path, the LLM reasoning layer provides precision, filtering, and explanation. In the CLI path, results are presented directly to the user.

## Design Rationale

### Why tree-based methods first

1. **No training data required.** Coq lacks the premise annotation datasets that neural methods need. Tree-based methods work on the raw expression structure, deployable immediately on any Coq library.

2. **High recall as a design goal.** The first pass should cast a wide net. The LLM reasoning layer (via MCP) provides the sophistication to filter and rank results. We optimize for recall/sensitivity at the retrieval stage, not precision.

3. **Baseline for comparison.** Before investing in embeddings, fine-tuned models, or graph neural networks, we need a training-free baseline to measure against. If tree-based retrieval + LLM filtering proves sufficient for the target use cases, more complex methods may be unnecessary.

4. **Complementary to future methods.** Tree-based retrieval captures structural similarity that embedding models miss. Research on Lean shows that combining structural and neural methods outperforms either alone, so structural methods remain valuable even when neural methods are added later.

### Why MCP + LLM

The LLM is the ranking and reasoning layer, not just a reranker.

In offline testing, Claude (Opus) demonstrated the ability to:
- Read a Coq lemma statement and explain what it does in natural language
- Answer questions about a lemma's applicability to a given goal
- Identify when two lemmas are semantically related despite syntactic dissimilarity
- Reformulate a vague user query into precise structural or symbolic searches

This means the retrieval engine does not need to be precise — it needs **high recall**. The LLM handles:

- **Query formulation**: User says "something about lists being equal when reversed twice." The LLM translates this into multiple search tool calls: `search_by_symbols(["rev", "app", "list"])`, `search_by_name("*rev*inv*")`, `search_by_type("forall l, rev (rev l) = l")`.
- **Result filtering**: Of 50 candidates from structural search, the LLM reads the statements and selects the 3-5 actually relevant ones.
- **Explanation**: The LLM explains *why* each result is relevant, in the context of what the user is trying to do.
- **Iterative refinement**: If the first search doesn't find it, the LLM reformulates — follows dependency links, broadens symbol sets, tries different structural patterns.

This is qualitatively different from LLM-as-reranker (where the LLM just scores relevance). The LLM's value is in intent interpretation, query reformulation, and conversational explanation — not relevance scoring.

### Why LLM reasoning, not LLM reranking

Voyage AI's benchmarks (October 2025) found that purpose-built rerankers are 25-60x cheaper, up to 48x faster, and 12-15% more accurate than LLMs at relevance scoring. When paired with strong first-stage retrieval, LLM reranking actually *degraded* performance.

However, the LLM's value in this system is not relevance scoring — it is intent interpretation, query reformulation, and conversational explanation. These are capabilities no reranker provides. The architecture exploits what the LLM is uniquely good at (reasoning about what the user needs) while avoiding what it is bad at (efficient relevance scoring at scale).

## Scope Boundaries

This system is **not**:

- **A premise selection tool** (though it could become one). Premise selection operates on proof states and feeds into automated proving. This system operates on user queries and feeds into human understanding.
- **A neural retrieval system**. No embeddings, no training. The tree-based methods are the retrieval engine; the LLM is the intelligence layer.
- **A replacement for `Search`**. Coq's `Search` command does exact syntactic matching, which remains useful. This system provides the *semantic* search that `Search` cannot do.

## Success Criteria

1. **Recall**: On a hand-curated set of (query, relevant lemma) pairs from common Coq workflows, the retrieval stage (before LLM filtering) should surface the relevant lemma in the top-50 at least 70% of the time.
2. **Latency**: First-pass retrieval completes in <1 second for a library of 50K declarations.
3. **Usability**: A user in Claude Code can describe what they need in natural language and get a useful, explained result within one conversational turn.
4. **Zero-config deployment**: Index the standard library with a single command. No GPU, no external services, no API keys (beyond Claude Code itself for the MCP path).
5. **CLI access**: All search capabilities available as standalone CLI commands for terminal workflows without Claude Code.

## Acceptance Criteria

### Multi-Channel Fusion

**Priority:** P0
**Stability:** Stable

- GIVEN a search query WHEN retrieval executes THEN all applicable retrieval channels (structural, symbolic, lexical) are engaged
- GIVEN results from multiple channels WHEN fusion is applied THEN items appearing in multiple channels rank higher than items from a single channel

### Recall Target

**Priority:** P0
**Stability:** Stable

- GIVEN a hand-curated evaluation set of (query, relevant lemma) pairs from common Coq workflows WHEN the retrieval pipeline is evaluated THEN the system achieves ≥ 70% recall@50
- GIVEN ongoing development WHEN retrieval changes are made THEN recall metrics are tracked and reported

### Latency Target

**Priority:** P0
**Stability:** Stable

- GIVEN an index of up to 50K declarations WHEN any search tool is called THEN retrieval completes in < 1 second
- GIVEN latency measurement WHEN it is taken THEN it covers end-to-end from MCP tool call receipt to response
