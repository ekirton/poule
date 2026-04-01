# Pre-trained Model Distribution

A ready-to-use neural tactic prediction model, trained on proof traces from six Coq libraries, so that users get tactic suggestions without training a model themselves.

---

## Problem

Training a neural tactic prediction model requires extracted proof trace data, a GPU, and familiarity with ML training workflows. The target user — a Coq developer who wants tactic suggestions during proof development — should not need any of these. If the tactic prediction capability only works after the user trains a model, it effectively does not exist for most users.

## Solution

The tool ships with a pre-trained, INT8-quantized tactic classifier covering proof patterns from the Coq standard library, MathComp, stdpp, Flocq, Coquelicot, and CoqInterval. When a trained model is present, the `suggest_tactics` MCP tool includes neural predictions alongside rule-based suggestions automatically. No training step, no GPU, no configuration.

The pre-trained model is a standalone asset — it is **not** part of the search index. It does not produce embeddings and is not involved in library indexing or search. It is loaded by the `suggest_tactics` tool at server startup when available.

## What the User Sees

1. User installs the tool (same as today)
2. If the pre-trained tactic model is present, `suggest_tactics` returns neural predictions alongside rule-based suggestions
3. If no model is present, `suggest_tactics` returns only rule-based suggestions — no errors, no degradation

## Model Characteristics

- **Size**: ~100M parameters (CodeBERT encoder + classification head)
- **Quantized checkpoint size**: Under 100MB (INT8 quantized ONNX)
- **Inference**: CPU-only, <50ms per prediction
- **Quality**: >= 40% top-1 accuracy, >= 80% top-5 accuracy on held-out test set

## Design Rationale

### Why a standalone model, not part of the search index

The tactic classifier predicts tactic families from proof states — it does not produce declaration embeddings. There is no reason to rebuild it when the library index changes, and no reason to store it alongside search data. Decoupling the model from the index simplifies both the indexing pipeline and the model distribution.

### Why ship a model rather than download on first use

Downloading a model at runtime introduces network dependencies and failure modes (offline environments, corporate firewalls). The model is small enough (<100MB quantized) to distribute with the tool.

### Why six libraries as the training corpus

The six target libraries (stdlib, MathComp, stdpp, Flocq, Coquelicot, CoqInterval) span diverse mathematical domains and proof styles: standard arithmetic, algebraic structures, separation logic, floating-point formalization, real analysis, and interval arithmetic. Together they provide ~105,000 (proof_state, tactic) training pairs covering the full range of Coq proof strategies.

---

## Acceptance Criteria

### Ship a Pre-trained Tactic Prediction Model

**Priority:** P0
**Stability:** Stable

- GIVEN a fresh installation WHEN the `suggest_tactics` MCP tool is called THEN neural tactic predictions are returned if the pre-trained model is present
- GIVEN the pre-trained model WHEN evaluated on a held-out test set THEN it achieves >= 40% top-1 accuracy and >= 80% top-5 accuracy
- GIVEN the pre-trained model checkpoint WHEN its size is measured THEN the INT8 quantized model is under 100MB
