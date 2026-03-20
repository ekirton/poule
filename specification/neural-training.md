# Neural Training Pipeline

Training, evaluation, fine-tuning, and quantization pipeline for the neural premise selection model.

**Architecture**: [neural-training.md](../doc/architecture/neural-training.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the training pipeline that produces neural encoder model checkpoints from extracted Coq proof trace data: data loading and validation, bi-encoder training with masked contrastive loss, evaluation against retrieval quality thresholds, fine-tuning from pre-trained checkpoints, and INT8 quantization for CPU deployment.

## 2. Scope

**In scope**: `TrainingDataLoader` (JSONL parsing, pair extraction, train/val/test split, hard negative sampling), `BiEncoderTrainer` (training loop, masked contrastive loss, checkpointing), `RetrievalEvaluator` (recall@k, MRR, neural vs. symbolic comparison), `ModelQuantizer` (PyTorch → INT8 ONNX conversion, validation), `TrainingDataValidator` (pre-training data quality checks).

**Out of scope**: Neural encoder inference at query time (owned by neural-retrieval), embedding index construction (owned by neural-retrieval), retrieval pipeline integration (owned by pipeline), storage schema (owned by storage).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Training pair | A `(proof_state_text, premises_used_names)` tuple extracted from a proof trace step |
| Positive premise | A premise that appears in `premises_used` for a given proof state |
| Hard negative | A premise that is accessible to the theorem but not used in the proof step |
| Accessible premise | A premise whose source file is in the transitive file-dependency closure of the theorem's file |
| Masked contrastive loss | InfoNCE variant where shared positives (premises positive for other states in the batch) are excluded from the negative set |

## 4. Behavioral Requirements

### 4.1 TrainingDataLoader

#### load(jsonl_paths, index_db_path)

- REQUIRES: `jsonl_paths` is a non-empty list of paths to JSON Lines extraction output files. `index_db_path` points to a valid index database containing the premise corpus.
- ENSURES: Returns a `TrainingDataset` containing all valid `(proof_state_text, premises_used_names)` pairs, the premise corpus (from the index database), and train/validation/test splits.

#### Pair extraction

Each ExtractionStep contains the proof state (goals, hypotheses) *after* the step's tactic was applied, plus the premises used by that tactic. Step 0 is the initial state with no tactic. The training pair for a tactic at step k uses the proof state from step k-1 (the state before the tactic) paired with the premises from step k:

```
For each ExtractionRecord in the JSONL files:
    For step_index k = 1 to len(record.steps) - 1:
        state_text = serialize_goals(record.steps[k-1].goals)
        premises = [p.name for p in record.steps[k].premises if p.kind != "hypothesis"]
        If len(premises) > 0:
            Emit (state_text, premises)
```

**Proof state serialization** (`serialize_goals`): The goal list shall be serialized to a single text string. For each goal, format as: all hypotheses (each as `name : type`), then the goal type, separated by newlines. Multiple goals are separated by a blank line. This produces deterministic, human-readable text suitable as encoder input.

**Hypothesis filtering**: Premises with `kind == "hypothesis"` shall be excluded from `premises_used` because local hypotheses are not entries in the premise corpus and cannot be retrieved. Steps where all premises are local hypotheses (empty `premises_used` after filtering) shall be skipped.

Steps with empty premise lists (e.g., `reflexivity`, `assumption`) shall also be skipped — they provide no training signal.

> **Given** an ExtractionRecord with 6 steps (step 0 = initial, steps 1–5 = tactics), where steps 1, 3, 4 have non-empty global premises after hypothesis filtering
> **When** pairs are extracted
> **Then** 3 training pairs are emitted, each pairing the goals from the previous step with the global premises from the current step

> **Given** an ExtractionStep at index 2 whose premises are all `kind: "hypothesis"`
> **When** pairs are extracted for this step
> **Then** this step is skipped (no training pair emitted)

#### Train/validation/test split

Files shall be split deterministically by fully qualified source file path:

1. Sort all unique source file paths lexicographically
2. Assign files at positions where `position % 10 == 8` to validation
3. Assign files at positions where `position % 10 == 9` to test
4. Assign all remaining files to training

All pairs from the same file go into the same split.

- MAINTAINS: No pair from the same source file appears in more than one split.

> **Given** 100 source files sorted lexicographically
> **When** the split is computed
> **Then** files at indices 8, 18, 28, ... → validation; indices 9, 19, 29, ... → test; all others → train

### 4.2 Hard Negative Sampling

#### sample_hard_negatives(state, positive_premises, accessible_premises, k=3)

- REQUIRES: `state` is a proof state text. `positive_premises` is the set of premises used. `accessible_premises` is the set of all premises accessible to the theorem. `k` is a positive integer.
- ENSURES: Returns `k` premise names sampled uniformly from `accessible_premises \ positive_premises`. If `|accessible_premises \ positive_premises| < k`, returns all available. If `accessible_premises` is empty or unavailable, samples from the full premise corpus as fallback.

#### Accessibility approximation

Accessibility is approximated at the file level using the dependency graph:

```
accessible_files(theorem) = transitive closure of file-level imports from the theorem's source file
accessible_premises(theorem) = all premises defined in accessible_files(theorem)
```

- REQUIRES: The index database contains a `dependencies` table with file-level dependency edges.
- When the `dependencies` table is empty or missing: fall back to sampling from the full premise corpus.

> **Given** theorem T in file F, and F imports files A, B (which imports C)
> **When** accessible premises are computed for T
> **Then** accessible set includes all premises from F, A, B, and C

### 4.3 BiEncoderTrainer

#### train(dataset, output_path, hyperparams)

- REQUIRES: `dataset` is a `TrainingDataset` with at least 1,000 training pairs. `output_path` is a writable path. `hyperparams` has defaults as specified below.
- ENSURES: Trains a bi-encoder model using masked contrastive loss. Saves the best checkpoint (by validation Recall@32) to `output_path`. Prints training metrics (loss, validation Recall@32) after each epoch.
- On training completion: saves final checkpoint alongside best checkpoint.
- On GPU OOM: raises `TrainingResourceError` with message suggesting batch size reduction.

**Default hyperparameters:**

| Parameter | Default | Constraint |
|-----------|---------|-----------|
| `batch_size` | 256 | Must be positive |
| `learning_rate` | 2e-5 | Must be positive |
| `weight_decay` | 1e-2 | Must be non-negative |
| `temperature` | 0.05 | Must be positive |
| `hard_negatives_per_state` | 3 | Must be non-negative |
| `max_seq_length` | 512 | Must be positive |
| `max_epochs` | 20 | Must be positive |
| `early_stopping_patience` | 3 | Must be positive |
| `embedding_dim` | 768 | Fixed — not configurable |

#### Masked contrastive loss

For a batch of B proof states `{s_1, ..., s_B}`, each with positive premises `P_i` and hard negatives `N_i`:

For each positive pair `(s_i, p_ij)`:
```
candidates = {p_ij} ∪ N_i ∪ {all p_kl for k ≠ i where p_kl ∉ P_i}
                                                       ^^^^^^^^^^^
                                                       Masking condition

loss_ij = -log( exp(cos_sim(s_i, p_ij) / τ) / Σ_c∈candidates exp(cos_sim(s_i, c) / τ) )
```

The loss masks out any premise that is a positive for the current proof state `s_i`, preventing shared premises (e.g., `Nat.add_comm`) from generating false negative signal.

- MAINTAINS: Temperature τ is applied as a divisor inside the exponential, not as a scaling factor outside.

> **Given** proof state s_1 uses premise P, and proof state s_2 also uses premise P in the same batch
> **When** the contrastive loss is computed for s_1
> **Then** premise P is excluded from the negative set for s_1 (masked)

#### Early stopping

After each epoch, compute Recall@32 on the validation split. If validation Recall@32 does not improve for `early_stopping_patience` consecutive epochs, stop training and retain the best checkpoint.

> **Given** patience=3 and validation R@32 does not improve for epochs 8, 9, 10
> **When** epoch 10 completes
> **Then** training stops and the checkpoint from epoch 7 (last improvement) is retained as the best model

#### Checkpoint format

The checkpoint shall include:
- Model state dict (encoder weights)
- Optimizer state dict
- Epoch number
- Best validation Recall@32
- Hyperparameters used

### 4.4 Fine-Tuning

#### fine_tune(checkpoint_path, dataset, output_path, hyperparams)

- REQUIRES: `checkpoint_path` points to a valid training checkpoint. `dataset` contains project-specific training pairs. `output_path` is writable.
- ENSURES: Loads the pre-trained checkpoint. Resumes training with adjusted hyperparameters. Saves best fine-tuned checkpoint by validation Recall@32.

**Fine-tuning hyperparameter overrides:**

| Parameter | Override | Rationale |
|-----------|----------|-----------|
| `learning_rate` | 5e-6 (default) | Lower LR to avoid catastrophic forgetting |
| `max_epochs` | 10 (default) | Smaller dataset converges faster |

All other hyperparameters default to the same values as `train`.

> **Given** a pre-trained checkpoint and 2,000 project-specific training pairs
> **When** `fine_tune` runs on a consumer GPU (≤ 24GB VRAM)
> **Then** fine-tuning completes in under 4 hours

### 4.5 RetrievalEvaluator

#### evaluate(checkpoint_path, test_data, index_db_path)

- REQUIRES: `checkpoint_path` points to a valid model checkpoint. `test_data` is a list of `(proof_state_text, premises_used_names)` pairs. `index_db_path` points to a valid index database.
- ENSURES: Loads the model. For each test state, encodes it, retrieves top-k premises from the full premise corpus, and computes retrieval metrics. Returns an `EvaluationReport`.

**EvaluationReport fields:**

| Field | Type | Definition |
|-------|------|-----------|
| `recall_at_1` | float | Fraction of states with ≥1 correct premise in top-1 |
| `recall_at_10` | float | Fraction of states with ≥1 correct premise in top-10 |
| `recall_at_32` | float | Fraction of states with ≥1 correct premise in top-32 |
| `mrr` | float | Mean reciprocal rank of the first correct premise |
| `test_count` | integer | Number of test pairs evaluated |
| `mean_premises_per_state` | float | Average ground-truth premises per test state |
| `mean_query_latency_ms` | float | Average encode + search time per query |

When `recall_at_32 < 0.50`, the report shall include a warning: `"Model does not meet deployment threshold (Recall@32 < 50%)"`.

> **Given** a test set of 1,000 pairs
> **When** `evaluate` completes
> **Then** returns an EvaluationReport with all metrics computed

#### compare(checkpoint_path, test_data, index_db_path)

- REQUIRES: Same as `evaluate`, plus the index database must have WL histograms, inverted index, and symbol frequencies loaded (for symbolic retrieval).
- ENSURES: Runs three retrieval configurations on the same test data and returns a `ComparisonReport`.

**ComparisonReport fields:**

| Field | Type | Definition |
|-------|------|-----------|
| `neural_recall_32` | float | Recall@32 using neural channel only |
| `symbolic_recall_32` | float | Recall@32 using existing pipeline channels only |
| `union_recall_32` | float | Recall@32 from the union of neural and symbolic top-32, re-ranked by RRF |
| `relative_improvement` | float | `(union - symbolic) / symbolic` |
| `overlap_pct` | float | Percentage of correct retrievals found by both channels |
| `neural_exclusive_pct` | float | Percentage found only by neural |
| `symbolic_exclusive_pct` | float | Percentage found only by symbolic |

When `relative_improvement < 0.15`, the report shall include a warning: `"Neural channel may not provide sufficient complementary value (union improvement < 15%)"`.

> **Given** test data where neural finds 100 correct retrievals and symbolic finds 120, with 60 overlap
> **When** `compare` computes the report
> **Then** overlap_pct = 60/(100+120-60) = 37.5%, neural_exclusive_pct = 40/160 = 25%, symbolic_exclusive_pct = 60/160 = 37.5%

### 4.6 ModelQuantizer

#### quantize(checkpoint_path, output_path)

- REQUIRES: `checkpoint_path` points to a valid PyTorch training checkpoint. `output_path` is a writable path.
- ENSURES: Exports the model to ONNX (opset 17+). Applies dynamic INT8 quantization. Validates quantization quality. Writes the INT8 ONNX model to `output_path`.

**Validation step:**
1. Generate 100 random input texts (from test set or synthetic)
2. Encode each through both full-precision and quantized models
3. Compute max cosine distance across all 100 pairs
4. If max cosine distance ≥ 0.02: raise `QuantizationError` with the distance value

> **Given** a trained model checkpoint
> **When** `quantize` runs
> **Then** produces an INT8 ONNX file at `output_path` with max cosine distance < 0.02 from full precision

### 4.7 TrainingDataValidator

#### validate(jsonl_paths)

- REQUIRES: `jsonl_paths` is a non-empty list of paths to JSON Lines extraction output files.
- ENSURES: Scans all files in a single pass. Returns a `ValidationReport`.

**ValidationReport fields:**

| Field | Type | Definition |
|-------|------|-----------|
| `total_pairs` | integer | Total `(state, premises)` pairs with non-empty premise lists |
| `empty_premise_pairs` | integer | Steps with empty premise lists (skipped) |
| `malformed_pairs` | integer | Steps with missing or invalid `goals` or `premises` fields |
| `unique_premises` | integer | Distinct premise names across all pairs |
| `unique_states` | integer | Distinct proof state texts across all pairs |
| `top_premises` | list of (name, count) | 10 most frequently referenced premises |
| `warnings` | list of string | Human-readable warning messages |

**Warning conditions:**

| Condition | Warning message |
|-----------|----------------|
| `empty_premise_pairs / (total_pairs + empty_premise_pairs) > 0.10` | `"Over 10% of steps have empty premise lists — check extraction quality for files: {affected_files}"` |
| `malformed_pairs > 0` | `"Found {n} malformed pairs — check extraction output format"` |
| `total_pairs < 5000` | `"Only {n} training pairs — model quality may be limited"` |
| `unique_premises < 1000` | `"Only {n} unique premises — embedding space may be under-constrained"` |
| Any premise accounts for > 5% of all occurrences | `"Premise {name} accounts for {pct}% of all occurrences — may dominate training"` |

> **Given** a JSONL file with 50,000 steps, 35,000 with non-empty premises
> **When** `validate` runs
> **Then** returns report with total_pairs=35,000, empty_premise_pairs=15,000, no warnings (30% empty is common)

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| JSONL file not found | `FileNotFoundError` | Propagated to CLI |
| JSONL parse error (invalid JSON on a line) | `DataFormatError` | Line skipped, counted as malformed pair |
| Index database not found | `IndexNotFoundError` | Propagated to CLI |
| Checkpoint file not found | `CheckpointNotFoundError` | Propagated to CLI |
| GPU out of memory during training | `TrainingResourceError` | Propagated with batch size suggestion |
| Quantization validation failure (distance ≥ 0.02) | `QuantizationError` | Propagated with max distance value |
| Training dataset has < 1,000 pairs after filtering | `InsufficientDataError` | Propagated to CLI |
| Validation split is empty | `InsufficientDataError` | Propagated (split has 0 files in validation position) |

Error hierarchy:
- `NeuralTrainingError` — base class for all training pipeline errors
  - `DataFormatError` — JSONL parse or schema error
  - `CheckpointNotFoundError` — model checkpoint missing
  - `TrainingResourceError` — GPU OOM or insufficient compute
  - `QuantizationError` — INT8 conversion quality check failed
  - `InsufficientDataError` — not enough training data

## 6. Non-Functional Requirements

| Metric | Target |
|--------|--------|
| Training time (50K pairs, 24GB GPU) | < 8 hours |
| Training time (10K pairs, 24GB GPU) | < 2 hours |
| Fine-tuning time (2K pairs, 24GB GPU) | < 4 hours |
| Validation pass (per epoch) | < 60 seconds |
| Data validation (single pass, 100K steps) | < 30 seconds |
| Quantization (export + validate) | < 5 minutes |
| Peak GPU memory (batch_size=256, seq_len=512) | ≤ 24GB |

## 7. Examples

### Full training workflow

```
# 1. Validate data
report = validate(["stdlib.jsonl", "mathcomp.jsonl"])
# report.total_pairs = 45,000, no warnings

# 2. Load data
dataset = load(["stdlib.jsonl", "mathcomp.jsonl"], "index.db")
# dataset.train: 36,000 pairs, dataset.val: 4,500 pairs, dataset.test: 4,500 pairs

# 3. Train
train(dataset, "model.pt", hyperparams={batch_size: 256, lr: 2e-5, epochs: 20})
# Epoch 1: loss=4.2, val_R@32=0.18
# Epoch 2: loss=3.1, val_R@32=0.32
# ...
# Epoch 12: loss=1.4, val_R@32=0.54 (best)
# Epoch 13-15: no improvement → early stopping

# 4. Evaluate
eval_report = evaluate("model.pt", dataset.test, "index.db")
# R@1=0.22, R@10=0.41, R@32=0.52, MRR=0.35

# 5. Compare with symbolic
comp_report = compare("model.pt", dataset.test, "index.db")
# neural R@32=0.52, symbolic R@32=0.38, union R@32=0.55
# relative_improvement = 0.45 (45% — well above 15% threshold)

# 6. Quantize
quantize("model.pt", "neural-premise-selector.onnx")
# Max cosine distance: 0.008 (< 0.02 threshold)

# 7. Deploy: copy .onnx to well-known model path, re-index
```

### Fine-tuning workflow

```
# User extracts their project's proofs
# poule extract /path/to/my-project --output my-project.jsonl

dataset = load(["my-project.jsonl"], "index.db")
fine_tune("model.pt", dataset, "fine-tuned.pt", hyperparams={lr: 5e-6, epochs: 10})
# Adapts to project-specific definitions and proof patterns
```

## 8. Language-Specific Notes (Python)

- Use `torch` for model definition, training loop, and checkpoint management.
- Use `transformers` for the base encoder model (CodeBERT or equivalent) and tokenizer.
- Use `torch.cuda.amp` for mixed-precision training (FP16 forward pass, FP32 gradients).
- Use `torch.utils.data.DataLoader` with a custom `Dataset` for batching and shuffling.
- Use `onnx` and `onnxruntime.quantization` for ONNX export and dynamic INT8 quantization.
- Checkpoint format: `torch.save({"model_state_dict": ..., "optimizer_state_dict": ..., "epoch": ..., "best_recall_32": ..., "hyperparams": ...})`.
- Package location: `src/poule/neural/training/`.
