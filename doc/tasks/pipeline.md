# Task: Query Processing Pipeline

## 1. Overview

Implement the end-to-end query processing pipeline that orchestrates the four MCP search tools: `search_by_structure`, `search_by_type`, `search_by_symbols`, and `search_by_name`. The pipeline sits between the MCP server (which handles input validation and response formatting) and the individual retrieval channels (WL kernel, TED, MePo, FTS5, Const Jaccard, collapse-match). It is responsible for:

- Parsing query Coq expressions into `ExprTree` form
- Normalizing queries (Coq normalization + CSE)
- Invoking the correct combination of channels for each search tool
- Computing fine-ranking weighted sums for structural candidates
- Fusing multi-channel results via RRF
- Isolating channel failures so partial results can still be returned

**Source specification**: `specification/pipeline.md`, with channel details in `specification/channel-wl-kernel.md`, `specification/channel-mepo.md`, `specification/channel-fts.md`, `specification/channel-ted.md`, `specification/channel-const-jaccard.md`, and `specification/fusion.md`.

---

## 2. Dependencies

The pipeline depends on every other component in the system. Implementation order matters.

### Must Be Implemented Before This Task

| Dependency | Specification | Reason |
|------------|--------------|--------|
| Data structures | `specification/data-structures.md` | `ExprTree`, `NodeLabel`, `ScoredResult`, `WlHistogram` types used throughout |
| Storage schema + read path | `specification/storage.md` | Pipeline reads WL vectors, symbol data, FTS5, and `constr_tree` BLOBs from SQLite |
| Coq normalization | `specification/coq-normalization.md` | `coq_normalize()` called in the query path |
| CSE normalization | `specification/cse-normalization.md` | `cse_normalize()` called in the query path |
| WL kernel channel | `specification/channel-wl-kernel.md` | `wl_histogram()`, `wl_screen()`, `cosine_similarity()` |
| TED channel | `specification/channel-ted.md` | `ted_similarity()`, `ted_rerank()` |
| Const Jaccard channel | `specification/channel-const-jaccard.md` | `extract_consts()`, `const_jaccard()` |
| MePo channel | `specification/channel-mepo.md` | `mepo_select()` |
| FTS5 channel | `specification/channel-fts.md` | FTS5 query execution and preprocessing |
| Fusion | `specification/fusion.md` | `rrf_fuse()`, `collapse_match()`, weighted-sum formulas |
| Extraction pipeline | `specification/extraction.md` | Must have a populated database to test against |

### Implemented Concurrently or After

| Component | Specification | Reason |
|-----------|--------------|--------|
| MCP server | `specification/mcp-server.md` | Calls the pipeline; can be wired up after pipeline functions exist |
| Query parsing | Unspecified (see feedback) | The Coq expression parsing interface is a dependency but has no spec; define a minimal interface and stub it |

---

## 3. Module Structure

```
src/
  coq_search/
    __init__.py
    pipeline/
      __init__.py              # re-exports the 4 search functions
      orchestrator.py          # top-level dispatch: search_by_structure, search_by_type, etc.
      structural.py            # structural scoring sub-pipeline (WL -> fine-rank)
      query_parser.py          # interface to Coq expression parsing (stub-able)
      errors.py                # pipeline-level error types
    channels/
      __init__.py
      wl_kernel.py             # WL histogram, cosine similarity, screening
      ted.py                   # Zhang-Shasha TED, ted_similarity, ted_rerank
      mepo.py                  # MePo iterative selection
      fts5.py                  # FTS5 query preprocessing and execution
      const_jaccard.py         # constant extraction, Jaccard similarity
      collapse_match.py        # collapse-match tree similarity
    fusion/
      __init__.py
      rrf.py                   # Reciprocal Rank Fusion
      fine_ranking.py          # weighted-sum metric fusion for structural candidates
    normalization/
      __init__.py
      coq_normalize.py         # Coq-specific tree adaptations
      cse_normalize.py         # Common Subexpression Elimination
    types/
      __init__.py
      expr_tree.py             # ExprTree, NodeLabel hierarchy
      results.py               # ScoredResult, FusedResult
      histograms.py            # WlHistogram type alias
    storage/
      __init__.py
      database.py              # SQLite connection, read-only access
      memory_index.py          # in-memory WL vectors, symbol index, freq table
      tree_store.py            # ExprTree BLOB deserialization from declarations
```

---

## 4. Implementation Steps

### Step 1: Define Pipeline Error Types

**File**: `src/coq_search/pipeline/errors.py`

```python
class PipelineError(Exception):
    """Base class for pipeline errors."""
    pass

class ParseError(PipelineError):
    """Query expression failed to parse."""
    def __init__(self, message: str):
        self.message = message

class DependencyError(PipelineError):
    """A required dependency (database, Coq parser) is unavailable."""
    def __init__(self, message: str):
        self.message = message

class ChannelError(Exception):
    """An individual channel raised an exception. Caught and logged by the pipeline."""
    def __init__(self, channel: str, cause: Exception):
        self.channel = channel
        self.cause = cause
```

These map to the error table in pipeline.md Section 7.

---

### Step 2: Define the Query Parser Interface

**File**: `src/coq_search/pipeline/query_parser.py`

Define an abstract interface for parsing a Coq expression string into an `ExprTree`. The actual implementation depends on the coq-lsp or SerAPI integration (which is unspecified -- see feedback). For now, define the contract and provide a stub.

```python
from typing import Protocol
from coq_search.types.expr_tree import ExprTree

class CoqParser(Protocol):
    def parse_expression(self, expr_str: str) -> ExprTree:
        """
        Parse a Coq expression string into a raw ExprTree.

        REQUIRES: expr_str is a non-empty string.
        ENSURES: Returns an ExprTree representing the parsed expression.
        RAISES: ParseError if the expression is syntactically invalid.
        """
        ...
```

Provide a `StubCoqParser` for testing that accepts a predefined mapping of expression strings to trees.

---

### Step 3: Implement the Structural Scoring Sub-Pipeline

**File**: `src/coq_search/pipeline/structural.py`

This is the core of `search_by_structure` and is also reused by `search_by_type`. It encapsulates steps 2-8 from pipeline.md Section 3.

```python
from dataclasses import dataclass
from coq_search.types.expr_tree import ExprTree
from coq_search.types.results import ScoredResult
from coq_search.storage.memory_index import MemoryIndex
from coq_search.storage.tree_store import TreeStore

@dataclass
class StructuralConfig:
    wl_depth: int = 3
    wl_top_n: int = 500
    ted_max_nodes: int = 50
    default_limit: int = 50

def run_structural_pipeline(
    query_tree: ExprTree,
    memory_index: MemoryIndex,
    tree_store: TreeStore,
    config: StructuralConfig = StructuralConfig(),
    limit: int = 50,
) -> list[ScoredResult]:
    """
    Execute the full structural scoring pipeline.

    Steps:
    1. Apply coq_normalize to query_tree
    2. Apply cse_normalize to normalized tree
    3. Compute WL histogram at h=config.wl_depth
    4. WL screen against library vectors (top config.wl_top_n)
    5. Retrieve candidate ExprTrees from tree_store
    6. For each candidate, compute fine-ranking metrics:
       - wl_cosine (already computed during screening)
       - ted_similarity (if both query and candidate <= ted_max_nodes)
       - collapse_match
       - const_jaccard
    7. Compute structural_score via weighted sum (fusion.md Section 4)
    8. Sort by structural_score descending
    9. Return top-limit results

    Channel errors in TED/collapse-match/Jaccard are caught and logged;
    the candidate gets a degraded score from remaining metrics.
    """
```

**Internal helper -- fine-rank a single candidate**:

```python
def _fine_rank_candidate(
    query_tree: ExprTree,
    candidate_tree: ExprTree,
    wl_cosine: float,
    query_node_count: int,
    candidate_node_count: int,
    ted_max_nodes: int,
) -> float:
    """
    Compute the structural_score for one candidate.

    If both trees have node_count <= ted_max_nodes:
      structural_score = 0.15 * wl_cosine
                       + 0.40 * ted_similarity
                       + 0.30 * collapse_match
                       + 0.15 * const_jaccard

    Otherwise:
      structural_score = 0.25 * wl_cosine
                       + 0.50 * collapse_match
                       + 0.25 * const_jaccard
    """
```

**Key implementation detail**: After WL screening returns `(decl_id, wl_cosine_score)` pairs, the pipeline must fetch the serialized `ExprTree` for each candidate from the `declarations.constr_tree` BLOB column via `tree_store`. This is up to 500 BLOB reads. Batch the reads in a single SQL query: `SELECT id, constr_tree FROM declarations WHERE id IN (?, ?, ...)`.

---

### Step 4: Implement the RRF Fusion Function

**File**: `src/coq_search/fusion/rrf.py`

```python
def rrf_fuse(
    ranked_lists: list[list[ScoredResult]],
    k: int = 60,
) -> list[ScoredResult]:
    """
    Reciprocal Rank Fusion.

    For each decl_id appearing in any ranked list:
      rrf_score = sum(1.0 / (k + rank) for each list containing decl_id)

    Returns results sorted by rrf_score descending.

    REQUIRES: Each ranked_list is ordered by the channel's scoring (rank 1 = best).
    ENSURES: Every decl_id from every input list appears exactly once in the output.
    """
```

---

### Step 5: Implement the Fine-Ranking Weighted Sum

**File**: `src/coq_search/fusion/fine_ranking.py`

```python
@dataclass
class FineRankWeights:
    """Weights for structural metric fusion."""
    # With TED (node_count <= 50)
    wl_with_ted: float = 0.15
    ted: float = 0.40
    collapse_with_ted: float = 0.30
    jaccard_with_ted: float = 0.15
    # Without TED (node_count > 50)
    wl_without_ted: float = 0.25
    collapse_without_ted: float = 0.50
    jaccard_without_ted: float = 0.25

def compute_structural_score(
    wl_cosine: float,
    ted_similarity: float | None,
    collapse_match_score: float,
    const_jaccard_score: float,
    weights: FineRankWeights = FineRankWeights(),
) -> float:
    """
    Weighted sum of structural metrics.

    If ted_similarity is None, uses the no-TED weight set.
    All input scores are clamped to [0.0, 1.0] before combination.
    """
```

---

### Step 6: Implement the Four Search Flow Orchestrators

**File**: `src/coq_search/pipeline/orchestrator.py`

This is the main entry point called by the MCP server.

#### 6a. `search_by_structure`

```python
def search_by_structure(
    expression: str,
    parser: CoqParser,
    memory_index: MemoryIndex,
    tree_store: TreeStore,
    limit: int = 50,
) -> list[ScoredResult]:
    """
    Structural similarity search.

    Flow:
    1. parser.parse_expression(expression) -> raw ExprTree
       - On ParseError: propagate to caller
    2. coq_normalize(raw_tree) -> normalized tree
       - If empty tree: return []
    3. cse_normalize(normalized_tree) -> cse_tree
       - If empty tree: return []
    4. run_structural_pipeline(cse_tree, memory_index, tree_store, limit=limit)
    5. Return results

    Error isolation: ParseError propagates. All other errors from
    normalization or channels are caught, logged, and produce empty
    or partial results.
    """
```

#### 6b. `search_by_type`

```python
def search_by_type(
    type_expr: str,
    parser: CoqParser,
    memory_index: MemoryIndex,
    tree_store: TreeStore,
    db: Database,
    limit: int = 50,
) -> list[ScoredResult]:
    """
    Multi-channel search by type expression.

    Flow:
    1. parser.parse_expression(type_expr) -> raw ExprTree
       - On ParseError: propagate to caller
    2. coq_normalize + cse_normalize -> normalized tree
    3. Channel 1 (structural): run_structural_pipeline(tree) -> structural_results
       - On channel failure: log, structural_results = []
    4. Channel 2 (MePo): extract_symbols(tree), mepo_select(symbols) -> mepo_results
       - On channel failure: log, mepo_results = []
    5. Channel 3 (FTS5): preprocess type_expr, fts5_query(db) -> fts5_results
       - On channel failure: log, fts5_results = []
    6. Collect non-empty result lists
       - If all empty: return []
    7. rrf_fuse([structural_results, mepo_results, fts5_results], k=60)
    8. Return top-limit results

    Error isolation: Each channel is wrapped in try/except. If a channel
    fails, it is excluded from RRF fusion. A warning is logged identifying
    the failed channel and the exception.
    """
```

#### 6c. `search_by_symbols`

```python
def search_by_symbols(
    symbols: list[str],
    memory_index: MemoryIndex,
    limit: int = 50,
) -> list[ScoredResult]:
    """
    Symbol-based search via MePo.

    Flow:
    1. mepo_select(symbols, memory_index.symbol_index,
                   memory_index.symbol_freq, p=0.6, c=2.4, max_rounds=5)
    2. Return top-limit results

    Note: The spec says "optionally compute Const Jaccard for top MePo
    results." For the initial implementation, skip Jaccard and return
    MePo results directly. Jaccard refinement can be added later if
    retrieval quality evaluation shows it improves results.
    """
```

#### 6d. `search_by_name`

```python
def search_by_name(
    pattern: str,
    db: Database,
    limit: int = 50,
) -> list[ScoredResult]:
    """
    Name search via FTS5.

    Flow:
    1. fts5_preprocess(pattern) -> fts5_query_string
       - Qualified name detection (contains '.'): split on '.' and '_', AND-join
       - Wildcard handling: preserve trailing '*' as FTS5 prefix token
       - Escape FTS5 special characters
    2. If fts5_query_string is empty: return []
    3. Execute FTS5 MATCH with BM25 weights (name=10.0, statement=1.0, module=5.0)
    4. Return results ordered by BM25 score, limited to `limit`
    """
```

---

### Step 7: Implement the Memory Index Loader

**File**: `src/coq_search/storage/memory_index.py`

The pipeline requires three in-memory data structures loaded at server startup (per mcp-server.md Section 8.1).

```python
@dataclass
class MemoryIndex:
    wl_vectors: dict[int, WlHistogram]       # decl_id -> histogram (h=3)
    node_counts: dict[int, int]              # decl_id -> node_count
    symbol_index: dict[str, set[int]]        # symbol -> set of decl_ids
    symbol_freq: dict[str, int]              # symbol -> frequency count
    decl_symbols: dict[int, list[str]]       # decl_id -> symbol list

    @classmethod
    def load_from_db(cls, db: Database) -> "MemoryIndex":
        """
        Load all in-memory structures from the database.

        Queries:
        1. SELECT decl_id, histogram FROM wl_vectors WHERE h = 3
        2. SELECT id, node_count, symbol_set FROM declarations
        3. SELECT symbol, freq FROM symbol_freq

        Build inverted symbol index from declarations.symbol_set.
        """
```

---

### Step 8: Implement the Tree Store

**File**: `src/coq_search/storage/tree_store.py`

Handles batch retrieval and deserialization of `ExprTree` BLOBs for fine ranking.

```python
class TreeStore:
    def __init__(self, db: Database):
        self._db = db

    def get_trees(self, decl_ids: list[int]) -> dict[int, ExprTree]:
        """
        Batch-retrieve and deserialize ExprTrees for the given declaration IDs.

        SQL: SELECT id, constr_tree FROM declarations WHERE id IN (...)
        Deserialization: pickle.loads(blob) for each non-NULL constr_tree.

        If deserialization fails for a candidate, log a warning and skip it.
        Returns a dict mapping decl_id -> ExprTree for successfully loaded trees.
        """

    def get_tree(self, decl_id: int) -> ExprTree | None:
        """Single-tree retrieval. Convenience wrapper around get_trees."""
```

---

### Step 9: Wire Up Channel Error Isolation

The pipeline spec requires that individual channel exceptions do not crash the pipeline (pipeline.md Section 7, row "Individual channel raises exception"). Implement this as a context manager or decorator.

**File**: `src/coq_search/pipeline/orchestrator.py` (add to existing)

```python
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

@contextmanager
def channel_guard(channel_name: str):
    """
    Context manager for channel error isolation.

    Usage:
        with channel_guard("MePo"):
            mepo_results = mepo_select(...)

    On exception: logs a warning with the channel name and exception,
    then yields control back with no results (caller handles the empty case).
    """
    try:
        yield
    except Exception as e:
        logger.warning("Channel %s failed: %s", channel_name, e, exc_info=True)
        raise ChannelError(channel_name, e)
```

In the orchestrator functions, use this pattern:

```python
structural_results = []
try:
    with channel_guard("structural"):
        structural_results = run_structural_pipeline(...)
except ChannelError:
    pass  # already logged; structural_results remains []
```

---

### Step 10: Implement Pipeline Initialization

**File**: `src/coq_search/pipeline/__init__.py`

```python
from coq_search.pipeline.orchestrator import (
    search_by_structure,
    search_by_type,
    search_by_symbols,
    search_by_name,
)

class Pipeline:
    """
    Facade that holds shared state (memory index, tree store, parser)
    and exposes the four search methods.

    Constructed once at server startup; methods called per-request.
    """

    def __init__(
        self,
        db: Database,
        parser: CoqParser,
    ):
        self.memory_index = MemoryIndex.load_from_db(db)
        self.tree_store = TreeStore(db)
        self.parser = parser
        self.db = db

    def search_by_structure(self, expression: str, limit: int = 50) -> list[ScoredResult]:
        return search_by_structure(expression, self.parser, self.memory_index, self.tree_store, limit)

    def search_by_type(self, type_expr: str, limit: int = 50) -> list[ScoredResult]:
        return search_by_type(type_expr, self.parser, self.memory_index, self.tree_store, self.db, limit)

    def search_by_symbols(self, symbols: list[str], limit: int = 50) -> list[ScoredResult]:
        return search_by_symbols(symbols, self.memory_index, limit)

    def search_by_name(self, pattern: str, limit: int = 50) -> list[ScoredResult]:
        return search_by_name(pattern, self.db, limit)
```

---

## 5. Testing Plan

### 5.1 Test Fixtures

**File**: `test/conftest.py` and `test/fixtures/`

Create a small synthetic index database with:
- 20-30 synthetic declarations with known names, types, symbols, and WL histograms
- Precomputed `constr_tree` BLOBs for a subset (to test fine ranking)
- A populated `declarations_fts` table
- A `symbol_freq` table consistent with the declarations

Include declarations designed to exercise specific scenarios:
- Identical trees (should score 1.0 on all structural metrics)
- Structurally similar trees (same shape, different constants)
- Completely unrelated trees
- Trees with >50 nodes (to test TED skip path)
- Declarations with overlapping symbol sets (for MePo testing)

### 5.2 Unit Tests

| Test File | Tests |
|-----------|-------|
| `test/pipeline/test_structural.py` | `run_structural_pipeline` with known query/candidate pairs; verify correct metric computation and ranking order |
| `test/fusion/test_rrf.py` | RRF with 1, 2, 3 input lists; empty lists; single-item lists; verify score computation matches spec examples |
| `test/fusion/test_fine_ranking.py` | Weighted sum with TED available; without TED; boundary values (0.0, 1.0); out-of-range clamping |
| `test/pipeline/test_query_parser.py` | Stub parser returns known trees; parser raises ParseError for invalid input |
| `test/storage/test_memory_index.py` | Load from fixture database; verify histogram, symbol index, freq table contents |
| `test/storage/test_tree_store.py` | Batch tree retrieval; handle missing BLOBs; handle deserialization failure |

### 5.3 Integration Tests (per search flow)

#### `test/pipeline/test_search_by_structure.py`

- **Happy path**: Known expression -> parse -> normalize -> WL screen -> fine-rank -> verify expected declarations appear in top results
- **Empty WL results**: Query with no structural matches -> returns empty list (not an error)
- **Parse failure**: Invalid expression -> `ParseError` propagates
- **Large query (>50 nodes)**: TED skipped, only collapse-match and Jaccard used in weighted sum

#### `test/pipeline/test_search_by_type.py`

- **Happy path (all channels)**: Expression with structural matches, symbol overlap, and name matches -> all three channels contribute -> RRF fused result ranks multi-channel hits highest
- **One channel fails**: Mock FTS5 to raise exception -> warning logged, WL + MePo results still fused via RRF (2 channels)
- **Two channels fail**: Only MePo succeeds -> single-list RRF (scores still valid)
- **All channels fail**: Returns empty list
- **Parse failure**: Propagates as `ParseError`

#### `test/pipeline/test_search_by_symbols.py`

- **Happy path**: Known symbol set -> MePo selects expected declarations
- **Empty symbols**: Returns empty list
- **Unknown symbols**: Symbols not in freq table treated as maximally rare (freq=1)

#### `test/pipeline/test_search_by_name.py`

- **Qualified name**: `"Nat.add_comm"` -> FTS5 query `"Nat" AND "add" AND "comm"` -> results include matching declarations
- **Natural language**: `"commutativity"` -> passed to FTS5 as-is
- **Empty query**: Returns empty list
- **FTS5 syntax error**: Returns `ParseError`

### 5.4 Channel Error Isolation Tests

**File**: `test/pipeline/test_error_isolation.py`

- Mock each channel to raise various exceptions (RuntimeError, ValueError, sqlite3.OperationalError)
- Verify the pipeline logs a warning and continues with remaining channels
- Verify the final result is non-empty when at least one channel succeeds
- Verify `ParseError` is NOT caught by channel isolation (it should propagate)
- Verify `DependencyError` (database failure) propagates to caller

### 5.5 End-to-End Tests

**File**: `test/e2e/test_pipeline_e2e.py`

Requires a real (small) Coq index. If the extraction pipeline is available:
- Build an index from a minimal `.vo` file set
- Run each search flow against the real index
- Verify results are non-empty and correctly formatted
- Verify known declarations (e.g., `Nat.add_comm`) appear for relevant queries

If extraction is not yet available, mark these tests as `@pytest.mark.skip(reason="requires extraction pipeline")`.

---

## 6. Acceptance Criteria

### Functional

1. `search_by_structure("forall n : nat, n + 0 = n")` returns a ranked list of structurally similar declarations, with `Nat.add_0_r` in the top results (given a stdlib index).
2. `search_by_type("forall n : nat, n + 0 = n")` returns RRF-fused results combining structural, symbol, and lexical channels.
3. `search_by_symbols(["Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"])` returns declarations using those symbols, ordered by MePo relevance.
4. `search_by_name("Nat.add_comm")` returns FTS5 results with `Coq.Arith.PeanoNat.Nat.add_comm` ranked first or near the top.
5. When a channel raises an exception during `search_by_type`, the pipeline logs a warning and returns results from the remaining channels.
6. When parsing fails, a `ParseError` is raised with the parser's error message.
7. Empty result lists are returned (not errors) when: WL screening finds 0 candidates, normalization produces an empty tree, all channels return 0 results, or the query has no extractable symbols.

### Structural

8. The `Pipeline` class can be instantiated with a database and parser, and exposes all four search methods.
9. Channel implementations are independent modules that can be tested in isolation.
10. The fine-ranking weighted sum uses the exact weights from fusion.md Section 4.
11. RRF uses k=60.
12. WL screening uses h=3, N=500.

### Non-Functional

13. All pipeline code is in `src/coq_search/pipeline/` and `src/coq_search/fusion/`.
14. Channel implementations are in `src/coq_search/channels/`.
15. All test files have at least one test per public function.

---

## 7. Risks and Mitigations

### Risk 1: Coq Expression Parsing Interface is Unspecified

The pipeline requires parsing user-provided Coq expression strings into `ExprTree` at query time. No specification exists for this interface (see `specification/feedback/pipeline.md`).

**Mitigation**: Define a `CoqParser` protocol (Step 2) and implement a `StubCoqParser` for testing. The protocol is narrow enough (one method) that integrating a real parser later is straightforward. The stub maps known expression strings to pre-built trees, enabling full pipeline testing without Coq.

### Risk 2: Candidate Tree Deserialization Performance

Fine ranking requires deserializing up to 500 `ExprTree` BLOBs from SQLite. Pickle deserialization of complex objects can be slow.

**Mitigation**: Batch SQL reads (single `WHERE id IN (...)` query). Profile deserialization early. If pickle is too slow, consider a custom binary format or MessagePack. The `TreeStore` abstraction isolates the deserialization strategy.

### Risk 3: Channel Integration Complexity

The `search_by_type` flow invokes 3 independent channels, each with its own error modes, and fuses their outputs. Subtle bugs in result format mismatches or rank ordering can degrade quality silently.

**Mitigation**: Define `ScoredResult` as the universal output type for all channels. Write integration tests that verify multi-channel fusion produces correct RRF scores against hand-computed examples (the spec provides concrete examples in fusion.md Section 6). Log the per-channel result count at INFO level so quality degradation from a silently-failing channel is visible.

### Risk 4: collapse-match Recursion Depth

The `collapse_match` algorithm in fusion.md is recursive over tree structure. Deeply nested trees (>200 levels) could cause stack overflow.

**Mitigation**: fusion.md specifies a recursion depth cap of 200, returning 0.0 beyond that. Implement this cap explicitly. Alternatively, convert to an iterative algorithm with an explicit stack.

### Risk 5: Weighted Sum Tuning

The fine-ranking weights (0.15/0.40/0.30/0.15 with TED, 0.25/0.50/0.25 without) are from the spec but may need tuning after evaluation against real queries.

**Mitigation**: Extract weights into `FineRankWeights` dataclass (Step 5) so they can be adjusted without code changes. Consider making them configurable via a config file in a future iteration.

### Risk 6: WL Size Filter May Be Too Aggressive

The 1.2x size ratio threshold for small queries filters out candidates that differ by more than 20% in node count. This may exclude relevant results for very small queries.

**Mitigation**: The threshold is implemented in the WL channel (not the pipeline), but the pipeline should be tested with small queries to verify recall is acceptable. If needed, the threshold can be relaxed or made query-size-dependent.
