# Neural Training Pipeline

Training, evaluation, fine-tuning, and quantization pipeline for the neural premise selection model.

**Architecture**: [neural-training.md](../doc/architecture/neural-training.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the training pipeline that produces neural encoder model checkpoints from extracted Coq proof trace data: data loading and validation, bi-encoder training with masked contrastive loss, evaluation against retrieval quality thresholds, fine-tuning from pre-trained checkpoints, and INT8 quantization for CPU deployment.

## 2. Scope

**In scope**: `VocabularyBuilder` (closed-vocabulary construction from search index and training data), `CoqTokenizer` (whitespace-split tokenization using closed vocabulary), `TrainingDataLoader` (JSONL parsing, pair extraction, train/val/test split, hard negative sampling), `BiEncoderTrainer` (training loop, masked contrastive loss, checkpointing), `RetrievalEvaluator` (recall@k, MRR, neural vs. symbolic comparison), `ModelQuantizer` (PyTorch → INT8 ONNX conversion, validation), `TrainingDataValidator` (pre-training data quality checks), `HyperparameterTuner` (automated hyperparameter optimization using Optuna).

**Out of scope**: Neural encoder inference at query time (owned by neural-retrieval), embedding index construction (owned by neural-retrieval), retrieval pipeline integration (owned by pipeline), storage schema (owned by storage).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Closed vocabulary | A JSON dictionary mapping every token string to a unique integer ID, used for tokenization at training and inference time |
| Fixed token set | A predefined collection of tokens (special tokens, punctuation, Unicode symbols, Greek letters, digits) that are always included in the vocabulary regardless of input data |
| Training pair | A `(proof_state_text, premises_used_names)` tuple extracted from a proof trace step |
| Positive premise | A premise that appears in `premises_used` for a given proof state |
| Hard negative | A premise that is accessible to the theorem but not used in the proof step |
| Accessible premise | A premise whose source file is in the transitive file-dependency closure of the theorem's file |
| Masked contrastive loss | InfoNCE variant where shared positives (premises positive for other states in the batch) are excluded from the negative set |
| Epoch callback | An optional function `(epoch, val_recall) -> None` invoked after each epoch's validation, used by the tuner to report intermediate values and trigger pruning |
| Trial | A single hyperparameter optimization run with a sampled configuration |
| Pruning | Early termination of a trial whose intermediate validation metric falls below the median of previously completed trials at the same epoch |

## 4. Behavioral Requirements

### 4.0 VocabularyBuilder

#### build(index_db_path, jsonl_paths, output_path)

- REQUIRES: `index_db_path` points to a valid index database containing a `declarations` table. `jsonl_paths` is a non-empty list of paths to JSON Lines extraction output files. `output_path` is a writable path.
- ENSURES: Constructs a closed vocabulary from the search index and training data. Writes a JSON file to `output_path` mapping token strings to sequential integer IDs. Returns a `VocabularyReport`.

#### Fixed token sets

The following tokens are always included in the vocabulary at fixed positions, regardless of input data:

**Special tokens (IDs 0–4):**

| ID | Token |
|----|-------|
| 0 | `[PAD]` |
| 1 | `[UNK]` |
| 2 | `[CLS]` |
| 3 | `[SEP]` |
| 4 | `[MASK]` |

**Punctuation and delimiters:**
`(`, `)`, `{`, `}`, `[`, `]`, `:`, `;`, `,`, `.`, `|`, `@`, `!`, `?`, `_`, `'`, `#`, `=`, `+`, `-`, `*`, `/`, `<`, `>`, `~`

**SSReflect tacticals:**
`/=`, `//`, `//=`, `=>`, `->`, `<-`

**Scope delimiters:**
`%N`, `%Z`, `%R`, `%Q`, `%positive`, `%type`

**Unicode mathematical symbols:**
`∀`, `∃`, `→`, `←`, `↔`, `⊢`, `⊣`, `≤`, `≥`, `≠`, `≡`, `∧`, `∨`, `¬`, `⊆`, `⊇`, `∈`, `∉`, `⊂`, `⊃`, `∪`, `∩`, `∘`, `×`, `⊕`, `⊗`, `ℕ`, `ℤ`, `ℚ`, `ℝ`, `ℂ`

**Greek letters:**
`α`, `β`, `γ`, `δ`, `ε`, `ζ`, `η`, `θ`, `ι`, `κ`, `λ`, `μ`, `ν`, `ξ`, `π`, `ρ`, `σ`, `τ`, `υ`, `φ`, `χ`, `ψ`, `ω`, `Γ`, `Δ`, `Θ`, `Λ`, `Ξ`, `Π`, `Σ`, `Φ`, `Ψ`, `Ω`

**Digits:**
`0`, `1`, `2`, `3`, `4`, `5`, `6`, `7`, `8`, `9`

- MAINTAINS: Special tokens are always at IDs 0–4. The order of fixed token sets after the special tokens is: punctuation, SSReflect tacticals, scope delimiters, Unicode symbols, Greek letters, digits.

#### Token extraction from the search index

Read all rows from the `declarations` table. For each declaration, the `name` field (fully-qualified canonical form) is added as a vocabulary entry.

- MAINTAINS: Every declaration name in the index appears in the vocabulary exactly once.

> **Given** an index database with 15,000 declarations
> **When** `build` runs
> **Then** all 15,000 declaration names appear as vocabulary entries

#### Token extraction from training data

Scan each ExtractionRecord in the JSONL files. For each record, iterate over all steps. For each step, serialize the goals (same serialization as TrainingDataLoader) and split the serialized text on whitespace. Each unique token that is not already in the vocabulary is added.

This captures hypothesis variable names (`n`, `m`, `H`, `H0`, `x`, `y`, `IHn'`) and type expressions that appear in proof states.

- MAINTAINS: No duplicate tokens. If a token from the training data already exists in the vocabulary (from fixed sets or the index), it is not added again.

> **Given** training data containing proof states with hypothesis names `n`, `m`, `H`, `IHn'`
> **When** `build` scans the training data
> **Then** these names appear in the vocabulary (unless already present from the index)

#### Unicode normalization

All token strings shall have NFC (Canonical Decomposition followed by Canonical Composition) Unicode normalization applied before insertion into the vocabulary. This ensures that precomposed characters (e.g., `é` as U+00E9) and decomposed sequences (e.g., `e` + U+0301) are treated identically.

- MAINTAINS: All keys in the output JSON are NFC-normalized.

#### ID assignment

Token IDs are assigned sequentially starting from 0. The assignment order is:

1. Special tokens (IDs 0–4)
2. Fixed token sets (punctuation, tacticals, scope delimiters, Unicode, Greek, digits) — in the order listed above, within each set in the order listed
3. Declaration names from the index — sorted lexicographically
4. Tokens from training data not already in the vocabulary — sorted lexicographically

- MAINTAINS: IDs are contiguous (no gaps). Each token maps to exactly one ID. Each ID maps to exactly one token.

> **Given** 5 special tokens, 120 fixed tokens, 15,000 index declarations, and 300 training data tokens
> **When** IDs are assigned
> **Then** total vocabulary size is 15,425 and IDs range from 0 to 15,424

#### Output format

The vocabulary shall be written as a JSON object where keys are token strings and values are integer IDs. The JSON shall be pretty-printed with 2-space indentation for human readability.

```json
{
  "[PAD]": 0,
  "[UNK]": 1,
  "[CLS]": 2,
  "[SEP]": 3,
  "[MASK]": 4,
  "(": 5,
  ")": 6,
  ...
}
```

- MAINTAINS: The JSON file is valid UTF-8. All keys are unique. All values are unique non-negative integers.

#### VocabularyReport

`build` shall return a `VocabularyReport` with the following fields:

| Field | Type | Definition |
|-------|------|-----------|
| `total_tokens` | integer | Total number of tokens in the vocabulary |
| `special_tokens` | integer | Count of special tokens (always 5) |
| `fixed_tokens` | integer | Count of fixed token set entries (punctuation, symbols, etc.) |
| `index_tokens` | integer | Count of tokens from the search index declarations |
| `training_data_tokens` | integer | Count of tokens added from training data scanning |
| `output_path` | string | Path where the vocabulary was written |

> **Given** an index with 15,000 declarations and training data contributing 300 additional tokens
> **When** `build` completes
> **Then** VocabularyReport has total_tokens ≈ 15,425, index_tokens = 15,000, training_data_tokens = 300

### 4.0.1 CoqTokenizer

A lightweight tokenizer that performs whitespace splitting and dictionary lookup against the closed vocabulary. Replaces `AutoTokenizer.from_pretrained("microsoft/codebert-base")` throughout the pipeline.

#### __init__(vocabulary_path)

- REQUIRES: `vocabulary_path` points to a valid vocabulary JSON file (as produced by `VocabularyBuilder.build`).
- ENSURES: Loads the vocabulary mapping into memory. Sets `pad_token_id`, `unk_token_id`, `cls_token_id`, `sep_token_id`, `mask_token_id` from the vocabulary (IDs 0–4). Sets `vocab_size` to the number of entries.
- Raises `FileNotFoundError` if the path does not exist. Raises `DataFormatError` if the JSON is malformed.

#### encode(text, max_length=512)

- REQUIRES: `text` is a string.
- ENSURES: Returns a tuple `(input_ids, attention_mask)` where:
  1. `text` is NFC-normalized.
  2. Split on whitespace into tokens.
  3. Each token is looked up in the vocabulary dict → token ID (or `unk_token_id` for unknown tokens).
  4. `[CLS]` ID is prepended, `[SEP]` ID is appended.
  5. If length > `max_length`: truncate to `max_length` (keeping `[CLS]` at start, replacing last token with `[SEP]`).
  6. `attention_mask` is 1 for real tokens, 0 for padding.
  7. If length < `max_length`: pad with `pad_token_id` to `max_length`.
  8. Returns lists of integers (not tensors).

> **Given** text `"n : nat"` and vocabulary `{"[CLS]": 2, "[SEP]": 3, "[PAD]": 0, "n": 10, ":": 7, "nat": 8, "[UNK]": 1}`
> **When** `encode("n : nat", max_length=8)` is called
> **Then** `input_ids = [2, 10, 7, 8, 3, 0, 0, 0]` and `attention_mask = [1, 1, 1, 1, 1, 0, 0, 0]`

> **Given** an unknown token `"foobar"` not in the vocabulary
> **When** `encode("foobar")` is called
> **Then** `"foobar"` maps to `unk_token_id` (1)

#### encode_batch(texts, max_length=512)

- REQUIRES: `texts` is a non-empty list of strings.
- ENSURES: Encodes each text via `encode`, then pads all sequences to the length of the longest in the batch (up to `max_length`). Returns a dict `{"input_ids": tensor, "attention_mask": tensor}` with shape `(batch_size, padded_length)`.

- MAINTAINS: Padding is to the longest sequence in the batch, not to `max_length` (dynamic padding for efficiency).

> **Given** texts `["a b", "x"]` where `"a"`, `"b"`, `"x"` are in the vocabulary
> **When** `encode_batch(["a b", "x"], max_length=512)` is called
> **Then** `input_ids` has shape `(2, 4)` — both padded to length 4 (CLS + 2 tokens + SEP for the longer one)

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

#### train(dataset, output_path, vocabulary_path, hyperparams, epoch_callback)

- REQUIRES: `dataset` is a `TrainingDataset` with at least 1,000 training pairs (after sampling, if applied). `output_path` is a writable path. `vocabulary_path` points to a valid vocabulary JSON file (as produced by `VocabularyBuilder.build`). `hyperparams` has defaults as specified below. `sample` is `None` or a float in (0.0, 1.0]. `epoch_callback` is `None` or a callable `(epoch: int, val_recall: float) -> None`.
- ENSURES: When `sample` is not `None`, randomly sub-samples the training split to `ceil(len(dataset.train) * sample)` pairs before training begins (validation and test splits are not affected). Constructs a `CoqTokenizer` from `vocabulary_path`. Creates a `BiEncoder` model with an embedding layer sized to the vocabulary. Copies overlapping pretrained embeddings from CodeBERT for tokens that appear in both vocabularies (digits, punctuation, common words). Initializes remaining embeddings randomly (σ=0.02). Trains using masked contrastive loss. Saves the best checkpoint (by validation Recall@32) to `output_path`. The checkpoint includes the vocabulary path for reproducibility. Prints training metrics (loss, validation Recall@32) after each epoch. When `epoch_callback` is not `None`, invokes it after each epoch's validation with the epoch number and validation Recall@32; if the callback raises an exception, the training loop terminates and the exception propagates to the caller.
- On training completion: saves final checkpoint alongside best checkpoint.
- On GPU OOM: raises `TrainingResourceError` with message suggesting batch size reduction.
- When `vocabulary_path` is `None`: falls back to CodeBERT's default tokenizer and embedding layer (backward compatibility).

**Default hyperparameters:**

| Parameter | Default | Constraint |
|-----------|---------|-----------|
| `batch_size` | 128 | Must be positive |
| `learning_rate` | 5e-5 | Must be positive |
| `weight_decay` | 1e-2 | Must be non-negative |
| `temperature` | 0.05 | Must be positive |
| `hard_negatives_per_state` | 3 | Must be non-negative |
| `max_seq_length` | 256 | Must be positive |
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
- Model state dict (encoder weights, including the custom embedding layer when using closed vocabulary)
- Optimizer state dict
- Epoch number
- Best validation Recall@32
- Hyperparameters used
- `vocabulary_path` (string or None) — the path to the vocabulary JSON used during training

### 4.4 Fine-Tuning

#### fine_tune(checkpoint_path, dataset, output_path, hyperparams, epoch_callback)

- REQUIRES: `checkpoint_path` points to a valid training checkpoint. `dataset` contains project-specific training pairs. `output_path` is writable. `epoch_callback` is `None` or a callable `(epoch: int, val_recall: float) -> None`.
- ENSURES: Loads the pre-trained checkpoint, including the vocabulary path from the checkpoint. Resumes training with adjusted hyperparameters and the same tokenizer. Saves best fine-tuned checkpoint by validation Recall@32. When `epoch_callback` is not `None`, invokes it after each epoch's validation; if the callback raises an exception, the training loop terminates and the exception propagates.

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
- ENSURES: Reads `vocabulary_path` from the checkpoint. When present, reconstructs the model with the custom vocab size and uses `CoqTokenizer` for dummy input generation and validation. Exports the model to ONNX (opset 17+). Applies dynamic INT8 quantization. Validates quantization quality. Writes the INT8 ONNX model to `output_path`.

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

### 4.8 HyperparameterTuner

Automated hyperparameter optimization using Optuna to maximize validation Recall@32.

#### Tunable hyperparameters

| Parameter | Sampling type | Range | Default |
|-----------|--------------|-------|---------|
| `learning_rate` | Log-uniform | [1e-6, 1e-4] | 2e-5 |
| `temperature` | Log-uniform | [0.01, 0.2] | 0.05 |
| `batch_size` | Categorical | {64, 128, 256} | 256 |
| `weight_decay` | Log-uniform | [1e-4, 1e-1] | 1e-2 |
| `hard_negatives_per_state` | Integer | [1, 5] | 3 |

All other hyperparameters (`max_seq_length`, `embedding_dim`, `max_epochs`, `early_stopping_patience`) are fixed at their default values and not tunable.

#### tune(dataset, output_dir, vocabulary_path, n_trials, study_name, resume)

- REQUIRES: `dataset` is a `TrainingDataset` with at least 1,000 training pairs. `output_dir` is a writable directory path. `vocabulary_path` is `None` or points to a valid vocabulary JSON file. `n_trials` is a positive integer (default: 20). `study_name` is a non-empty string (default: `"poule-hpo"`). `resume` is a boolean (default: `False`).
- ENSURES: Creates an Optuna study with `TPESampler(seed=42)` and `MedianPruner(n_startup_trials=3, n_warmup_steps=3)`. Uses SQLite storage at `<output_dir>/hpo-study.db`. Runs `n_trials` trials sequentially. Each trial samples hyperparameters from the search space, creates a `BiEncoderTrainer`, and trains using the sampled configuration. Each trial's checkpoint is saved to `<output_dir>/trial-<N>.pt`. On study completion, copies the best trial's checkpoint to `<output_dir>/best-model.pt`. Returns a `TuningResult`.
- When `resume` is `True`: loads the existing study from `<output_dir>/hpo-study.db` and continues from the last completed trial.
- When a trial raises `TrainingResourceError` (OOM): logs the error and continues to the next trial.
- When all trials fail (zero complete successfully): raises `TuningError`.
- Between trials: calls `gc.collect()` and `torch.mps.empty_cache()` (when MPS is available) to release memory.

**Pruner configuration:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `n_startup_trials` | 3 | First 3 trials run to completion to establish a baseline distribution |
| `n_warmup_steps` | 3 | Epochs 1–3 are immune to pruning within each trial (early metrics are noisy) |

**Pruning integration with training loop:**

1. The objective function defines an `epoch_callback` that calls `trial.report(val_recall, epoch)` and then checks `trial.should_prune()`.
2. If `should_prune()` returns `True`, the callback raises `optuna.TrialPruned`.
3. `TrialPruned` propagates through `_train_impl()` (only `RuntimeError` for OOM is caught in the inner loop).
4. Optuna's study runner catches `TrialPruned` and records the trial as pruned.

> **Given** a study with n_trials=20 and a dataset of 10,000 pairs
> **When** `tune` completes
> **Then** the best checkpoint is at `<output_dir>/best-model.pt`, the study database is at `<output_dir>/hpo-study.db`, and `TuningResult` contains the best hyperparameters, best R@32, trial count, and prune count

> **Given** a previously interrupted study with 8 completed trials at `<output_dir>/hpo-study.db`
> **When** `tune` is called with `resume=True` and `n_trials=20`
> **Then** 12 additional trials are run (20 total)

> **Given** a study where all 5 trials raise `TrainingResourceError`
> **When** `tune` completes
> **Then** `TuningError` is raised with a message indicating zero trials completed

#### TuningResult

| Field | Type | Definition |
|-------|------|-----------|
| `best_hyperparams` | dict | Hyperparameter values from the best trial |
| `best_value` | float | Best validation Recall@32 across all completed trials |
| `n_trials` | integer | Total number of trials (completed + pruned + failed) |
| `n_pruned` | integer | Number of trials pruned by the MedianPruner |
| `study_path` | string | Path to the SQLite study database |
| `all_trials` | list of dict | Per-trial summary: `{"number": int, "value": float or None, "state": str, "hyperparams": dict}` |

> **Given** a study with 20 trials where 12 completed, 5 were pruned, and 3 failed
> **When** `TuningResult` is constructed
> **Then** `n_trials=20`, `n_pruned=5`, `best_value` is the max R@32 among the 12 completed trials, and `all_trials` has 20 entries

### 4.9 Device Detection

#### get_device()

- REQUIRES: Nothing.
- ENSURES: Returns a `torch.device` in priority order: CUDA (if `torch.cuda.is_available()`), MPS (if `torch.backends.mps.is_available()`), CPU (fallback).
- This is a module-level utility function used by `BiEncoderTrainer._train_impl()`, `RetrievalEvaluator`, and `HyperparameterTuner`.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| JSONL file not found | `FileNotFoundError` | Propagated to CLI |
| JSONL parse error (invalid JSON on a line) | `DataFormatError` | Line skipped, counted as malformed pair |
| Index database not found | `IndexNotFoundError` | Propagated to CLI |
| Index database has no declarations (vocabulary build) | `InsufficientDataError` | Propagated with message: `"No declarations found in index database"` |
| Checkpoint file not found | `CheckpointNotFoundError` | Propagated to CLI |
| GPU out of memory during training | `TrainingResourceError` | Propagated with batch size suggestion |
| Quantization validation failure (distance ≥ 0.02) | `QuantizationError` | Propagated with max distance value |
| Training dataset has < 1,000 pairs after filtering | `InsufficientDataError` | Propagated to CLI |
| Validation split is empty | `InsufficientDataError` | Propagated (split has 0 files in validation position) |
| Vocabulary JSON not found | `FileNotFoundError` | Propagated to CLI |
| Vocabulary JSON malformed | `DataFormatError` | Propagated with message: `"Invalid vocabulary file"` |
| All HPO trials fail (zero complete) | `TuningError` | Propagated with message: `"Hyperparameter optimization failed: 0 of {n} trials completed successfully"` |

Error hierarchy:
- `NeuralTrainingError` — base class for all training pipeline errors
  - `DataFormatError` — JSONL parse or schema error
  - `CheckpointNotFoundError` — model checkpoint missing
  - `TrainingResourceError` — GPU OOM or insufficient compute
  - `QuantizationError` — INT8 conversion quality check failed
  - `InsufficientDataError` — not enough training data
  - `TuningError` — hyperparameter optimization study failed (zero trials completed)

## 6. Non-Functional Requirements

| Metric | Target |
|--------|--------|
| Training time (50K pairs, 24GB GPU) | < 8 hours |
| Training time (10K pairs, 24GB GPU) | < 2 hours |
| Fine-tuning time (2K pairs, 24GB GPU) | < 4 hours |
| Validation pass (per epoch) | < 60 seconds |
| Vocabulary build (15K declarations + 100K steps) | < 60 seconds |
| Data validation (single pass, 100K steps) | < 30 seconds |
| Quantization (export + validate) | < 5 minutes |
| Peak GPU memory (batch_size=256, seq_len=512) | ≤ 24GB |
| Training time (10K pairs, M2 Pro MPS) | < 7 hours |
| HPO (20 trials, 10K pairs, M2 Pro MPS) | < 5 hours (with pruning) |
| HPO (20 trials, 10K pairs, 24GB GPU) | < 2 hours (with pruning) |

## 7. Examples

### Full training workflow

```
# 0. Build vocabulary
vocab_report = build("index.db", ["stdlib.jsonl", "mathcomp.jsonl"], "coq-vocabulary.json")
# vocab_report.total_tokens = 15,425

# 1. Validate data
report = validate(["stdlib.jsonl", "mathcomp.jsonl"])
# report.total_pairs = 45,000, no warnings

# 2. Load data
dataset = load(["stdlib.jsonl", "mathcomp.jsonl"], "index.db")
# dataset.train: 36,000 pairs, dataset.val: 4,500 pairs, dataset.test: 4,500 pairs

# 3. Train (with closed vocabulary)
train(dataset, "model.pt", vocabulary_path="coq-vocabulary.json",
      hyperparams={batch_size: 256, lr: 2e-5, epochs: 20})
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

### Hyperparameter optimization workflow

```
# 1. Load data (same as training)
dataset = load(["stdlib.jsonl", "mathcomp.jsonl"], "index.db")

# 2. Run HPO
result = tune(dataset, "hpo-output/", vocabulary_path="coq-vocabulary.json", n_trials=20)
# Trial 0: lr=3.2e-5, τ=0.042, batch=128, wd=5.1e-3, neg=3 → R@32=0.51
# Trial 1: lr=8.7e-6, τ=0.11, batch=256, wd=2.3e-2, neg=2 → R@32=0.44
# Trial 2: lr=1.2e-4, τ=0.015, batch=64, wd=8.9e-4, neg=4 → pruned at epoch 5
# ...
# Trial 19: lr=2.8e-5, τ=0.038, batch=128, wd=7.2e-3, neg=3 → R@32=0.56
#
# result.best_value = 0.56, result.n_pruned = 7
# Best checkpoint: hpo-output/best-model.pt

# 3. Resume an interrupted study
result = tune(dataset, "hpo-output/", vocabulary_path="coq-vocabulary.json",
              n_trials=30, resume=True)
# Continues from trial 20 (10 more trials)
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
- Use `optuna` for hyperparameter optimization. Import lazily — only required when `tune()` is called.
- Package location: `src/poule/neural/training/`.
