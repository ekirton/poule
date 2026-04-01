# Model Training CLI

Command-line tools for training, evaluating, and deploying the neural tactic prediction model from extracted Coq proof trace data.

---

## Problem

Neural tactic prediction requires a trained classifier model. Training requires proof trace data (produced by the Training Data Extraction pipeline), compute resources, and expertise in configuring training runs. The project needs to support two distinct workflows:

1. **Project maintainers** train the canonical model on data from six Coq libraries and ship the checkpoint with the tool
2. **AI researchers** train experimental models with different architectures, hyperparameters, or training data and evaluate them against baselines

## Solution

A set of CLI commands that handle the full training lifecycle:

- **Build-vocabulary**: Given a search index and extracted training data, build a closed-vocabulary tokenizer that maps every Coq identifier, syntax token, and Unicode symbol to a unique integer ID
- **Train**: Given extracted proof trace data and a vocabulary, train a tactic family classifier from a pre-trained CodeBERT encoder
- **Evaluate**: Given a trained model and a held-out test set, compute tactic prediction accuracy metrics (accuracy@k, per-family precision/recall)
- **Validate**: Given extracted proof trace data, check for completeness, tactic family distribution, and class imbalance before committing to a training run
- **Quantize**: Given a trained model, produce an INT8 quantized ONNX checkpoint for CPU inference

## Training Data Requirements

The training pipeline consumes `(proof_state, tactic_text)` pairs in the JSON Lines format produced by the Training Data Extraction pipeline. The `"s"` (step) records contain a serialized proof state and the tactic command text. The six target libraries yield ~105,000 such pairs.

The validation command checks the data before training starts, reporting:
- Count of valid step records and records with missing tactic text
- Tactic family distribution (frequency of each family)
- Class imbalance warnings (dominant families that may require stronger class weighting)

This catches common data quality issues before compute time is committed.

## Evaluation Framework

Evaluation measures how well the model predicts the correct tactic family for a given proof state. The evaluation command computes:

- **Accuracy@1**: Percentage of test examples where the top-1 prediction matches the ground truth tactic family
- **Accuracy@5**: Percentage where the correct family appears in the top-5 predictions
- **Per-family precision and recall**: Identifies which tactic families the model predicts well vs. poorly
- **Confusion matrix**: Shows systematic mispredictions between similar tactic families

The deployment thresholds are accuracy@1 >= 40% and accuracy@5 >= 80%. If either threshold is not met, the evaluation command emits a warning.

## Compute Constraints

Training must complete on a single consumer GPU (<=24GB VRAM), Apple Silicon Mac (>=32GB unified memory) using MLX, or be offloadable to a cloud GPU within a $100 budget. The tactic classifier is simpler than a contrastive bi-encoder (single forward pass, no premise encoding), so training is faster and cheaper than the original premise retrieval model would have been.

## MLX Training Backend

Project maintainers training on Apple Silicon Macs use MLX instead of PyTorch. MLX is Apple's array framework designed for unified memory — it eliminates the memory leak issues that make PyTorch MPS impractical for training on 32GB Macs.

The MLX backend provides the same training workflow but produces MLX-format checkpoints. A conversion command transforms MLX checkpoints into PyTorch format, which feeds into the existing ONNX quantization pipeline unchanged.

## Design Rationale

### Why CLI, not a library API

The training workflow is batch-oriented: prepare data, start training, wait for completion, evaluate results. This maps naturally to CLI commands that can be scripted, run in CI, or invoked from cloud GPU instances.

### Why separate validate and train steps

Training costs compute time and real money. Validating the input data is instant and catches the most common failure modes (incomplete extraction, wrong format, degenerate distributions). Separating these steps follows the principle of failing fast and cheaply.

### Why a closed vocabulary rather than subword tokenization

CodeBERT's generic BPE tokenizer fragments Coq identifiers (`Nat.add_comm` -> 5 tokens, `ssreflect` -> 3 tokens), wasting the 512-token context window. Coq's vocabulary is closed: ~118K library identifiers, ~33K variable names and syntax fragments from training data, ~110 fixed tokens, ~64 Unicode symbols — all known at index time. A closed-vocabulary tokenizer assigns every identifier exactly 1 token via O(1) dictionary lookup. CFR (Zhu et al., 2025) demonstrated +33% Recall@5 from domain-specific tokenization alone.

---

## Acceptance Criteria

### Build a Closed Vocabulary from the Search Index and Training Data

**Priority:** P0
**Stability:** Stable
**Traces to:** R6-P0-13, R6-P0-14

- GIVEN a search index database and one or more JSON Lines extraction files WHEN the build-vocabulary command is run THEN a JSON file mapping tokens to sequential integer IDs is produced
- GIVEN the vocabulary output WHEN inspected THEN it contains special tokens, fixed token sets, and identifiers from the index and training data
- GIVEN the vocabulary WHEN used to tokenize a held-out proof state THEN the `[UNK]` rate is < 1%

### Train a Tactic Classifier from Extracted Data

**Priority:** P0
**Stability:** Stable
**Traces to:** R6-P0-9

- GIVEN JSON Lines extraction files containing `"s"` records WHEN the train command is run THEN a tactic classifier checkpoint is produced
- GIVEN extracted data containing ~105,000 `(proof_state, tactic_text)` pairs WHEN training completes THEN the output includes loss curves and validation accuracy@5
- GIVEN the training command WHEN a CUDA-capable GPU is available THEN training uses it automatically; otherwise falls back to CPU with a duration warning

### Validate Training Data Before Training

**Priority:** P1
**Stability:** Stable
**Traces to:** R6-P1-1

- GIVEN JSON Lines extraction files WHEN the validation command is run THEN it reports the count of valid `"s"` records, records with missing tactic text, and tactic family distribution
- GIVEN a dataset with severe class imbalance WHEN validation completes THEN a warning is emitted with the imbalanced family names and their frequencies

### Evaluate Tactic Prediction Accuracy

**Priority:** P0
**Stability:** Stable
**Traces to:** R6-P0-10

- GIVEN a trained model checkpoint and a held-out test set WHEN the evaluate command is run THEN it reports accuracy@1, accuracy@5, and per-family precision/recall
- GIVEN the evaluation results WHEN accuracy@1 < 40% or accuracy@5 < 80% THEN a warning is emitted

### Tune Hyperparameters Automatically

**Priority:** P1
**Stability:** Draft
**Traces to:** R6-P1-3

- GIVEN extracted data and a search index WHEN the tune command is run THEN it performs automated hyperparameter optimization over learning rate, batch size, and class weight exponent, maximizing validation accuracy@5
- GIVEN a tuning study WHEN underperforming trials are detected THEN they are pruned early to save compute

### Train with MLX on Apple Silicon

**Priority:** P0
**Stability:** Draft
**Traces to:** R6-P0-15

- GIVEN extracted data and a vocabulary WHEN the train command is run with `--backend mlx` on an Apple Silicon Mac THEN a tactic classifier checkpoint is produced in MLX format
- GIVEN an MLX-trained checkpoint WHEN the convert command is run THEN a PyTorch checkpoint compatible with ONNX quantization is produced
