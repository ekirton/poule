# Neural Tactic Prediction — Training & Deployment Guide

The neural tactic prediction system trains a classifier that predicts which tactic family to apply given a proof state. It integrates into the `suggest_tactics` MCP tool, enhancing rule-based suggestions with learned predictions. All steps run inside the dev container.

## Overview

```
Coq projects (.v)
  │  poule extract
  ▼
Proof traces (JSONL) — "s" records with (proof_state, tactic_text)
  │  poule validate-training-data
  ▼
Validated training data (~105K steps from 6 libraries)
  │  poule build-vocabulary
  ▼
Closed vocabulary (coq-vocabulary.json)
  │  poule train
  ▼
PyTorch checkpoint (.pt)
  │  poule evaluate
  │  poule quantize
  ▼
INT8 ONNX model (tactic-predictor.onnx) + tactic-labels.json
  │  placed in model directory
  ▼
suggest_tactics MCP tool → neural predictions active
```

## Step 1: Extract training data

Extract proof traces with per-step tactic annotations from Coq libraries. The extraction pipeline replays each proof, recording the proof state and tactic text at each step.

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

Each line in the output is a self-contained JSON object. The key record types:

| Record type | Description |
|-------------|-------------|
| `campaign_metadata` | Provenance (Coq version, project commits, tool version) — first line |
| `"s"` (step) | Per-tactic-step record: proof state + tactic command text |
| `"g"` (goal) | Supplementary goal states for vocabulary construction |
| `extraction_error` | One per failed proof — error kind and message |
| `extraction_summary` | Counts (found, extracted, failed, skipped) — last line |

The `"s"` records are the training data: each contains a serialized proof state (the goals and hypotheses before the tactic) and the tactic command text that was applied. The six target libraries yield ~105,000 such records.

## Step 2: Validate training data

Check extracted data for quality issues before committing compute time.

```bash
poule validate-training-data training-data.jsonl
```

The validator reports:
- Total step records and steps with missing tactic text
- Tactic family distribution (frequency of each family)
- Class imbalance warnings (dominant families that may need stronger weighting)

A minimum of 10,000 steps is recommended; the six target libraries combined yield ~105,000.

## Step 3: Build the vocabulary

Build a closed-vocabulary tokenizer that assigns every Coq identifier its own token ID. This replaces CodeBERT's generic RoBERTa tokenizer, which fragments identifiers like `Nat.add_comm` into 5 subword tokens. With a closed vocabulary, every identifier is exactly 1 token.

```bash
poule build-vocabulary \
  --db index.db \
  --output coq-vocabulary.json \
  training-data.jsonl
```

The vocabulary is constructed from two sources:
- **Search index** (`index.db`) — all fully-qualified declaration names from the indexed libraries
- **Serialized proof states** from the training data — hypothesis variable names and syntax tokens

## Step 4: Train the model

Train a tactic family classifier from the extracted data. Supports three backends:

| Backend | Platform | Requirements |
|---------|----------|--------------|
| MLX | macOS with Apple Silicon | `pip install "mlx>=0.18"` — uses unified memory GPU |
| PyTorch (CUDA) | Linux/Windows with NVIDIA GPU | `pip install torch` — 8GB+ VRAM recommended |
| PyTorch (CPU) | Any | `pip install torch --index-url https://download.pytorch.org/whl/cpu` |

On macOS with Apple Silicon, the MLX backend is selected automatically. It trains on the Metal GPU and saves checkpoints in safetensors format, which are auto-converted to PyTorch `.pt` for downstream inference.

**Install training dependencies:**

```bash
# macOS with Apple Silicon (recommended for training)
pip install "mlx>=0.18"
pip install -e '.[train]'

# CPU-only (containers, CI, machines without a GPU)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e '.[train]'

# NVIDIA GPU
pip install -e '.[train]' torch
```

```bash
# Train with closed vocabulary
poule train \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output model.pt \
  training-data.jsonl

# Quick end-to-end test (for testing only)
poule train \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output model.pt \
  --sample 0.15 \
  --epochs 2 \
  training-data.jsonl
```

The `--sample` flag randomly sub-samples the training split to the given fraction. Validation and test splits are not affected. **This is for test runs only.**

Training details:
- **Architecture**: CodeBERT encoder initialized from `microsoft/codebert-base`, with closed-vocabulary embedding layer (158K tokens), mean pooling, and linear classification head (96 classes)
- **Encoder depth**: Configurable `num_hidden_layers` ∈ {4, 6, 8, 12}. When fewer than 12 layers are used, layers are selected at evenly spaced indices from CodeBERT's 12 layers (layer dropping)
- **Loss**: Class-weighted cross-entropy with label smoothing. Weights use tunable inverse-frequency power law: `weight[c] = (total / (num_classes × count[c])) ^ alpha`
- **Split**: Deterministic file-level split — position % 10 == 8 → validation, == 9 → test, rest → training
- **Early stopping**: Halts when validation accuracy@5 fails to improve for `patience` consecutive epochs (default 3)
- **MLX training**: Pre-tokenizes all data, uses length-bucketed batching to reduce attention cost on variable-length sequences, evaluates lazily per micro-batch

### Hyperparameter optimization

The training pipeline includes an Optuna-based hyperparameter tuner that searches over model architecture and training configuration jointly:

```bash
poule tune \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output hpo-results/ \
  --n-trials 10 \
  training-data.jsonl
```

The tuner searches over 7 hyperparameters:

| Hyperparameter | Range |
|---|---|
| `num_hidden_layers` | {4, 6, 8, 12} |
| `learning_rate` | [1e-6, 1e-4] log-uniform |
| `batch_size` | {16, 32, 64} |
| `weight_decay` | [1e-4, 1e-1] log-uniform |
| `class_weight_alpha` | [0.0, 1.0] |
| `label_smoothing` | [0.0, 0.3] |
| `sam_rho` | [0.01, 0.2] log-uniform |

The study uses TPE sampling with a MedianPruner (3 startup trials, 3 warmup epochs). Study state persists to SQLite (`hpo-study.db`) for crash recovery with `--resume`. The best trial's checkpoint is copied to `best-model.pt`.

## Step 5: Evaluate the model

Measure tactic prediction accuracy on the held-out test set.

```bash
poule evaluate --checkpoint model.pt --test-data training-data.jsonl --db index.db
```

Reports accuracy@1, accuracy@5, per-family precision/recall, and a confusion matrix. Warnings are emitted if:
- accuracy@1 < 40%
- accuracy@5 < 80%

## Step 6: Quantize for deployment

Convert the PyTorch checkpoint to INT8 ONNX for CPU inference.

```bash
poule quantize --checkpoint model.pt --output tactic-predictor.onnx
```

The quantization pipeline:
1. Exports the model to ONNX (opset 17+)
2. Applies dynamic INT8 quantization via ONNX Runtime
3. Validates by comparing predicted labels on 100 random inputs — fails if agreement < 98%
4. Writes `tactic-labels.json` alongside the ONNX model (maps class index to family name)

Result: ~25MB ONNX file, <50ms per prediction on CPU.

## Step 7: Deploy

Place the quantized model and label file where the `suggest_tactics` MCP tool can find them:

```bash
# Default model directory
mkdir -p ~/.local/share/poule/models/
cp tactic-predictor.onnx ~/.local/share/poule/models/
cp tactic-labels.json ~/.local/share/poule/models/
cp coq-vocabulary.json ~/.local/share/poule/models/
```

When these files are present, `suggest_tactics` automatically includes neural predictions alongside rule-based suggestions. When absent, it falls back to rule-based suggestions only — no errors, no degradation.

## End-to-end example: training the canonical model

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

# 3. Build vocabulary
poule build-vocabulary \
  --db index.db \
  --output coq-vocabulary.json \
  training-data.jsonl

# 4. Collapse training data (normalize tactic families, merge rare into "other")
poule collapse-training-data \
  --min-count 50 \
  --output training.jsonl \
  training-data.jsonl

# 5. HPO (optional but recommended — finds best architecture + hyperparameters)
poule tune \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output hpo-results/ \
  --n-trials 10 \
  training.jsonl

# 6. Train final model with best hyperparameters
poule train \
  --vocabulary coq-vocabulary.json \
  --db index.db \
  --output model.pt \
  --hyperparams hpo-results/best-hyperparams.json \
  training.jsonl

# 7. Evaluate
poule evaluate --checkpoint model.pt --test-data training.jsonl --db index.db

# 8. Quantize
poule quantize --checkpoint model.pt --output tactic-predictor.onnx
```
