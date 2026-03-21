# Pre-trained Model Distribution

A ready-to-use neural premise selection model checkpoint, trained on the Coq standard library and MathComp, shipped with the tool so users get improved search quality without training a model themselves.

---

## Problem

Training a neural retrieval model requires extracted proof trace data, a GPU, and familiarity with ML training workflows. The target user — a Coq developer who wants better search — should not need any of these. If the neural retrieval channel only works after the user trains a model, it effectively does not exist for most users.

## Solution

The tool ships with a pre-trained, INT8-quantized model checkpoint covering the Coq standard library and MathComp. When the user runs the indexing command, premise embeddings are computed using this checkpoint automatically. No training step, no GPU, no configuration.

The pre-trained model is the project's canonical checkpoint: trained by the project maintainers on the full Training Data Extraction output for stdlib + MathComp, evaluated against the deployment quality thresholds, quantized to INT8, and distributed alongside the tool.

## What the User Sees

1. User installs the tool and runs the indexing command (same as today)
2. Indexing builds the structural/symbolic index as before
3. If the pre-trained model checkpoint is present, indexing also computes neural embeddings for all declarations
4. Search queries now benefit from the neural channel — no additional steps required

If the user later fine-tunes the model on their project's data, the fine-tuned checkpoint replaces the pre-trained one and embeddings are recomputed on the next index rebuild.

## Model Characteristics

The pre-trained model targets the following profile based on research evidence:

- **Size**: ~100M parameters (the range where training objectives and data quality matter more than scale)
- **Quantized checkpoint size**: Under 500MB (INT8 quantized)
- **Inference**: CPU-only, <10ms per encoding
- **Quality**: ≥50% Recall@32 on held-out Coq proof state evaluation set

## Design Rationale

### Distribution mechanism

The pre-trained model and a prebuilt search index (covering stdlib + MathComp) are distributed via GitHub Releases. Users download both artifacts with a single CLI command (`download-index --include-model`), verified by SHA-256 checksums. This eliminates the need to install the Coq toolchain or run extraction for the common case. See the [distribution architecture](../architecture/prebuilt-distribution.md) for the full protocol.

### Why ship a model rather than download on first use

Downloading a model at runtime introduces network dependencies, versioning complexity, and failure modes (offline environments, corporate firewalls, CDN outages). The model is small enough (<500MB quantized) to distribute with the tool. This follows the zero-config deployment principle: install, index, search.

### Why stdlib + MathComp as the training corpus

These are the two most widely used Coq libraries. The standard library provides foundational coverage; MathComp provides the densest mathematical content and the most complex proof patterns. Together they cover the vast majority of declarations that Coq developers search for. Project-specific retrieval quality can be improved through fine-tuning (a separate P1 feature).

### Why not a larger model

Research consistently shows that 100M-class models match or exceed much larger models for formal math retrieval when paired with hybrid ranking. LeanExplore's 109M off-the-shelf model matched or beat 7B fine-tuned models. LeanHammer's 82M model outperformed ReProver's 299M by 150%. Shipping a 7B model would require GPU inference, excluding most users. The quality advantage of larger models is marginal and fully compensated by hybrid ranking with the existing structural and symbolic channels.

---

## Acceptance Criteria

### Ship a Pre-trained Model for Standard Library and MathComp

**Priority:** P0
**Stability:** Stable

- GIVEN a fresh installation of the search tool WHEN the user runs the indexing command with the default model THEN the pre-trained model is used to compute premise embeddings without requiring any training step
- GIVEN the pre-trained model WHEN evaluated on a held-out test set from the Coq standard library and MathComp THEN it achieves ≥ 50% Recall@32
- GIVEN the pre-trained model checkpoint WHEN its size is measured THEN the INT8 quantized model is under 500MB
