# Task: Implement Fusion Module

## 1. Overview

Implement the fusion module that combines ranked results from multiple retrieval channels into a single ranked list. Two fusion mechanisms are required:

1. **Fine-ranking metric fusion**: Combines structural sub-channel scores (WL cosine, TED similarity, collapse-match, const Jaccard) into a single `structural_score` using a weighted sum. Two weight variants exist depending on whether TED is available.
2. **Reciprocal Rank Fusion (RRF)**: Combines independent ranked lists from different channels (e.g., structural, MePo, FTS5) into a final ranking without learned weights.

Additionally, this task implements the **collapse-match** similarity algorithm, which measures how well a query tree's structure appears within a candidate tree.

**Source specification**: `specification/fusion.md`

---

## 2. Dependencies

The following must be implemented (or at least have their interfaces defined) before this module:

| Dependency | Spec | What is needed |
|-----------|------|---------------|
| Data structures | `specification/data-structures.md` | `ExprTree`, `NodeLabel` classes, `ScoredResult` dataclass |
| Node label categories | `specification/channel-ted.md` (Section 4) | The `same_category` groupings used by both TED cost model and collapse-match |
| Const Jaccard | `specification/channel-const-jaccard.md` | `const_jaccard(tree1, tree2) -> float` interface (consumed, not implemented here) |
| WL kernel | `specification/channel-wl-kernel.md` | `wl_cosine` score interface (consumed, not implemented here) |
| TED | `specification/channel-ted.md` | `ted_similarity(tree1, tree2) -> float` interface (consumed, not implemented here) |

**No dependency on storage or MCP server.** This module is pure computation over in-memory data structures.

---

## 3. Module Structure

```
src/
  wily_rooster/
    fusion/
      __init__.py          # Re-exports public API
      rrf.py               # Reciprocal Rank Fusion
      fine_ranking.py      # Fine-ranking weighted sum
      collapse_match.py    # Collapse-match similarity algorithm
      categories.py        # same_category groupings (shared with TED)
test/
  test_fusion/
    __init__.py
    test_rrf.py
    test_fine_ranking.py
    test_collapse_match.py
    test_categories.py
```

---

## 4. Implementation Steps

### Step 1: Implement `categories.py` — Node Label Category Mapping

This module defines the `same_category` function shared between collapse-match and the TED cost model.

**File**: `src/wily_rooster/fusion/categories.py`

```python
from enum import Enum, auto

class NodeCategory(Enum):
    LEAF_CONSTANT = auto()   # LConst, LInd, LConstruct
    LEAF_VARIABLE = auto()   # LRel, LVar, LCseVar
    SORT = auto()            # LSort
    BINDER = auto()          # LProd, LLambda, LLetIn
    APPLICATION = auto()     # LApp
    ELIMINATION = auto()     # LCase, LProj
    RECURSION = auto()       # LFix, LCoFix
    INTEGER = auto()         # LInt (see feedback — not in spec, needs decision)

def node_category(label: NodeLabel) -> NodeCategory:
    """Return the category for a node label.

    Maps each NodeLabel variant to its category per the TED cost model
    (channel-ted.md Section 4).
    """
    ...

def same_category(label_a: NodeLabel, label_b: NodeLabel) -> bool:
    """Return True if two labels belong to the same category."""
    return node_category(label_a) == node_category(label_b)
```

**Implementation notes**:
- Use `isinstance` checks or a dispatch dict mapping label type to category.
- `LInt` is not mentioned in the TED cost model categories. Provisional decision: assign `LInt` to its own `INTEGER` category. Document this as a deviation and flag for review.
- `LCseVar` is listed under leaf variables in the TED cost model.

### Step 2: Implement `collapse_match.py` — Collapse-Match Similarity

**File**: `src/wily_rooster/fusion/collapse_match.py`

```python
def collapse_match(query: ExprTree, candidate: ExprTree, _depth: int = 0) -> float:
    """Compute collapse-match similarity between query and candidate trees.

    Measures how well the query tree structure can be found within the
    candidate tree. Asymmetric: a small query matching a subtree of a
    large candidate scores well.

    Returns a float in [0.0, 1.0].
    Caps recursion at depth 200, returning 0.0 beyond.
    """
    ...
```

**Algorithm (from spec pseudocode, annotated)**:

1. **Recursion depth guard**: If `_depth > 200`, return `0.0`.

2. **Both leaves**: If both `query` and `candidate` have no children:
   - If `same_category(query.label, candidate.label)`: return `1.0`
   - Else: return `0.0`

3. **Query is leaf, candidate is interior**: Return the maximum of `collapse_match(query, c, _depth + 1)` for each child `c` of `candidate`. If candidate has no children (should not happen for interior nodes per invariants, but guard anyway), return `0.0`.

4. **Candidate is leaf, query is interior**: Return `0.0`.

5. **Both interior**: If `not same_category(query.label, candidate.label)`: return `0.0`.

6. **Child matching**: For each query child `qc`, find the best-scoring candidate child `cc` (allowing reuse of candidate children):
   ```
   score = sum(max(collapse_match(qc, cc, _depth+1) for cc in candidate.children)
               for qc in query.children)
   ```

7. **Normalization**: Return `score / max(len(candidate.children), len(query.children))`.

**Critical implementation concerns**:

- **Recursion depth**: Thread `_depth` through every recursive call, incrementing by 1. Return `0.0` when `_depth > 200`.
- **Complexity**: The algorithm is O(|Qc| * |Cc|) per node pair, recursing into children. For trees within the 50-node TED threshold, this is bounded. For larger trees (used in the no-TED formula), consider adding a total-work counter or memoization if performance is a concern. Start without memoization; add if profiling shows it is needed.
- **Empty children on interior nodes**: Per data-structures.md invariants, interior nodes always have children. But defensively handle empty children by returning `1.0` if `same_category` holds (matching the spec's `matched == 0` branch).
- **Clamping**: The algorithm naturally produces values in [0, 1] if inputs are well-formed. Clamp the final result to [0.0, 1.0] as a safety measure.

### Step 3: Implement `fine_ranking.py` — Fine-Ranking Metric Fusion

**File**: `src/wily_rooster/fusion/fine_ranking.py`

```python
import logging

logger = logging.getLogger(__name__)

def clamp01(value: float) -> float:
    """Clamp a value to [0.0, 1.0]. Log warning if out of range."""
    if value < 0.0 or value > 1.0:
        logger.warning("Score %.6f out of [0,1] range, clamping", value)
    return max(0.0, min(1.0, value))


def structural_score_with_ted(
    wl_cosine: float,
    ted_similarity: float,
    collapse_match_score: float,
    const_jaccard: float,
) -> float:
    """Compute structural score when TED is available (node_count <= 50).

    Formula: 0.15 * wl_cosine + 0.40 * ted_similarity
           + 0.30 * collapse_match + 0.15 * const_jaccard

    All inputs are clamped to [0, 1] before computation.
    Output is clamped to [0, 1].
    """
    wl = clamp01(wl_cosine)
    ted = clamp01(ted_similarity)
    cm = clamp01(collapse_match_score)
    cj = clamp01(const_jaccard)
    score = 0.15 * wl + 0.40 * ted + 0.30 * cm + 0.15 * cj
    return clamp01(score)


def structural_score_without_ted(
    wl_cosine: float,
    collapse_match_score: float,
    const_jaccard: float,
) -> float:
    """Compute structural score when TED is skipped (node_count > 50).

    Formula: 0.25 * wl_cosine + 0.50 * collapse_match + 0.25 * const_jaccard

    All inputs are clamped to [0, 1] before computation.
    Output is clamped to [0, 1].
    """
    wl = clamp01(wl_cosine)
    cm = clamp01(collapse_match_score)
    cj = clamp01(const_jaccard)
    score = 0.25 * wl + 0.50 * cm + 0.25 * cj
    return clamp01(score)
```

**Verification**: The with-TED weights sum to 1.0 (0.15 + 0.40 + 0.30 + 0.15 = 1.0). The without-TED weights sum to 1.0 (0.25 + 0.50 + 0.25 = 1.0). Since all inputs are clamped to [0, 1] and weights sum to 1.0, the output is naturally in [0, 1]. The final clamp is a safety net.

### Step 4: Implement `rrf.py` — Reciprocal Rank Fusion

**File**: `src/wily_rooster/fusion/rrf.py`

```python
from dataclasses import dataclass


@dataclass
class FusedResult:
    decl_id: int
    rrf_score: float
    fused_rank: int  # 1-based, assigned after sorting


def rrf_fuse(
    ranked_lists: list[list[int]],
    k: int = 60,
) -> list[FusedResult]:
    """Combine multiple ranked lists using Reciprocal Rank Fusion.

    Each ranked list is a list of decl_ids ordered by rank (index 0 = rank 1).
    Returns FusedResult items sorted by rrf_score descending, with
    1-based fused_rank assigned.

    If all input lists are empty, returns an empty list.
    If a single list is provided, returns that list re-scored with RRF.
    """
    ...
```

**Algorithm**:

```
scores: dict[int, float] = {}
for channel_results in ranked_lists:
    for rank_idx, decl_id in enumerate(channel_results):
        rank = rank_idx + 1  # 1-based
        scores[decl_id] = scores.get(decl_id, 0.0) + 1.0 / (k + rank)

sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
return [FusedResult(decl_id=did, rrf_score=score, fused_rank=i+1)
        for i, (did, score) in enumerate(sorted_items)]
```

**Implementation notes**:
- `k` is always 60 per the spec. Accept it as a parameter with default for testability.
- Use plain `dict` accumulation. No numerical stability concerns since RRF scores are simple reciprocals.
- The function accepts `list[list[int]]` (decl_id lists). An alternative signature accepting `list[list[ScoredResult]]` may be useful for pipeline integration; provide both or adapt during pipeline integration.

### Step 5: Implement `__init__.py` — Public API

**File**: `src/wily_rooster/fusion/__init__.py`

```python
from .rrf import rrf_fuse, FusedResult
from .fine_ranking import (
    structural_score_with_ted,
    structural_score_without_ted,
    clamp01,
)
from .collapse_match import collapse_match
from .categories import same_category, node_category, NodeCategory

__all__ = [
    "rrf_fuse",
    "FusedResult",
    "structural_score_with_ted",
    "structural_score_without_ted",
    "clamp01",
    "collapse_match",
    "same_category",
    "node_category",
    "NodeCategory",
]
```

---

## 5. Testing Plan

### 5.1 Unit Tests for `same_category` (`test/test_fusion/test_categories.py`)

| Test case | Input | Expected |
|-----------|-------|----------|
| Same leaf constants | `LConst("a")`, `LInd("b")` | `True` |
| Same leaf constants | `LConst("a")`, `LConstruct("b", 0)` | `True` |
| Same leaf variables | `LRel(0)`, `LVar("x")` | `True` |
| Same leaf variables | `LRel(0)`, `LCseVar(1)` | `True` |
| Same binders | `LProd()`, `LLambda()` | `True` |
| Same binders | `LProd()`, `LLetIn()` | `True` |
| Same elimination | `LCase()`, `LProj("p")` | `True` |
| Same recursion | `LFix(0)`, `LCoFix(0)` | `True` |
| Cross category | `LConst("a")`, `LProd()` | `False` |
| Cross category | `LRel(0)`, `LConst("a")` | `False` |
| Cross category | `LApp()`, `LProd()` | `False` |
| Self category | `LApp()`, `LApp()` | `True` |
| Sort self | `LSort(SortKind.PROP)`, `LSort(SortKind.SET)` | `True` |
| LInt handling | `LInt(42)`, `LInt(7)` | `True` (provisional) |
| LInt cross | `LInt(42)`, `LConst("a")` | `False` |

### 5.2 Unit Tests for `collapse_match` (`test/test_fusion/test_collapse_match.py`)

**Test: Both leaves, same category**
- Query: `ExprTree(label=LConst("a"))`, Candidate: `ExprTree(label=LInd("b"))`
- Expected: `1.0`

**Test: Both leaves, different category**
- Query: `ExprTree(label=LConst("a"))`, Candidate: `ExprTree(label=LProd())`
- Expected: `0.0`

**Test: Query leaf, candidate interior — leaf matches a child**
- Query: `ExprTree(label=LConst("a"))`
- Candidate: `ExprTree(label=LProd(), children=[ExprTree(label=LInd("b")), ExprTree(label=LRel(0))])`
- Expected: `1.0` (LConst and LInd are same category)

**Test: Query leaf, candidate interior — no match**
- Query: `ExprTree(label=LApp())`
- Candidate: `ExprTree(label=LProd(), children=[ExprTree(label=LInd("b")), ExprTree(label=LRel(0))])`
- Expected: `0.0`

**Test: Candidate leaf, query interior**
- Query: `ExprTree(label=LProd(), children=[ExprTree(label=LInd("a"))])`
- Candidate: `ExprTree(label=LConst("b"))`
- Expected: `0.0`

**Test: Both interior, same category, perfect match**
- Query: `Prod(Ind("a"), Ind("b"))`
- Candidate: `Prod(Ind("c"), Ind("d"))`
- Expected: `1.0` (both children match same category, score = 2/max(2,2) = 1.0)

**Test: Both interior, different root category**
- Query: `App(Ind("a"), Ind("b"))`
- Candidate: `Prod(Ind("a"), Ind("b"))`
- Expected: `0.0` (LApp vs LProd are different categories)

**Test: Query smaller than candidate — partial match**
- Query: `Prod(Ind("a"))` (1 child)
- Candidate: `Prod(Ind("a"), Ind("b"), Ind("c"))` (3 children)
- Expected: `1.0 / max(3, 1) = 0.333...` (one query child matches, denominator is 3)

**Test: Recursion depth cap**
- Construct a linear chain tree of depth 250 (each node has one child).
- Expected: Returns `0.0` for the deepest comparisons; does not raise `RecursionError`.

**Test: Empty tree (edge case)**
- Both trees are leaf nodes with no children: covered by "both leaves" tests.

### 5.3 Unit Tests for Fine-Ranking (`test/test_fusion/test_fine_ranking.py`)

**Test: Spec example — with TED**
- Inputs: `wl_cosine=0.82`, `ted_similarity=0.65`, `collapse_match=0.71`, `const_jaccard=0.50`
- Expected: `0.671` (within floating-point tolerance, e.g., `abs(result - 0.671) < 1e-6`)

**Test: Spec example — without TED**
- Inputs: `wl_cosine=0.82`, `collapse_match=0.71`, `const_jaccard=0.50`
- Expected: `0.685` (within floating-point tolerance)

**Test: All zeros**
- All inputs `0.0`
- Expected: `0.0`

**Test: All ones**
- All inputs `1.0`
- Expected: `1.0`

**Test: Clamping — input out of range**
- Input: `wl_cosine=1.5`, others `0.0`
- Expected: `wl_cosine` clamped to `1.0` before multiplication. Warning logged.

**Test: Clamping — negative input**
- Input: `ted_similarity=-0.1`, others `1.0`
- Expected: `ted_similarity` clamped to `0.0`. Warning logged.

### 5.4 Unit Tests for RRF (`test/test_fusion/test_rrf.py`)

**Test: Spec example — 3 channels**
- Input:
  - WL: `[D1, D2, D3]`
  - MePo: `[D2, D4, D1]`
  - FTS5: `[D3, D1, D5]`
- Expected ranking: `[D1, D2, D3, D4, D5]`
- Expected scores (verify to 5 decimal places):
  - D1: `0.04839`
  - D2: `0.03252`
  - D3: `0.03226`
  - D4: `0.01613`
  - D5: `0.01587`

**Test: Empty input**
- Input: `[]`
- Expected: `[]`

**Test: All empty lists**
- Input: `[[], [], []]`
- Expected: `[]`

**Test: Single list**
- Input: `[[D1, D2, D3]]`
- Expected: `[D1, D2, D3]` with scores `1/61, 1/62, 1/63`

**Test: Single item in multiple lists**
- Input: `[[D1], [D1], [D1]]`
- Expected: `[D1]` with score `3 * 1/61`

**Test: Disjoint lists**
- Input: `[[D1], [D2]]`
- Expected: `[D1, D2]` or `[D2, D1]` (both have score `1/61`; order is stable by insertion)

### 5.5 Property-Based Tests (using Hypothesis)

**Property: RRF scores are always positive**
- For any non-empty ranked lists, all RRF scores are > 0.

**Property: RRF is order-independent across channels**
- `rrf_fuse([A, B, C])` produces the same scores as `rrf_fuse([C, A, B])`.

**Property: More channel appearances means higher or equal RRF score**
- If item X appears in all N channels and item Y appears in fewer channels, X's score >= Y's score (when ranks are equal).

**Property: Structural score is in [0, 1]**
- For any inputs in [0, 1], both `structural_score_with_ted` and `structural_score_without_ted` return a value in [0, 1].

**Property: collapse_match returns value in [0, 1]**
- For any two well-formed ExprTrees, `collapse_match` returns a float in [0.0, 1.0].

**Property: collapse_match(leaf, leaf) is 0 or 1**
- Two leaf nodes always produce exactly 0.0 or 1.0.

**Property: collapse_match is bounded by recursion depth**
- Trees of depth > 200 complete without RecursionError.

---

## 6. Acceptance Criteria

1. All spec examples produce the exact expected outputs (within floating-point tolerance of 1e-5).
2. `rrf_fuse` handles empty lists, single lists, and multi-channel lists correctly.
3. `structural_score_with_ted` and `structural_score_without_ted` return values in [0, 1] for all inputs in [0, 1].
4. Out-of-range inputs to fine-ranking functions are clamped and logged.
5. `collapse_match` returns values in [0, 1] for all valid tree pairs.
6. `collapse_match` does not raise `RecursionError` for trees of depth > 200.
7. `same_category` matches the TED cost model category definitions exactly.
8. All property-based tests pass for 1000+ examples.
9. The module has no external dependencies beyond the project's own data structures.
10. `categories.py` is importable by the TED cost model implementation (shared code, no duplication).

---

## 7. Risks and Mitigations

### Risk 1: Numerical stability in RRF

**Risk**: Floating-point addition order could cause non-deterministic tie-breaking.

**Mitigation**: RRF scores are simple reciprocals (1/(k+rank) with k=60 and rank typically 1-500), so values are in the range [~0.002, ~0.016]. Accumulation errors are negligible. For deterministic tie-breaking, use a secondary sort key (e.g., `decl_id` ascending) when RRF scores are equal.

### Risk 2: Recursion depth in collapse-match

**Risk**: Python's default recursion limit is 1000. The spec caps at 200, but each call level may invoke multiple recursive branches. Deep trees could still exceed Python's stack.

**Mitigation**: The `_depth` parameter tracks logical recursion depth (how many nested collapse_match calls), not Python stack depth. Since each level can fan out to `|Qc| * |Cc|` calls, the actual Python stack depth equals the tree depth (max 200), not the total call count. Python's default limit of 1000 is sufficient. Add a test with a depth-250 chain to verify.

### Risk 3: Exponential blowup in collapse-match for wide trees

**Risk**: For two trees with branching factor B and depth D, the call count is O(B^(2D)). Even with the 200-depth cap, very wide trees could cause slowness.

**Mitigation**: In practice, Coq expression trees are relatively narrow after currification (LApp is binary, LProd/LLambda have 2 children). The main risk is LCase nodes with many branches. For the initial implementation, proceed without memoization. Add timing instrumentation. If profiling shows hot spots, add memoization keyed on `(query.node_id, candidate.node_id)` pairs.

### Risk 4: Shared category definitions between fusion and TED

**Risk**: If `same_category` diverges between the fusion collapse-match and the TED cost model, scores become inconsistent.

**Mitigation**: Implement categories in a single shared module (`categories.py`) imported by both fusion and TED code. The TED task must import from `wily_rooster.fusion.categories` (or a shared location if refactored later).

### Risk 5: LInt not in spec categories

**Risk**: `LInt` nodes exist in the data model but have no assigned category in the TED cost model or collapse-match spec.

**Mitigation**: Provisional decision: assign `LInt` its own category (`INTEGER`). Flag for review. If `LInt` nodes are rare in practice (primitive integer literals in Coq), the impact is minimal.

### Risk 6: Spec ambiguity in collapse-match child matching semantics

**Risk**: The spec says "greedy left-to-right" but the pseudocode allows candidate child reuse. Implementing the wrong semantics would produce different scores.

**Mitigation**: Implement per the pseudocode (candidate children may be reused by multiple query children), since the pseudocode is authoritative over the prose description. Document the discrepancy (filed in `specification/feedback/fusion.md`). If the spec is updated to require true greedy matching, the change is localized to the inner loop of `collapse_match`.
