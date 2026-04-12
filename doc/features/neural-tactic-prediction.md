# Neural Tactic Prediction

A learned tactic family classifier that predicts which tactic to apply given a proof state, integrated into the existing `suggest_tactics` MCP tool as a neural enhancement over rule-based suggestions.

---

## Problem

When a student is stuck mid-proof, they need more than a list of possible tactics — they need to understand *why* a particular tactic makes sense given the current proof state. Claude serves as a thought partner and tutor, but needs a signal for which tactics are most promising so it can explain the reasoning and link to relevant textbook material.

The existing `suggest_tactics` MCP tool uses rule-based goal classification: it inspects the goal type for structural patterns (conjunction, disjunction, equality, existential, etc.) and suggests tactics accordingly. This approach is limited to a fixed set of goal shapes and cannot learn from proof patterns across libraries. It misses tactic choices that depend on hypothesis context, mathematical domain conventions, or library-specific idioms.

Meanwhile, the extraction pipeline captures (proof_state, tactic) pairs from five Coq libraries (stdlib, stdpp, flocq, coquelicot, MathComp) — each goal state paired with the tactic that was actually applied. This data represents the collective proof strategies of library authors across diverse mathematical domains. MathComp is included because it provides the SSReflect training signal needed by the dedicated SSReflect category head. CoqInterval is excluded — its specialized interval-arithmetic proof style does not transfer to other libraries (LOOCV showed 64/65 dead families).

## Solution

A hierarchical encoder-based classifier predicts the tactic family from a serialized proof state. Claude uses these predictions as a starting point to explain each suggestion: why the tactic is appropriate for this proof state, what proof strategy it serves, and where the student can learn more (e.g., the relevant Software Foundations chapter or Coq reference manual section).

The model uses a CodeBERT encoder with a closed-vocabulary tokenizer and a two-level classification hierarchy: 8 tactic categories (introduction, elimination, rewriting, hypothesis management, automation, arithmetic, contradiction, ssreflect) with within-category tactic families. Each category has a dedicated classification head. Training uses LDAM (label-distribution-aware margin loss) with deferred re-balancing: class-dependent margin offsets penalize misclassification of rare tactics more heavily, combined with a two-phase schedule that uses instance-balanced sampling initially and class-balanced sampling for the final training phase. Inference produces P(tactic) = P(category) × P(tactic|category) via the product rule.

Neural predictions are integrated into the existing `suggest_tactics` MCP tool:
- When a trained model is available, neural predictions are returned alongside rule-based suggestions, ranked by model confidence
- When no model is available, the tool operates with rule-based suggestions only — no errors, no degradation
- The MCP interface is unchanged; Claude sees richer suggestions when a model is present and uses them to offer explained, pedagogical guidance

## What This Is Not

This is **not** a search channel. The tactic classifier is independent of the Semantic Lemma Search pipeline. It does not produce embeddings, does not participate in RRF fusion, and is not stored in the search index. It is a proof assistance capability exposed through the `suggest_tactics` tool.

This is **not** full tactic generation. The classifier predicts tactic *families* (e.g., `rewrite`, `apply`, `induction`), not arbitrary tactic text. For families that take lemma arguments, the argument retrieval layer (see below) suggests specific candidates from the search index — but it does not generate novel argument expressions or handle tactic combinators.

## Design Rationale

### Why tactic prediction instead of premise retrieval

The original plan was to train a neural premise retrieval model. This failed: only ~3,500 of ~134,000 extracted proof records produce non-empty premise lists (97% attrition), because Coq's kernel does not track which lemmas each tactic consults. With ~3,500 training pairs — 1,600x smaller than LeanHammer's dataset — the premise retrieval model cannot achieve competitive quality.

Tactic prediction reuses the same extraction infrastructure with 30x more data. Every proof step has a tactic, regardless of whether premises are known. Research (Tactician, Proverbot9001, CoqHammer) confirms that tactic prediction works well for Coq without per-step premise annotations.

### Why 8 categories

The flat 96-class classifier achieves only 46.6% test accuracy@5 with 86 of 96 classes showing zero recall. The root cause is extreme class imbalance (IR = 26,950:1). Hierarchical decomposition into categories drops cross-category imbalance significantly. All 8 categories (introduction, elimination, rewriting, hypothesis management, automation, arithmetic, contradiction, ssreflect) have dedicated classification heads. Arithmetic and contradiction have few training examples (<900 and <150 respectively), but merging them into an "other" catch-all demonstrably hurts: the 6-category experiment showed the catch-all destroyed the working SSReflect head (move recall: 40.1% to 24.5%) without improving the merged categories. Keeping all 8 categories preserves each head's decision boundaries. Proof structure tokens (bullets, braces) are excluded from training entirely.

### Why CPU-only inference

The same argument as for premise retrieval: 100M-class models with INT8 quantization achieve <10ms per encoding on any modern CPU. Requiring a GPU would exclude most Coq developers. The tactic classifier's inference is even cheaper than retrieval because it produces a single classification vector, not an embedding that must be compared against a large index.

---

## Acceptance Criteria

### Predict Tactic Families from Proof States

**Priority:** P0
**Stability:** Stable
**Traces to:** R6-P0-1, R6-P0-2, R6-P0-7, R6-P0-8

- GIVEN a trained tactic classifier and a proof state WHEN tactic prediction is invoked THEN the model returns a ranked list of tactic families with confidence scores
- GIVEN a held-out test set of Coq proof steps WHEN the classifier is evaluated THEN top-1 accuracy is >= 40% and top-5 accuracy is >= 80%
- GIVEN the tactic family vocabulary WHEN inspected THEN it contains ~65 families across 8 categories covering >99% of extracted proof steps

### Integrate with suggest_tactics MCP Tool

**Priority:** P0
**Stability:** Stable
**Traces to:** R6-P0-4, R6-P0-11

- GIVEN a `suggest_tactics` call with a trained model available WHEN the tool executes THEN neural predictions are included in the response alongside rule-based suggestions
- GIVEN a `suggest_tactics` call without a trained model WHEN the tool executes THEN only rule-based suggestions are returned, with no errors or degradation
- GIVEN neural and rule-based suggestions WHEN they are combined THEN neural predictions with high confidence rank above rule-based suggestions

### CPU Inference with INT8 Quantization

**Priority:** P0
**Stability:** Stable
**Traces to:** R6-P0-5, R6-P0-6

- GIVEN a trained model checkpoint WHEN the quantize command is run THEN an INT8 quantized ONNX model is produced
- GIVEN the quantized model WHEN a single proof state is classified THEN inference completes in under 50ms on a modern laptop CPU
- GIVEN the quantized model WHEN evaluated on the test set THEN accuracy is within 2 percentage points of the full-precision model

### Handle Class Imbalance

**Priority:** P0
**Stability:** Stable
**Traces to:** R6-P0-3

- GIVEN a training dataset with imbalanced tactic family distribution WHEN training is configured THEN class weights are computed from inverse frequency and applied to the cross-entropy loss
- GIVEN class-weighted training WHEN evaluated on minority tactic families THEN per-family recall is significantly higher than without weighting

### Undersample Dominant Tactic Families

**Priority:** P1
**Stability:** Draft
**Traces to:** R6-P1-8

The six most frequent tactic families (rewrite, intros, apply, auto, destruct, split) contain thousands of near-identical proof states. Capping each at a configurable maximum (default ~2,000) per family in the training split reduces training set size from ~114K to ~40–50K samples while preserving all tail-class examples. This forces more tail-class exposure per epoch without discarding rare tactic data.

**What this provides:**
- Configurable per-family cap applied only to the training split (validation and test splits are unchanged)
- Deterministic, reproducible undersampling using a fixed random seed
- Reduced training time proportional to the smaller dataset

**What this does not provide:**
- Oversampling of rare classes (a separate technique)
- Changes to class weighting (undersampling and weighting are complementary)
- Changes to the data collapse step or extraction pipeline

- GIVEN a training dataset with dominant tactic families exceeding the cap WHEN undersampling is enabled THEN each dominant family in the training split is reduced to at most the configured cap
- GIVEN undersampling is enabled WHEN the validation and test splits are inspected THEN they are unchanged from the non-undersampled case
- GIVEN a tactic family below the cap WHEN undersampling is enabled THEN all its examples are retained
- GIVEN undersampling with a fixed seed WHEN run twice on the same data THEN the same samples are selected

### Leave-One-Library-Out Cross-Validation

**Priority:** P1
**Stability:** Draft
**Traces to:** R6-P1-9

The current file-level split scatters files from the same library across train, validation, and test splits. Libraries share tactic conventions — stdlib favors `destruct`/`induction`, stdpp has its own automation patterns. The model may learn library identity rather than generalizable proof-state-to-tactic mappings. Leave-one-library-out cross-validation (LOOCV) diagnoses whether library-level data leakage is the bottleneck for generalization.

CoqInterval is excluded from both training and LOOCV — its specialized interval-arithmetic proof style does not transfer (LOOCV showed 64/65 dead families). MathComp is included in training (it provides the SSReflect signal) but excluded from LOOCV because its SSReflect-dialect tactics (71% of its steps) make it a poor hold-out candidate against vanilla-Coq libraries. The remaining 4 vanilla-Coq libraries (stdlib, stdpp, flocq, coquelicot) are 78–99% vanilla Coq.

For each of the 4 vanilla-Coq libraries, one fold holds out that library entirely as the test set and trains on the remaining libraries plus MathComp. Validation comes from the training-distribution libraries (not the held-out library) so early stopping gets a proper signal. The test set is a completely unseen library — true cross-library generalization.

**What this provides:**
- A CLI command to run LOOCV across all libraries, producing a per-fold and aggregate report
- Library-level data loading that assigns files to train/val/test by library membership rather than file position
- Per-fold metrics: accuracy@1, accuracy@5, category accuracy@1, dead family count, per-family recall
- Aggregate metrics: mean and standard deviation of test accuracy@5 across folds, per-library accuracy comparison

**What this does not provide:**
- A new production training split (LOOCV is a diagnostic experiment, not a replacement for the file-level split)
- Changes to the existing training pipeline or model architecture
- Automatic selection of the best split strategy based on LOOCV results

- GIVEN per-library JSONL files for 4 vanilla-Coq libraries plus MathComp (excluding CoqInterval) WHEN the LOOCV command runs THEN 4 folds are trained and evaluated, each holding out one vanilla-Coq library as the test set
- GIVEN a LOOCV fold WHEN the held-out library's files are inspected THEN none appear in the training or validation splits
- GIVEN a LOOCV fold WHEN validation files are inspected THEN they come only from the non-held-out libraries
- GIVEN a LOOCV fold WHEN undersampling is applied THEN it uses the configured cap (default 1000) on the training split only
- GIVEN all 4 folds complete WHEN the aggregate report is generated THEN it contains mean test_acc@5, std test_acc@5, and per-library accuracy
- GIVEN a fixed seed and identical input WHEN LOOCV is run twice THEN the same train/val splits and results are produced

### Collapse Training Data

**Priority:** P1
**Stability:** Stable
**Traces to:** R6-P1-7

The raw extraction output contains 2,113 tactic families, but 1,330 (63%) are singletons and 1,808 (86%) have ≤5 examples. Many are parsing artifacts — compound tactics that were not fully normalized during extraction (e.g., `destruct(q_dec`, `1:lia`, `(do`). Training on this raw distribution wastes capacity on noise and inflates the "other" class.

A collapse step merges per-library JSONL files into a single training file, normalizing tactic families by:
1. Stripping parenthesized prefixes and suffixes that indicate compound tactic fragments
2. Merging families below a configurable minimum count into "other"
3. Applying alias mappings to consolidate variant spellings

The original per-library files are preserved unchanged. The collapsed file is a derived artifact that can be regenerated with different parameters.

**What this is not:** This is not a change to the extraction pipeline. Extraction continues to emit raw tactic text. Collapse is a post-extraction preprocessing step.

- GIVEN per-library training JSONL files WHEN the collapse command runs with default settings THEN a single merged JSONL file is produced containing all step records with normalized tactic families
- GIVEN the collapsed output WHEN tactic families are counted THEN no family has fewer than the configured minimum count (default 50), except "other"
- GIVEN the original per-library files WHEN the collapse command completes THEN the originals are unchanged
- GIVEN different `--min-count` values WHEN the collapse command is re-run THEN the output reflects the new threshold without re-extracting

### Retrieve Tactic Arguments from Search Index

**Priority:** P2
**Stability:** Draft
**Traces to:** R6-P2-2

For tactic families that take lemma arguments (`apply`, `rewrite`, `exact`), the system retrieves candidate arguments from the search index and produces full tactic suggestions (e.g., `apply Nat.add_comm`). This bridges the gap between family-level prediction ("use `apply`") and actionable proof advice ("use `apply Nat.add_comm`").

The argument retrieval layer sits between the tactic family classifier and the `suggest_tactics` response. It uses the existing multi-channel retrieval pipeline — type-based search for `apply`/`exact` (lemmas whose conclusion matches the goal), symbol-based search for `rewrite` (equalities involving goal symbols) — without modifying the retrieval pipeline itself.

**What this provides:**
- Full tactic suggestions with specific lemma names for argument-taking tactic families
- Retrieval strategies tailored per tactic family (type matching for `apply`, equality filtering for `rewrite`)
- Integration into the existing `suggest_tactics` MCP tool response

**What this does not provide:**
- Argument retrieval for tactics that take proof terms, introduction patterns, or non-lemma arguments (e.g., `induction n`, `destruct (pair_dec x y)`)
- Novel argument expression generation — candidates come only from the search index
- Any changes to the search index, retrieval channels, or RRF fusion logic

**Acceptance criteria:**

- GIVEN a neural prediction of `apply` and a search index WHEN argument retrieval runs THEN candidates are lemmas whose conclusion type matches the focused goal type, ranked by retrieval score
- GIVEN a neural prediction of `rewrite` and a search index WHEN argument retrieval runs THEN candidates are lemmas that are equalities containing symbols present in the goal, ranked by retrieval score
- GIVEN a neural prediction of `exact` and a search index WHEN argument retrieval runs THEN candidates are lemmas whose type exactly matches the goal type, ranked by retrieval score
- GIVEN a neural prediction with argument candidates WHEN merged into `suggest_tactics` output THEN each candidate appears as a full tactic suggestion (e.g., `apply Nat.add_comm`) with the candidate's retrieval score informing confidence
- GIVEN a neural prediction for a family that takes arguments but no search index is loaded WHEN argument retrieval runs THEN the family-only suggestion is returned without error
- GIVEN a neural prediction for a family that does not take lemma arguments (e.g., `intros`, `simpl`, `auto`) WHEN argument retrieval runs THEN no retrieval is attempted and the family-only suggestion is returned
