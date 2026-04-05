# Neural Tactic Prediction

A learned tactic family classifier that predicts which tactic to apply given a proof state, integrated into the existing `suggest_tactics` MCP tool as a neural enhancement over rule-based suggestions.

---

## Problem

The existing `suggest_tactics` MCP tool uses rule-based goal classification: it inspects the goal type for structural patterns (conjunction, disjunction, equality, existential, etc.) and suggests tactics accordingly. This approach is limited to a fixed set of goal shapes and cannot learn from proof patterns across libraries. It misses tactic choices that depend on hypothesis context, mathematical domain conventions, or library-specific idioms.

Meanwhile, the extraction pipeline captures ~105,000 (proof_state, tactic) pairs from six Coq libraries — each goal state paired with the tactic that was actually applied. This data represents the collective proof strategies of library authors across diverse mathematical domains. A classifier trained on this data can learn which tactic families are appropriate for proof states that no rule-based system can enumerate.

## Solution

An encoder-based classifier predicts the tactic family from a serialized proof state. The model uses a CodeBERT encoder with a closed-vocabulary tokenizer (the same tokenizer used elsewhere in the project) and a classification head mapping to ~30 tactic families. Training uses class-weighted cross-entropy to handle the long-tailed tactic distribution.

Neural predictions are integrated into the existing `suggest_tactics` MCP tool:
- When a trained model is available, neural predictions are returned alongside rule-based suggestions, ranked by model confidence
- When no model is available, the tool operates with rule-based suggestions only — no errors, no degradation
- The MCP interface is unchanged; Claude sees richer suggestions when a model is present

## What This Is Not

This is **not** a search channel. The tactic classifier is independent of the Semantic Lemma Search pipeline. It does not produce embeddings, does not participate in RRF fusion, and is not stored in the search index. It is a proof assistance capability exposed through the `suggest_tactics` tool.

This is **not** full tactic generation. The classifier predicts tactic *families* (e.g., `rewrite`, `apply`, `induction`), not arbitrary tactic text. For families that take lemma arguments, the argument retrieval layer (see below) suggests specific candidates from the search index — but it does not generate novel argument expressions or handle tactic combinators.

## Design Rationale

### Why tactic prediction instead of premise retrieval

The original plan was to train a neural premise retrieval model. This failed: only ~3,500 of ~134,000 extracted proof records produce non-empty premise lists (97% attrition), because Coq's kernel does not track which lemmas each tactic consults. With ~3,500 training pairs — 1,600x smaller than LeanHammer's dataset — the premise retrieval model cannot achieve competitive quality.

Tactic prediction reuses the same extraction infrastructure with 30x more data. Every proof step has a tactic, regardless of whether premises are known. Research (Tactician, Proverbot9001, CoqHammer) confirms that tactic prediction works well for Coq without per-step premise annotations.

### Why ~30 tactic families

Coq has 60-80 distinct built-in tactics, but the distribution is heavily long-tailed. A small number of families (`intros`, `apply`, `rewrite`, `simpl`, `auto`, `destruct`, `induction`, `exact`, `unfold`) account for the majority of proof steps. Grouping into ~30 families balances granularity (specific enough to be useful) against learnability (enough training examples per class). Rare tactics are grouped into an "other" class.

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
- GIVEN the tactic family vocabulary WHEN inspected THEN it contains ~30 families covering >95% of extracted proof steps, with rare tactics grouped into an "other" class

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
