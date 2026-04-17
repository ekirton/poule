# Neural Tactic Prediction — Training & Deployment Guide

The neural tactic prediction system trains a classifier that predicts which tactic family to apply given a proof state. It integrates into the `suggest_tactics` MCP tool, enhancing rule-based suggestions with learned predictions.

The canonical end-to-end pipeline is `scripts/run-full-training.py` — it builds the BPE vocabulary, runs HPO, promotes the best trial, evaluates, and exports to ONNX in one invocation. The step-by-step CLI flow below is for inspection, debugging, or partial re-runs.

## Overview

```
Coq projects (.v)
  │  poule extract
  ▼
Proof traces (JSONL) — "s" records with (proof_state, tactic_text)
  │  poule validate-training-data
  ▼
Validated training data (5 libraries: Stdlib, stdpp, Flocq, Coquelicot, MathComp)
  │  poule collapse-training-data           (normalize tactic families)
  ▼
training.jsonl
  │  BpeVocabularyBuilder.build              (called from run-full-training.py)
  ▼
SentencePiece BPE tokenizer (~16K tokens, vocabulary/tokenizer.model)
  │  undersample dominant families → oversample minority families
  │  HPO (10 Optuna trials, MLX backend)
  ▼
Best PyTorch checkpoint (final-model/model.pt)
  │  TacticEvaluator.evaluate
  │  ModelQuantizer.quantize (FP32 ONNX export)
  ▼
final-model/{tactic-predictor.onnx, tactic-labels.json, vocabulary/tokenizer.model}
  │  scripts/publish-model.sh — flattens vocabulary into release assets
  ▼
GitHub Release: tactic-predictor.onnx + tactic-labels.json + tokenizer.model
  │  staged into $POULE_DATA_DIR
  ▼
suggest_tactics MCP tool → neural predictions active
```

## Step 1: Extract training data

Extract proof traces with per-step tactic annotations from Coq libraries. The extraction pipeline replays each proof, recording the proof state and tactic text at each step.

```bash
# Extract from the Coq/Rocq standard library
poule extract /opt/opam/coq/lib/coq/user-contrib/Stdlib --output stdlib.jsonl

# Multi-project extraction in a single campaign
poule extract \
  /opt/opam/coq/lib/coq/user-contrib/Stdlib \
  /opt/opam/coq/lib/coq/user-contrib/stdpp \
  /opt/opam/coq/lib/coq/user-contrib/Flocq \
  /opt/opam/coq/lib/coq/user-contrib/Coquelicot \
  /opt/opam/coq/lib/coq/user-contrib/mathcomp \
  --output training-data.jsonl
```

**Library selection.** The canonical training set is five libraries: Stdlib, stdpp, Flocq, Coquelicot, and MathComp. CoqInterval is excluded — its specialized proof style does not transfer to general theorems. MathComp is included in the training pool to provide SSReflect signal but is held *out* of LOOCV folds (LOOCV diagnoses transfer between vanilla-Coq libraries only).

Each line in the output is a self-contained JSON object. The key record types:

| Record type | Description |
|-------------|-------------|
| `campaign_metadata` | Provenance (Coq version, project commits, tool version) — first line |
| `"s"` (step) | Per-tactic-step record: proof state + tactic command text |
| `"g"` (goal) | Supplementary goal states for vocabulary construction |
| `extraction_error` | One per failed proof — error kind and message |
| `extraction_summary` | Counts (found, extracted, failed, skipped) — last line |

The `"s"` records are the training data: each contains a serialized proof state (the goals and hypotheses before the tactic) and the tactic command text that was applied. The five target libraries yield ~140,000 such records.

## Step 2: Validate training data

Check extracted data for quality issues before committing compute time.

```bash
poule validate-training-data training-data.jsonl
```

The validator reports:
- Total step records and steps with missing tactic text
- Tactic family distribution (frequency of each family)
- Class imbalance warnings (dominant families that may need stronger weighting)

A minimum of 10,000 steps is recommended; the five target libraries combined yield ~140,000.

## Step 3: Build the BPE vocabulary

Train a SentencePiece byte-pair-encoding (BPE) tokenizer on the serialized proof states. The earlier closed-vocabulary approach (one token per fully-qualified identifier, ~158K tokens with ALBERT-style factorization) has been retired in favour of a ~16K BPE vocabulary with full-rank embeddings — see [doc/neural-network-tactic-prediction.md](neural-network-tactic-prediction.md#bpe-tokenization) for the rationale.

The BPE builder is invoked from `scripts/run-full-training.py` and writes a tokenizer directory rather than a single JSON file:

```python
from Poule.neural.training.vocabulary import BpeVocabularyBuilder

BpeVocabularyBuilder.build(
    jsonl_paths=[Path("training.jsonl")],
    output_dir=Path("$POULE_DATA_DIR/vocabulary"),
)
```

Output layout:

```
vocabulary/
└── tokenizer.model   # SentencePiece model (~16K tokens)
```

Special tokens (`[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]`), structural markers (`[HYP]`, `[TYPE]`, `[BODY]`, `[GOAL]`, `[GOALSEP]`), and context features (`[PREV=…]`, `[DEPTH=…]`, `[NGOALS=…]`, `[HEAD=…]`) are registered as user-defined symbols so they remain atomic and never split.

> The legacy `poule build-vocabulary` CLI still exists but invokes the older closed-vocabulary builder; it is retained only for compatibility with prior models.

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
# Train with the BPE tokenizer directory (auto-detects tokenizer.model inside)
poule train \
  --vocabulary $POULE_DATA_DIR/vocabulary \
  --output model.pt \
  training.jsonl

# Quick end-to-end test (for testing only)
poule train \
  --vocabulary $POULE_DATA_DIR/vocabulary \
  --output model.pt \
  --sample 0.15 \
  --epochs 2 \
  training.jsonl
```

The `--sample` flag randomly sub-samples the training split to the given fraction. Validation and test splits are not affected. **This is for test runs only.**

### Resampling: undersample dominant, oversample minority

The dominant tactic families (`rewrite`, `apply`, `intros`, …) contain thousands of near-identical proof states; the rarest families have fewer than 50 examples. `scripts/run-full-training.py` applies two complementary corrections in sequence:

1. **Undersample at cap = 2,000.** Each family is capped at 2,000 training examples (~95K → ~40K). Families with fewer than `5% × cap = 100` examples are dropped as too sparse to learn.
2. **Oversample at floor = 500 (25% × cap).** Each remaining family below the floor is upsampled (with replacement) to the floor. This guarantees a baseline gradient signal for tail families on every epoch without distorting head families.

Class weights are then recomputed from the resampled distribution, so resampling and class weighting compose.

The standalone `train` CLI exposes only `--undersample-cap` and `--undersample-seed` (default 42). The oversampling step is currently invoked from the script directly, via `oversample_train(dataset, floor=500)`.

Training details:
- **Architecture**: CodeBERT encoder initialized from `microsoft/codebert-base`, with a fresh full-rank 768-d embedding layer sized to the BPE vocabulary (~16K tokens). Tokens that overlap with CodeBERT's original RoBERTa vocab inherit pretrained weights; the rest initialize from N(0, 0.02). Mean pooling feeds a hierarchical classification head (8 categories × within-category tactic heads, 65 families total).
- **Encoder depth**: Configurable `num_hidden_layers` ∈ {4, 6, 8, 12}. When fewer than 12 layers are used, layers are selected at evenly spaced indices from CodeBERT's 12 layers (layer dropping; e.g. 6 layers → indices 0, 2, 4, 6, 8, 10).
- **Loss**: Class-weighted cross-entropy with class-conditional label smoothing. Weights use the tunable inverse-frequency power law `weight[c] = (total / (num_classes × count[c])) ^ alpha`. Joint loss is `L = L_category + λ_within × L_within(active head)`.
- **Optimizer**: Sharpness-Aware Minimization (SAM) wrapped around AdamW. SAM perturbs parameters by `ρ` along the gradient before computing the update, biasing optimization toward flat minima.
- **Split**: Deterministic file-level split — position % 10 == 8 → validation, == 9 → test, rest → training.
- **Early stopping**: Halts when validation accuracy@5 fails to improve for `patience` consecutive epochs (default 3).
- **MLX training**: Pre-tokenizes all data, uses length-bucketed batching to reduce attention cost on variable-length sequences, evaluates lazily per micro-batch. Safetensors checkpoints are auto-converted to PyTorch `.pt` for downstream inference.

### Hyperparameter optimization

The training pipeline includes an Optuna-based hyperparameter tuner that searches over model architecture and training configuration jointly:

```bash
poule tune \
  --vocabulary $POULE_DATA_DIR/vocabulary \
  --output hpo-results/ \
  --n-trials 10 \
  --study-name poule-hpo-undersampled \
  --resume \
  training.jsonl
```

The tuner searches over 8 hyperparameters:

| Hyperparameter | Range | Default |
|---|---|---|
| `num_hidden_layers` | {4, 6, 8} | 6 |
| `learning_rate` | [1e-6, 1e-4] log-uniform | 2e-5 |
| `batch_size` | {16, 32, 64} | 32 |
| `weight_decay` | [1e-4, 1e-1] log-uniform | 1e-2 |
| `class_weight_alpha` | [0.0, 1.0] | 0.4 |
| `label_smoothing` | [0.0, 0.2] | 0.1 |
| `sam_rho` | [0.15, 0.3] | 0.15 |
| `lambda_within` | [0.3, 3.0] log-uniform | 1.0 |

The study uses TPE sampling with a `MedianPruner` (3 startup trials, 3 warmup epochs). Only completed and pruned trials count toward the budget — failed trials are not charged. Study state persists to SQLite (`hpo-study.db`) for crash recovery with `--resume`; rerunning with the same `--study-name` extends the study rather than restarting it. The best trial's checkpoint is copied to `best-model.pt`, which `run-full-training.py` then promotes to `final-model/model.pt`.

### Leave-one-library-out cross-validation

The file-level split scatters files from the same library across train/val/test. Libraries share tactic conventions (Stdlib favors `destruct`/`induction`, stdpp has its own automation), so the model may memorize library identity rather than learning generalizable proof structure. LOOCV diagnoses this by holding out each vanilla-Coq library in turn as the test set.

MathComp is *always trained on, never held out*: its SSReflect-dialect tactics (~71% of steps) are essential training signal but would dominate any held-out fold. `run-full-training.py` enforces this via `ALWAYS_TRAIN_LIBRARIES = ["mathcomp"]`. CoqInterval is excluded entirely from both training and LOOCV.

```bash
# Run LOOCV across all 5 libraries — MathComp stays in training every fold
poule loocv \
  stdlib.jsonl stdpp.jsonl \
  flocq.jsonl coquelicot.jsonl mathcomp.jsonl \
  --output-dir loocv-results/ \
  --vocabulary $POULE_DATA_DIR/vocabulary \
  --undersample-cap 1000
```

Each JSONL file's stem is used as the library name. For each fold (4 rotations — Stdlib, stdpp, Flocq, Coquelicot), the command:
1. Holds out the chosen library entirely as the test set (MathComp stays in training)
2. Splits the remaining libraries' files 90/10 (seeded shuffle) for train/val
3. Undersamples training at cap=1000 per family
4. Trains with the best HPO hyperparameters
5. Evaluates on the held-out library

The aggregate report (`loocv-results/loocv-report.json`) contains mean/std of test_acc@5 across folds and per-library accuracy. Interpretation:

| Outcome | Meaning |
|---------|---------|
| Mean test_acc@5 ≈ 57% (current baseline) | Library leakage is not the bottleneck |
| Mean test_acc@5 drops to 30–40% | Model learns library style, not proof structure |
| High variance across folds | Some libraries transfer well, others don't |

The `--undersample-cap` defaults to 1000 (lower than the standard 2000) because holding out a library shrinks the training pool. The `--backend` flag selects `mlx` (default) or `pytorch`. From `run-full-training.py`, LOOCV is gated behind `RUN_LOOCV=1` since each fold trains a full model.

## Step 5: Evaluate the model

Measure tactic prediction accuracy on the held-out test set.

```bash
poule evaluate --checkpoint final-model/model.pt --test-data training.jsonl
```

Reports accuracy@1, accuracy@5, category accuracy@1, per-category accuracy, per-family precision/recall, and zero-recall family count. Warnings are emitted if:
- accuracy@1 < 40%
- accuracy@5 < 80%
- category accuracy@1 < 80%

`run-full-training.py` additionally writes a `final-model-validation.txt` summary that includes the dataset sizes, HPO budget, best hyperparameters, per-category accuracy, per-family precision/recall, trainable-coverage tiers (≥100 and ≥200 examples), and a pass/fail block for the success criteria (`test_acc@5 > 57.0%`, `category_acc@1 > 35%`, coverage thresholds).

## Step 6: Export to ONNX

Export the PyTorch checkpoint to ONNX for cross-platform CPU inference.

```bash
poule quantize --checkpoint final-model/model.pt --output final-model/tactic-predictor.onnx
```

The export pipeline:
1. Loads the checkpoint and reconstructs the model (respecting `num_hidden_layers`)
2. Exports to ONNX via the torch dynamo exporter (opset 17+)
3. Validates by comparing predicted labels between PyTorch and ONNX across 100 random inputs — fails if agreement < 98%
4. Writes `tactic-labels.json` alongside the ONNX model. For the hierarchical model this is a `{"categories": [...], "per_category": {...}}` object whose flattened ordering matches the ONNX output indices.

The exported model is FP32. INT8 quantization is not applied — see the [design doc](neural-network-tactic-prediction.md) for rationale.

## Step 7: Deploy

The ONNX model, label file, and tokenizer must be placed in the data directory so the `suggest_tactics` MCP tool can find them. `TacticPredictor.load_default()` looks for three filenames *flat* in `POULE_DATA_DIR`:

| File | Source |
|------|--------|
| `tactic-predictor.onnx` | `final-model/tactic-predictor.onnx` |
| `tactic-labels.json` | `final-model/tactic-labels.json` |
| `tokenizer.model` | `final-model/vocabulary/tokenizer.model` |

`POULE_DATA_DIR` resolves as follows:

| Context | `POULE_DATA_DIR` | Set by |
|---------|-----------------|--------|
| Production container (`bin/poule`) | `/data` | Dockerfile + launcher |
| Dev container (`bin/poule-dev`) | `/data` (bind-mount of `~/poule-home/data`) | Launcher |
| Host-side development | `~/poule-home/data` (default) | Not set — uses default |

**For developers (training on the host Mac):** Artifacts land in `~/poule-home/data/final-model/` by default, which is bind-mounted as `/data` inside the dev container. Stage the three files into the data directory root:

```bash
cp ~/poule-home/data/final-model/tactic-predictor.onnx     ~/poule-home/data/
cp ~/poule-home/data/final-model/tactic-labels.json        ~/poule-home/data/
cp ~/poule-home/data/final-model/vocabulary/tokenizer.model ~/poule-home/data/
```

**For developers (training inside the dev container):**

```bash
cp $POULE_DATA_DIR/final-model/tactic-predictor.onnx     $POULE_DATA_DIR/
cp $POULE_DATA_DIR/final-model/tactic-labels.json        $POULE_DATA_DIR/
cp $POULE_DATA_DIR/final-model/vocabulary/tokenizer.model $POULE_DATA_DIR/
```

When these files are present, `suggest_tactics` automatically includes neural predictions alongside rule-based suggestions. When absent, it falls back to rule-based suggestions only — no errors, no degradation.

## Step 8: Publish

For users, model artifacts are distributed as GitHub releases and baked into the production Docker image. Use the publish script after quantization:

```bash
# Quantize first (Step 6) — wraps poule quantize with the canonical paths
./scripts/quantize-model.sh

# Publish as a GitHub release (requires gh CLI, authenticated)
./scripts/publish-model.sh
```

The script:
1. Reads `tactic-predictor.onnx`, `tactic-labels.json`, and `vocabulary/tokenizer.model` from `$POULE_DATA_DIR/final-model/` and flattens them into release assets
2. Computes SHA-256 checksums and generates a `manifest.json`
3. Replaces the existing `tactic-model` GitHub release (there is always exactly one)
4. Users receive the model via `poule download-index --include-model` or by pulling the latest Docker image

## End-to-end example: training the canonical model

The recommended path is `scripts/run-full-training.py`, which performs every step from vocabulary build through ONNX export and writes a validation report. It assumes `$POULE_DATA_DIR/training.jsonl` already exists (from extract → validate → collapse).

```bash
COQ_LIBS="/opt/opam/coq/lib/coq/user-contrib"
export POULE_DATA_DIR="${POULE_DATA_DIR:-$HOME/poule-home/data}"

# 1. Extract training data — 5 libraries (CoqInterval excluded; MathComp included for SSReflect signal)
poule extract \
  $COQ_LIBS/Stdlib \
  $COQ_LIBS/stdpp \
  $COQ_LIBS/Flocq \
  $COQ_LIBS/Coquelicot \
  $COQ_LIBS/mathcomp \
  --output $POULE_DATA_DIR/training-data.jsonl

# 2. Validate
poule validate-training-data $POULE_DATA_DIR/training-data.jsonl

# 3. Collapse training data (normalize tactic families, e.g. apply/eqP -> apply)
poule collapse-training-data \
  --output $POULE_DATA_DIR/training.jsonl \
  $POULE_DATA_DIR/training-data.jsonl

# 4. Run the full pipeline: BPE vocab + undersample/oversample + HPO + promote + evaluate + ONNX export
python scripts/run-full-training.py
# (Set RUN_LOOCV=1 to additionally run leave-one-library-out cross-validation.)

# 5. Stage artifacts into the data directory root for suggest_tactics
cp $POULE_DATA_DIR/final-model/tactic-predictor.onnx     $POULE_DATA_DIR/
cp $POULE_DATA_DIR/final-model/tactic-labels.json        $POULE_DATA_DIR/
cp $POULE_DATA_DIR/final-model/vocabulary/tokenizer.model $POULE_DATA_DIR/

# 6. Publish (requires gh CLI, authenticated)
./scripts/publish-model.sh
```

For granular control — re-running a single phase, debugging a specific HPO trial, or trying a different `--backend` — use the per-step CLI commands documented in Steps 3–6 above.
