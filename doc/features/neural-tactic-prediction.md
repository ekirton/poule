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

This is **not** full tactic generation. The classifier predicts tactic *families* (e.g., `rewrite`, `apply`, `induction`), not complete tactic text with arguments. Argument selection (e.g., which lemma to `apply`) is a separate concern addressed by the rule-based system and future work combining tactic prediction with premise retrieval.

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
