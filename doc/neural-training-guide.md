# Neural Premise Selection — Training & Deployment Guide

The neural premise selection system adds a learned semantic similarity channel to the search pipeline. It consists of four phases: training data extraction, model training, model evaluation, and deployment. All steps run inside the dev container.

## Overview

```
Coq projects (.v)
  │  poule extract
  ▼
Proof traces (JSONL)
  │  poule validate-training-data
  ▼
Validated training data
  │  poule build-vocabulary
  ▼
Closed vocabulary (coq-vocabulary.json)
  │  poule train
  ▼
PyTorch checkpoint (.pt)
  │  poule evaluate / poule compare
  │  poule quantize
  ▼
INT8 ONNX model (.onnx) + vocabulary
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

The training pipeline constructs pairs by pairing the goals from step k-1 (state before the tactic) with the global premises from step k (filtering out local hypotheses). A minimum of 10,000 pairs is needed; the stdlib alone provides ~67K.

## Step 3: Build the vocabulary

Build a closed-vocabulary tokenizer that assigns every Coq identifier its own token ID. This replaces CodeBERT's generic RoBERTa tokenizer, which fragments identifiers like `Nat.add_comm` into 5 subword tokens. With a closed vocabulary, every identifier is exactly 1 token.

```bash
# Build vocabulary from search index + extracted training data
poule build-vocabulary \
  --db index.db \
  --output coq-vocabulary.json \
  training-data.jsonl
```

The vocabulary is constructed from two sources:
- **Search index** (`index.db`) — all fully-qualified declaration names from the indexed libraries
- **Serialized proof states** from the training data — hypothesis variable names and syntax tokens

The vocabulary size scales with the number of indexed declarations. With the six target libraries (~118K declarations), the vocabulary contains ~150K tokens: ~118K library identifiers, ~33K variable names and syntax fragments from training data, ~110 fixed tokens (punctuation, Unicode symbols, Greek letters, digits, SSReflect tacticals, scope delimiters), and 5 special tokens (`[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]`). NFC Unicode normalization is applied before tokenization.

At inference time, tokenization is a whitespace split followed by O(1) dictionary lookup per token — no regex, no subword search. See `coq-vocabulary.md` for the full design rationale.

## Step 4: Train the model

Train a bi-encoder retrieval model from the extracted data. Requires a GPU (any 16GB+ for stdlib-only; 24GB recommended for larger corpora).

```bash
# Train with closed vocabulary
poule train \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output model.pt \
  stdlib.jsonl mathcomp.jsonl

# With custom hyperparameters
poule train \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output model.pt \
  --batch-size 256 \
  --learning-rate 2e-5 \
  --epochs 20 \
  training-data.jsonl
```

Training details:
- **Architecture**: ~98M parameter bi-encoder (CodeBERT 125M base with closed-vocabulary embedding layer, 768-dim embeddings, mean pooling)
- **Vocabulary**: Closed vocabulary (~150K tokens for the six target libraries) from `coq-vocabulary.json`
- **Embedding initialization**: Tokens overlapping with CodeBERT's vocabulary (digits, punctuation, common English words) retain pretrained embeddings; Coq-specific tokens initialized randomly (σ=0.02). CodeBERT's 12 transformer layers keep their full pretrained weights
- **Loss**: Masked contrastive (InfoNCE) with temperature τ=0.05. Shared premises across proof states in a batch are masked to prevent false negatives
- **Hard negatives**: 3 per proof state, sampled from accessible-but-unused premises (falls back to random corpus sampling if dependency graph unavailable)
- **Split**: Deterministic file-level split — position % 10 == 8 → validation, == 9 → test, rest → training. Prevents data leakage from related proofs in the same file
- **Early stopping**: Halts when validation Recall@32 fails to improve for 3 consecutive epochs

| Corpus size | GPU requirement | Estimated wall time | Estimated cost |
|-------------|----------------|---------------------|----------------|
| 10K pairs (stdlib only) | Any 16GB+ GPU | ~2 hours | <$10 |
| 50K pairs (stdlib + MathComp) | 24GB GPU (A6000/4090) | ~8 hours | $50–100 |
| 100K+ pairs (multi-project) | 24GB GPU (A6000/4090) | ~16 hours | $100–200 |

## Step 5: Optimize RRF fusion parameters

Before evaluating the combined pipeline, optimize the RRF smoothing constant *k* and per-channel weights. This is done in two phases:

```bash
# Phase 1: Symbol-only — optimize k and weights for structural, MePo, FTS channels
poule tune-rrf --db index.db training-data.jsonl --output-dir rrf-sym --n-trials 30

# Phase 3: Combined — optimize k and weights for all 4 channels (requires trained model)
poule tune-rrf --db index.db training-data.jsonl --output-dir rrf-combined \
  --n-trials 50 --checkpoint model.pt
```

Each phase pre-computes all channel ranked lists once, then sweeps parameters via Optuna — each trial is sub-second. The optimizer uses the validation split (position mod 10 == 8) and reports:
- Best *k* value
- Per-channel weights (*w*_structural, *w*_mepo, *w*_fts, and optionally *w*_neural)
- Best Recall@32 on validation

The *k* values for symbol-only and combined fusion may differ — this is expected since the neural channel changes the rank distribution dynamics. Use `--resume` to continue an interrupted study.

## Step 6: Evaluate the model

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

## Step 7: Quantize for deployment

Convert the PyTorch checkpoint to INT8 ONNX for CPU inference.

```bash
poule quantize --checkpoint model.pt --output neural-premise-selector.onnx
```

The quantization pipeline:
1. Exports the model to ONNX (opset 17+)
2. Applies dynamic INT8 quantization via ONNX Runtime
3. Validates by encoding 100 random inputs through both models — fails if max cosine distance ≥ 0.02

Result: ~100MB ONNX file (vs. ~400MB full precision), <10ms per encoding on CPU.

## Step 8: Publish the model

Include the ONNX model and vocabulary in the `index-merged` GitHub Release:

```bash
./scripts/publish-indexes.sh \
  --model neural-premise-selector.onnx \
  --vocabulary coq-vocabulary.json
```

This uploads the model and vocabulary alongside the merged search index. The Docker image build downloads them and places them at the well-known paths (`~/.local/share/poule/models/neural-premise-selector.onnx` and `~/.local/share/poule/models/coq-vocabulary.json`).

Users can also download the model separately:

```bash
poule-dev uv run python -m poule.cli download-index --output ~/data/index.db --include-model
```

## Step 9: Rebuild the index with embeddings

When the search index is rebuilt with a model checkpoint and vocabulary present, an embedding pass runs automatically after the standard indexing pass:

1. Load the INT8 ONNX encoder and vocabulary
2. Encode each declaration's statement → 768-dim vector
3. Batch-insert into the `embeddings` table (batches of 64, ~500ms each)
4. Write the model hash to `index_meta` for consistency checking

For 50K declarations on CPU: ~7 minutes. The embedding pass is atomic — failure discards the entire index.

At server startup, embeddings are loaded into a contiguous in-memory matrix (~150MB for 50K declarations). The neural channel is available when: (1) the model checkpoint exists, (2) the vocabulary file exists, (3) the `embeddings` table has rows, and (4) the stored model hash matches the current checkpoint. If any condition fails, search operates with symbolic channels only — no error, no degradation.

## End-to-end example: training the canonical model

This is the full workflow for producing the pre-trained model that ships with the tool:

```bash
COQ_LIBS="/opt/opam/coq/lib/coq/user-contrib"

# 1. Extract training data from all supported libraries
poule extract \
  $COQ_LIBS/Stdlib \
  $COQ_LIBS/mathcomp \
  $COQ_LIBS/stdpp \
  $COQ_LIBS/Flocq \
  $COQ_LIBS/Coquelicot \
  $COQ_LIBS/Interval \
  --output training-data.jsonl

# 2. Validate
poule validate-training-data training-data.jsonl

# 3. Build vocabulary (scans index + training data, runs instantly)
poule build-vocabulary \
  --db index.db \
  --output coq-vocabulary.json \
  training-data.jsonl

# 4. Train model (on a GPU machine)
poule train \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output model.pt \
  training-data.jsonl

# 5. Optimize RRF fusion parameters
# Phase 1: symbol-only baseline
poule tune-rrf --db index.db training-data.jsonl --output-dir rrf-sym --n-trials 30
# Phase 3: combined symbol + neural
poule tune-rrf --db index.db training-data.jsonl --output-dir rrf-combined \
  --n-trials 50 --checkpoint model.pt

# 6. Evaluate
poule evaluate --checkpoint model.pt --test-data training-data.jsonl --db index.db
poule compare  --checkpoint model.pt --test-data training-data.jsonl --db index.db

# 7. Quantize
poule quantize --checkpoint model.pt --output neural-premise-selector.onnx

# 8. Publish (includes model + vocabulary in the GitHub Release)
./scripts/publish-indexes.sh \
  --model neural-premise-selector.onnx \
  --vocabulary coq-vocabulary.json
```
