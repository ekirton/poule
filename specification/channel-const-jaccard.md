# Const Name Jaccard Channel

Lightweight structural similarity based on Jaccard similarity of constant name sets.

**Architecture**: [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) § Fine-Ranking Metric Fusion

---

## 1. Purpose

Define the Const Jaccard channel that computes similarity between two declarations based on the overlap of their constant/inductive/constructor name sets. This is a fast, complementary metric used in fine-ranking alongside WL cosine, TED, and collapse matching.

## 2. Scope

**In scope**: Constant name extraction from expression trees, Jaccard similarity computation, batch scoring against candidates.

**Out of scope**: Symbol weighting (owned by MePo channel), fusion weights (owned by fusion), tree normalization.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Constant set | The set of fully qualified names from `LConst`, `LInd`, and `LConstruct` nodes in an expression tree |
| Jaccard similarity | `|A ∩ B| / |A ∪ B|`; 0.0 when both sets are empty |

## 4. Behavioral Requirements

### 4.1 Constant Extraction

#### extract_consts(tree)

- REQUIRES: `tree` is a valid `ExprTree`.
- ENSURES: Returns a `set[str]` of fully qualified names from all `LConst`, `LInd`, and `LConstruct` nodes. For `LConstruct`, the name is the parent inductive FQN (already stored in the label's `name` field).

This function is shared with the MePo channel (`extract_symbols` is equivalent to `extract_consts`).

### 4.2 Jaccard Similarity

#### jaccard_similarity(set_a, set_b)

- REQUIRES: Both arguments are sets of strings.
- ENSURES: Returns `|set_a ∩ set_b| / |set_a ∪ set_b|` as a float in [0.0, 1.0]. Returns 0.0 when both sets are empty.

### 4.3 Batch Scoring

#### const_jaccard_rank(query_tree, candidates, declaration_symbols)

- REQUIRES: `query_tree` is a valid `ExprTree`. `candidates` is a list of declaration IDs. `declaration_symbols` maps `decl_id → set[str]` (preloaded from storage).
- ENSURES: Returns `(decl_id, jaccard_score)` pairs for all candidates.

The query's constant set is extracted once and compared against each candidate's precomputed symbol set.

**Pre-computed symbol sets**: During indexing, `declarations.symbol_set` stores the same set that `extract_consts` would produce. At query time, the pipeline uses the stored symbol sets rather than deserializing and re-extracting from trees.

## 5. Error Specification

| Condition | Outcome |
|-----------|---------|
| Empty query constant set | All candidates receive score 0.0 |
| Candidate missing from `declaration_symbols` | Candidate receives score 0.0 |

No errors are raised. Edge cases produce zero scores.

## 6. Examples

### Identical symbol sets

Given: `set_a = {"Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"}`, `set_b = {"Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"}`

When: `jaccard_similarity(set_a, set_b)` is called

Then: `2 / 2 = 1.0`

### Partial overlap

Given: `set_a = {"Nat.add", "Nat.mul"}`, `set_b = {"Nat.add", "Nat.sub"}`

When: `jaccard_similarity(set_a, set_b)` is called

Then: `1 / 3 ≈ 0.333`

### No overlap

Given: `set_a = {"Nat.add"}`, `set_b = {"Bool.andb"}`

When: `jaccard_similarity(set_a, set_b)` is called

Then: `0 / 2 = 0.0`

## 7. Language-Specific Notes (Python)

- Use Python `set` operations: `&` for intersection, `|` for union.
- Package location: `src/wily_rooster/channels/`.
