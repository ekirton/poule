# Neural Premise Selection — Training & Deployment Guide

The neural premise selection system adds a learned semantic similarity channel to the search pipeline. It consists of four phases: training data extraction, model training, model evaluation, and deployment. All steps run inside the dev container.

## Overview

```
Coq projects (.v)
  │  poule extract
  ▼
Proof traces (JSONL)
  │  poule validate-training-data
  │  poule train
  ▼
PyTorch checkpoint (.pt)
  │  poule evaluate / poule compare
  │  poule quantize
  ▼
INT8 ONNX model (.onnx)
  │  publish via GitHub Release
  │  baked into Docker image / downloaded by user
  ▼
Embeddings in index.db → neural retrieval channel active
```

## Step 1: Extract training data

Extract proof traces with per-step premise annotations from Coq libraries. The extraction pipeline replays each proof, recording the proof state and which premises each tactic used.

```bash
# Extract from the Coq/Rocq standard library
poule extract /opt/opam/coq/lib/coq/user-contrib/Stdlib --output stdlib.jsonl

# Extract from MathComp
poule extract /opt/opam/coq/lib/coq/user-contrib/mathcomp --output mathcomp.jsonl

# Multi-project extraction in a single campaign
poule extract \
  /opt/opam/coq/lib/coq/user-contrib/Stdlib \
  /opt/opam/coq/lib/coq/user-contrib/mathcomp \
  /opt/opam/coq/lib/coq/user-contrib/stdpp \
  /opt/opam/coq/lib/coq/user-contrib/Flocq \
  --output training-data.jsonl
```

Each line in the output is a self-contained JSON object. The stream structure is:

| Record type | Description |
|-------------|-------------|
| `campaign_metadata` | Provenance (Coq version, project commits, tool version) — first line |
| `proof_trace` | One per successfully extracted proof — per-step goals, tactics, premises |
| `extraction_error` | One per failed proof — error kind and message |
| `extraction_summary` | Counts (found, extracted, failed, skipped) — last line |

Target success rates: stdlib ≥ 95%, MathComp ≥ 90%.

## Step 2: Validate training data

Check extracted data for quality issues before committing GPU time.

```bash
poule validate-training-data stdlib.jsonl mathcomp.jsonl
```

The validator reports:
- Total `(proof_state, premises_used)` pairs and how many steps have empty premise lists
- Unique premise count and premise frequency distribution (top 10)
- Warnings for: >10% empty premises, malformed fields, <5,000 pairs, <1,000 unique premises, any premise >5% of all occurrences

The training pipeline constructs pairs by pairing the goals from step k-1 (state before the tactic) with the global premises from step k (filtering out local hypotheses). A minimum of 10,000 pairs is needed; the stdlib alone provides ~15K.

## Step 3: Train the model

Train a bi-encoder retrieval model from the extracted data. Requires a GPU (any 16GB+ for stdlib-only; 24GB recommended for larger corpora).

```bash
# Train from scratch on stdlib + MathComp
poule train \
  --data stdlib.jsonl mathcomp.jsonl \
  --db index.db \
  --output model.pt

# With custom hyperparameters
poule train \
  --data training-data.jsonl \
  --db index.db \
  --output model.pt \
  --batch-size 128 \
  --learning-rate 2e-5 \
  --max-epochs 20
```

Training details:
- **Architecture**: ~100M parameter bi-encoder (shared-weight CodeBERT-class encoder, 768-dim embeddings, mean pooling)
- **Loss**: Masked contrastive (InfoNCE) with temperature τ=0.05. Shared premises across proof states in a batch are masked to prevent false negatives
- **Hard negatives**: 3 per proof state, sampled from accessible-but-unused premises (falls back to random corpus sampling if dependency graph unavailable)
- **Split**: Deterministic file-level split — position % 10 == 8 → validation, == 9 → test, rest → training. Prevents data leakage from related proofs in the same file
- **Early stopping**: Halts when validation Recall@32 fails to improve for 3 consecutive epochs

| Corpus size | GPU requirement | Estimated wall time | Estimated cost |
|-------------|----------------|---------------------|----------------|
| 10K pairs (stdlib only) | Any 16GB+ GPU | ~2 hours | <$10 |
| 50K pairs (stdlib + MathComp) | 24GB GPU (A6000/4090) | ~8 hours | $50–100 |
| 100K+ pairs (multi-project) | 24GB GPU (A6000/4090) | ~16 hours | $100–200 |

## Step 4: Evaluate the model

Measure retrieval quality on the held-out test set.

```bash
# Retrieval metrics (R@1, R@10, R@32, MRR)
poule evaluate --checkpoint model.pt --test-data training-data.jsonl --db index.db

# Compare neural vs. symbolic vs. union
poule compare --checkpoint model.pt --test-data training-data.jsonl --db index.db
```

**Evaluation** reports Recall@1/10/32, MRR, test count, mean premises per state, and query latency. A warning is emitted if Recall@32 < 50%.

**Comparison** runs the same test set through neural-only, symbolic-only (WL + MePo + FTS5), and union (neural+symbolic, re-ranked by RRF). The key metric is relative improvement: `(union R@32 - symbolic R@32) / symbolic R@32`. A warning is emitted if this is below 15%.

Deployment gates (advisory):
- Neural Recall@32 ≥ 50%
- Union relative improvement ≥ 15% over symbolic-only

## Step 5: Quantize for deployment

Convert the PyTorch checkpoint to INT8 ONNX for CPU inference.

```bash
poule quantize --checkpoint model.pt --output neural-premise-selector.onnx
```

The quantization pipeline:
1. Exports the model to ONNX (opset 17+)
2. Applies dynamic INT8 quantization via ONNX Runtime
3. Validates by encoding 100 random inputs through both models — fails if max cosine distance ≥ 0.02

Result: ~100MB ONNX file (vs. ~400MB full precision), <10ms per encoding on CPU.

## Step 6: Publish the model

Include the ONNX model in the `index-merged` GitHub Release:

```bash
./scripts/publish-indexes.sh --model neural-premise-selector.onnx
```

This uploads the model alongside the merged search index. The Docker image build downloads it and places it at the well-known model path (`~/.local/share/poule/models/neural-premise-selector.onnx`).

Users can also download the model separately:

```bash
poule-dev uv run python -m poule.cli download-index --output ~/data/index.db --include-model
```

## Step 7: Rebuild the index with embeddings

When the search index is rebuilt with a model checkpoint present, an embedding pass runs automatically after the standard indexing pass:

1. Load the INT8 ONNX encoder
2. Encode each declaration's statement → 768-dim vector
3. Batch-insert into the `embeddings` table (batches of 64, ~500ms each)
4. Write the model hash to `index_meta` for consistency checking

For 50K declarations on CPU: ~7 minutes. The embedding pass is atomic — failure discards the entire index.

At server startup, embeddings are loaded into a contiguous in-memory matrix (~150MB for 50K declarations). The neural channel is available when: (1) the model checkpoint exists, (2) the `embeddings` table has rows, and (3) the stored model hash matches the current checkpoint. If any condition fails, search operates with symbolic channels only — no error, no degradation.

## Fine-tuning on a user project

Users with large custom projects can fine-tune the pre-trained model on their own proof traces:

```bash
# 1. Extract the project's proofs
poule extract /path/to/my-project --output my-project.jsonl

# 2. Fine-tune from the pre-trained checkpoint
poule fine-tune \
  --checkpoint neural-premise-selector.pt \
  --data my-project.jsonl \
  --output fine-tuned.pt \

# 3. Quantize and deploy
poule quantize --checkpoint fine-tuned.pt --output neural-premise-selector.onnx
```

Fine-tuning uses a lower learning rate (5e-6 vs. 2e-5) and fewer epochs (10 vs. 20) to avoid catastrophic forgetting. On a consumer GPU with 1K–10K project-specific proofs, fine-tuning completes in under 4 hours.

## End-to-end example: training the canonical model

This is the full workflow for producing the pre-trained model that ships with the tool:

```bash
# 1. Extract training data from all supported libraries
poule extract \
  /opt/opam/coq/lib/coq/user-contrib/Stdlib \
  /opt/opam/coq/lib/coq/user-contrib/mathcomp \
  /opt/opam/coq/lib/coq/user-contrib/stdpp \
  /opt/opam/coq/lib/coq/user-contrib/Flocq \
  /opt/opam/coq/lib/coq/user-contrib/Coquelicot \
  /opt/opam/coq/lib/coq/user-contrib/Interval \
  --output training-data.jsonl

# 2. Validate
poule validate-training-data training-data.jsonl

# 3. Train (on a GPU machine)
poule train --data training-data.jsonl --db index.db --output model.pt

# 4. Evaluate
poule evaluate --checkpoint model.pt --test-data training-data.jsonl --db index.db
poule compare  --checkpoint model.pt --test-data training-data.jsonl --db index.db

# 5. Quantize
poule quantize --checkpoint model.pt --output neural-premise-selector.onnx

# 6. Publish (includes model in the GitHub Release)
./scripts/publish-indexes.sh --model neural-premise-selector.onnx
```
