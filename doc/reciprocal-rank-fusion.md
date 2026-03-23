# Hybrid Retrieval via Reciprocal Rank Fusion for Coq Premise Selection

## 1. Introduction

Premise selection for Coq requires multiple complementary retrieval signals. No single channel dominates: structural similarity misses name-based connections, symbol overlap misses shape-based relationships, and lexical search misses both. Empirically, LeanHammer's union of neural and symbolic selection improves results by 21% over either alone (Mikula et al., 2025), and Rango demonstrates that BM25 lexical retrieval beats dense embeddings by 46% for in-project Coq proof retrieval (Thompson et al., 2025). These findings motivate a multi-channel pipeline where each channel contributes an independent ranked list, and a fusion algorithm combines them into a single ranking.

This document describes the symbolic retrieval pipeline — the four channels that operate without learned embeddings — and the Reciprocal Rank Fusion (RRF) algorithm that combines their outputs. It then addresses the empirical optimization of RRF's smoothing constant *k*, which controls how aggressively the fusion weights top-ranked results.

## 2. Retrieval Channels

### 2.1 Weisfeiler-Lehman (WL) Kernel Screening

The WL kernel (Shervashidze et al., 2011) computes a fixed-length histogram for each declaration's type expression tree by iterative neighborhood hashing. At each of *h* = 3 iterations, every node's label is replaced by a hash of its current label concatenated with its sorted children's labels. The resulting histogram counts label occurrences across all nodes and iterations. Retrieval computes the cosine similarity between the query histogram and each candidate's precomputed histogram via sparse dot product.

**Signal.** Tree structure patterns up to depth 3. Two declarations with similar recursive structure — even if they name different constants — produce similar histograms.

**Strengths.** Sub-second screening over 100K+ declarations from precomputed histograms stored in the index. No training data required; fully deterministic.

**Limitations.** Insensitive to node identity beyond hash collisions. Cannot capture semantic relationships that lack structural similarity.

### 2.2 Tree Edit Distance (TED)

The Zhang-Shasha algorithm (Zhang and Shasha, 1989) computes the minimum-cost sequence of node insertions, deletions, and renames to transform one tree into another. The cost model is asymmetric: leaf nodes (variables, constants, sorts) cost 0.2 to insert or delete, while interior nodes (application, lambda, product) cost 1.0 — reflecting that interior nodes carry more structural information. Rename cost is 0.0 for identical labels, 0.4 for cross-category renames. Similarity is defined as:

$$\text{ted\_similarity}(T_1, T_2) = \max\!\Big(0,\; 1 - \frac{\text{edit\_distance}(T_1, T_2)}{\max(|T_1|, |T_2|)}\Big)$$

TED is applied only when both trees have ≤ 50 nodes, due to the O(n²m²) worst-case complexity of the Zhang-Shasha algorithm.

**Signal.** Precise structural distance at the node level. The most discriminative structural metric when applicable.

**Limitations.** Computationally expensive for large trees. No semantic understanding of node labels.

### 2.3 Meng-Paulson (MePo) Symbol Overlap

MePo (Meng and Paulson, 2009) ranks declarations by iterative breadth-first symbol overlap. Symbols (constants, inductives, constructors) are weighted by inverse frequency: *w*(*s*) = 1 + 2/log₂(freq + 1), so rare symbols are more discriminating. Each round selects declarations whose relevance — the ratio of weighted shared symbols to total weighted symbols — exceeds a decaying threshold (0.6 × (1/2.4)^round). Selected declarations' symbols are added to the working set, expanding the search transitively over up to 5 rounds.

**Signal.** Shared mathematical objects, transitively expanded. A query mentioning `Category` (rare) is more discriminating than one mentioning `nat` (common).

**Strengths.** Fast (<200ms for 100K declarations with an inverted index). Strong baseline: MePo achieves 42.1% Recall@32 on Lean's Mathlib. Well-established heuristic used in CoqHammer and Sledgehammer.

**Limitations.** Misses semantically related declarations that use entirely different symbols.

### 2.4 FTS5 Lexical Search

SQLite FTS5 provides full-text search with Porter stemming and BM25 ranking. Queries are preprocessed: dotted identifiers (e.g., `List.map`) are split on `.` and AND-joined; underscored identifiers are treated as single tokens. BM25 column weights emphasize declaration names (10.0) over module paths (5.0) and statement text (1.0).

**Signal.** Keyword-level text matching on names, statements, and module paths. Handles the common case where users search by name fragment.

**Strengths.** Fast (<10ms per query). Effective fallback when structural and symbolic channels miss.

**Limitations.** No structural or semantic understanding beyond lexical overlap.

## 3. Structural Fine-Ranking

The structural channel is itself a composite. After WL screening selects the top candidates, four metrics are combined via a weighted sum to produce a single structural score per candidate:

**With TED** (both trees ≤ 50 nodes):

| Metric | Weight |
|--------|--------|
| WL cosine similarity | 0.15 |
| TED similarity | 0.40 |
| Collapse match | 0.30 |
| Constant Jaccard | 0.15 |

**Without TED** (either tree > 50 nodes):

| Metric | Weight |
|--------|--------|
| WL cosine similarity | 0.25 |
| Collapse match | 0.50 |
| Constant Jaccard | 0.25 |

Collapse match is a recursive structural comparison that scores node-pair agreement (1.0 for identical category and label, 0.5 for same category with different label, 0.0 for different categories). Constant Jaccard measures the overlap of referenced constant names between two trees.

This composite structural score produces a single ranked list — the "structural channel" — which is then fed into RRF alongside MePo and FTS5.

## 4. Reciprocal Rank Fusion

Reciprocal Rank Fusion (Cormack et al., 2009) combines multiple ranked lists into a single ranking without requiring score calibration across channels. Each channel contributes to a declaration's fused score based solely on its rank position:

$$\text{RRF}(d) = \sum_{c \in \text{channels}} \frac{1}{k + \text{rank}_c(d)}$$

where rank_c(*d*) is the 1-based rank of declaration *d* in channel *c*'s list. Declarations absent from a channel's list contribute 0 for that channel. The fused list is sorted by RRF score descending.

### 4.1 The Smoothing Constant *k*

The parameter *k* controls how aggressively RRF favors top-ranked results:

- **Small *k*** (e.g., *k* = 1): the score difference between rank 1 and rank 10 is large (1/2 vs 1/11). Top ranks dominate.
- **Large *k*** (e.g., *k* = 100): the score difference between rank 1 and rank 10 is small (1/101 vs 1/110). Contributions are more uniform across ranks.

The current value *k* = 60 is the standard choice from the information retrieval literature (Cormack et al., 2009).

### 4.2 Channels Fused

The `search_by_type` tool fuses three or four ranked lists via RRF:

1. **Structural** — composite score from §3
2. **Symbol overlap** — MePo selection from §2.3
3. **Lexical** — FTS5 search from §2.4
4. **Neural** — bi-encoder cosine similarity (when a trained model is available)

### 4.3 Worked Example

Given two channels with *k* = 60:

```
Channel A: [d1 (rank 1), d2 (rank 2), d3 (rank 3)]
Channel B: [d2 (rank 1), d3 (rank 2), d4 (rank 3)]

d1: 1/(60+1)                     = 0.0164
d2: 1/(60+2) + 1/(60+1)          = 0.0161 + 0.0164 = 0.0325
d3: 1/(60+3) + 1/(60+2)          = 0.0159 + 0.0161 = 0.0320
d4:            1/(60+3)           = 0.0159

Fused ranking: [d2, d3, d1, d4]
```

Declaration d2 ranks highest because it appears in both channels. The fusion naturally rewards declarations that are relevant across multiple independent signals.

## 5. Optimizing *k* and Per-Channel Weights

### 5.1 Motivation

The value *k* = 60 is a literature default, not an empirically validated choice for Coq premise retrieval. Research on fusion functions for hybrid retrieval (Bruch et al., 2022) demonstrates that RRF is sensitive to *k*: sweeping *k* from 1 to 100 causes multi-point swings in NDCG@1000 and Recall@*K*, and values tuned on one domain generalize poorly to others. The recommended practical range is *k* ≈ 46–60, but domain-specific optimization is necessary.

For Coq premise selection specifically, the channels have distinctive rank distributions — MePo tends to produce short, high-confidence lists while WL screening produces longer, noisier lists — suggesting that the optimal *k* may differ from the generic default. Furthermore, equal weighting of channels is unlikely to be optimal when channels differ in both precision and recall characteristics.

### 5.2 Weighted RRF

Standard RRF weights all channels equally. We extend it with per-channel weights *w_c*:

$$\text{WRRF}(d) = \sum_{c \in \text{channels}} \frac{w_c}{k + \text{rank}_c(d)}$$

A weight of 0.0 silences a channel entirely; 1.0 recovers standard RRF for that channel; values above 1.0 amplify its contribution. This is implemented as `weighted_rrf_fuse(ranked_lists, weights, k)` in `src/Poule/fusion/fusion.py`.

### 5.3 Three-Phase Optimization Pipeline

Optimization proceeds in three independent phases, each producing comparable Recall@32 numbers on the same held-out test set. This structure isolates each retrieval signal's contribution.

**Phase 1: Symbol-only optimization.** Optimize *k* and per-channel weights (*w*_structural, *w*_mepo, *w*_fts) for the three symbolic channels. This establishes the symbol-only baseline.

**Phase 2: Neural training with HPO.** Train the bi-encoder model with Optuna hyperparameter optimization (existing `HyperparameterTuner`). This establishes the neural-only baseline.

**Phase 3: Combined optimization.** Optimize *k* and per-channel weights (*w*_structural, *w*_mepo, *w*_fts, *w*_neural) for all four channels using the trained model from phase 2. The *k* value may differ from phase 1 because the neural channel's rank distribution changes the fusion dynamics.

Phases 1 and 2 are independent and can run in parallel. Phase 3 requires the trained checkpoint from phase 2.

### 5.4 Optimization Protocol

We optimize *k* and weights using Optuna with the TPE sampler, the same framework used for neural training hyperparameter optimization.

**Objective.** Recall@32 on the validation split (position mod 10 == 8). The test split (position mod 10 == 9) is reserved for final evaluation only — optimizing against it would leak.

**Search space.**

| Parameter | Range | Type | Phase 1 | Phase 3 |
|-----------|-------|------|---------|---------|
| *k* | [1, 100] | Integer | Yes | Yes |
| *w*_structural | [0.0, 2.0] | Float | Yes | Yes |
| *w*_mepo | [0.0, 2.0] | Float | Yes | Yes |
| *w*_fts | [0.0, 2.0] | Float | Yes | Yes |
| *w*_neural | [0.0, 2.0] | Float | No | Yes |

**Sampler.** TPE with seed=42. For 4–5 parameters, TPE converges in approximately 30–50 trials.

**Pre-compute then sweep.** Channel ranked lists are independent of *k* and weights. The protocol pre-computes all channel results for all validation queries once (expensive), then each Optuna trial only re-fuses with different parameters (sub-second). This reduces total optimization time from hours to minutes.

**Protocol.**

1. Load the validation split: (proof_state, ground_truth_premises) pairs from files at position mod 10 == 8.
2. Pre-compute channel ranked lists for all validation queries (structural, MePo, FTS, and optionally neural). Resolve all declaration IDs to names for comparison with ground truth.
3. For each Optuna trial:
   a. Sample *k* and per-channel weights.
   b. For each query, fuse pre-computed ranked lists via `weighted_rrf_fuse(channels, weights, k=k_trial)`.
   c. Compute Recall@32; report the mean to Optuna.
4. After all trials complete, report the best *k*, weights, and Recall@32.
5. Evaluate the best parameters on the held-out test split and report final Recall@32.

**CLI.**

```bash
# Phase 1: symbol-only (3 channels, 4 parameters)
poule tune-rrf --db index.db training-data.jsonl --output-dir rrf-sym --n-trials 30

# Phase 3: combined (4 channels, 5 parameters)
poule tune-rrf --db index.db training-data.jsonl --output-dir rrf-combined \
  --n-trials 50 --checkpoint model.pt
```

### 5.5 Validation Set Considerations

The validation split is used for three tuning tasks: symbol-only *k*/weights (phase 1), neural HPO/early stopping (phase 2), and combined *k*/weights (phase 3). This is standard practice — the validation set exists for all tuning decisions. The test set remains untouched for final reporting.

The neural model selected via validation in phase 2 may perform slightly better on validation queries than on unseen data (the model was selected to maximize validation Recall@32). This could cause phase 3 to slightly overweight the neural channel. In practice, this bias is small because early stopping creates only a modest val-test gap for well-regularized models. Reporting both validation and test Recall@32 for all three phases reveals whether this is significant.

With 10,000+ ground truth pairs, the 10% validation split provides ~1,000 queries — sufficient for a 5-parameter search (standard error ≈ 1.6 percentage points at Recall@32 ≈ 0.5). If the validation set is smaller (<200 queries), consider increasing it to 20% (position mod 10 == 7 or 8 → validation).

### 5.6 Future Extensions

**Convex combination as alternative.** Bruch et al. (2022) advocate for convex combination (CC) fusion — a learned weight α ∈ [0, 1] combining normalized channel scores — as superior to RRF when annotated queries are available. CC requires only ~40 annotated queries to outperform RRF via Bayesian optimization. This could be explored as an alternative to RRF if score normalization across channels proves tractable.

## References

Bruch, S., Zuccon, G., Mackenzie, J., and Mitra, B. "An Analysis of Fusion Functions for Hybrid Retrieval." arXiv:2210.11934, 2022.

Cormack, G.V., Clarke, C.L.A., and Buettcher, S. "Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods." *Proceedings of SIGIR*, 2009.

Meng, J. and Paulson, L.C. "Lightweight Relevance Filtering for Machine-Generated Resolution Problems." *Journal of Applied Logic*, 7(1):41–70, 2009.

Mikula, M., et al. "Premise Selection for a Lean Hammer." arXiv:2506.07477, June 2025.

Shervashidze, N., Schweitzer, P., van Leeuwen, E.J., Mehlhorn, K., and Borgwardt, K.M. "Weisfeiler-Lehman Graph Kernels." *Journal of Machine Learning Research*, 12:2539–2561, 2011.

Thompson, S., et al. "Rango: Adaptive Retrieval-Augmented Proving for Automated Software Verification." *International Conference on Software Engineering (ICSE)*, 2025.

Zhang, K. and Shasha, D. "Simple Fast Algorithms for the Editing Distance between Trees and Related Problems." *SIAM Journal on Computing*, 18(6):1245–1262, 1989.
