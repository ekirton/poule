# Neural Training Pipeline

Training, evaluation, fine-tuning, and quantization pipeline for the neural tactic prediction model.

**Architecture**: [neural-training.md](../doc/architecture/neural-training.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the training pipeline that produces a tactic family classifier from extracted Coq proof trace data: data loading and validation, class-weighted cross-entropy training, evaluation against classification accuracy thresholds, fine-tuning from pre-trained checkpoints, and INT8 quantization for CPU deployment.

## 2. Scope

**In scope**: `VocabularyBuilder` (closed-vocabulary construction from search index and training data), `CoqTokenizer` (whitespace-split tokenization using closed vocabulary), `TrainingDataLoader` (JSONL parsing, tactic family extraction, label map construction, train/val/test split), `TacticClassifierTrainer` (training loop, class-weighted cross-entropy loss, checkpointing), `TacticEvaluator` (accuracy@k, per-family precision/recall, confusion matrix), `ModelQuantizer` (PyTorch → INT8 ONNX conversion, validation, label export), `TrainingDataValidator` (pre-training data quality checks), `HyperparameterTuner` (automated hyperparameter optimization using Optuna), `MLXTacticClassifier` (MLX port of the classifier model), `MLXTrainer` (MLX training loop with functional gradients), `WeightConverter` (MLX safetensors → PyTorch checkpoint conversion).

**Out of scope**: Tactic prediction inference at query time (owned by neural-retrieval), retrieval pipeline integration (owned by pipeline), storage schema (owned by storage).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Closed vocabulary | A JSON dictionary mapping every token string to a unique integer ID, used for tokenization at training and inference time |
| Fixed token set | A predefined collection of tokens (special tokens, punctuation, Unicode symbols, Greek letters, digits) that are always included in the vocabulary regardless of input data |
| Tactic family | The normalized first token of a tactic command (e.g., `apply`, `rewrite`, `simpl`), used as the classification target |
| Label map | A dictionary mapping tactic family names to contiguous integer class indices |
| Class weight | Inverse-frequency weight for a tactic family, used to counteract long-tailed distribution during training |
| Epoch callback | An optional function `(epoch, val_accuracy) -> None` invoked after each epoch's validation, used by the tuner to report intermediate values and trigger pruning |
| Trial | A single hyperparameter optimization run with a sampled configuration |
| Pruning | Early termination of a trial whose intermediate validation metric falls below the median of previously completed trials at the same epoch |
| MLX | Apple's array framework for Apple Silicon, using lazy evaluation and unified memory |
| Safetensors | Serialization format for ML model weights used by MLX checkpoints |
| Weight conversion | Process of transforming MLX model parameters to PyTorch format: parameter name mapping + array format conversion |

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

Scan the compact training data JSONL files. For each `"s"` and `"g"` record, read the `"s"` field and split on whitespace. Each unique token that is not already in the vocabulary is added.

This captures hypothesis variable names (`n`, `m`, `H`, `H0`, `x`, `y`, `IHn'`) and type expressions that appear in proof states.

- MAINTAINS: No duplicate tokens. If a token from the training data already exists in the vocabulary (from fixed sets or the index), it is not added again.

> **Given** training data containing proof states with hypothesis names `n`, `m`, `H`, `IHn'`
> **When** `build` scans the training data
> **Then** these names appear in the vocabulary (unless already present from the index)

#### _extract_tokens_from_jsonl (internal)

For each line in a JSONL file, parse the JSON record and check `record.get("t") in ("s", "g")`. If the record matches, read the `"s"` field and split on whitespace to collect tokens.

- MAINTAINS: Only `"s"` (step) and `"g"` (goal) records contribute tokens. Other record types are ignored.

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

### 4.0.5 Compact Training Data Format

Training data files use a compact JSONL format with two record types. Each line is a JSON object with a `"t"` key discriminating the type:

**Step record** (`"t": "s"`): A training step with source file, serialized proof state, and tactic command text.
```json
{"t":"s","f":"Arith/Plus.v","s":"n : nat\nm : nat\nn + S m = S (n + m)","c":"simpl"}
```

| Field | Type | Description |
|-------|------|-------------|
| `t` | `"s"` | Record type discriminator |
| `f` | string | Source file path (for file-level splitting) |
| `s` | string | Serialized proof state (output of `serialize_goals`) |
| `c` | string | Tactic command text |

**Goal-state record** (`"t": "g"`): A supplementary serialized proof state for vocabulary building. These exist so that the vocabulary builder can scan all proof state goals, including goals from steps that may be filtered during training.
```json
{"t":"g","s":"forall n : nat, n + 0 = n"}
```

| Field | Type | Description |
|-------|------|-------------|
| `t` | `"g"` | Record type discriminator |
| `s` | string | Serialized proof state |

Records with `"record_type"` (e.g., `campaign_metadata`, `extraction_summary`, `extraction_error`) are passed through unchanged for provenance.

### 4.0.6 TacticCollapser

Post-extraction preprocessing that merges per-library JSONL files into a single training file with normalized tactic families, addressing class imbalance caused by compound tactic parsing artifacts.

#### collapse(input_paths, output_path, min_count, dry_run)

- REQUIRES: `input_paths` is a non-empty list of paths to compact training data JSONL files. `output_path` is a writable file path. `min_count` is a positive integer (default: 50). `dry_run` is a boolean (default: false).
- ENSURES: Reads all `"s"` records from input files, normalizes each record's tactic family via `normalize_tactic_family`, counts family occurrences across the full corpus, maps families below `min_count` to `"other"`, and writes all step records to `output_path` with the `"c"` field replaced by the final normalized family name. Returns a `CollapseReport`.
- ENSURES: If `dry_run` is true, computes and returns the `CollapseReport` without writing the output file.
- ENSURES: Input files are not modified.

#### normalize_tactic_family(tactic_text)

Extends `extract_tactic_family` with additional normalization rules for compound tactic fragments:

1. Strip leading and trailing whitespace.
2. Handle SSReflect: if the text starts with `by ` (followed by space), strip the `by ` prefix.
3. Strip leading parentheses: `(apply` → `apply`, `(do` → `do`.
4. Strip goal selector prefixes: `1:lia` → `lia`, `2:reflexivity` → `reflexivity`. Pattern: `^\d+:`.
5. Split on `;` and take the first segment (compound tactic handling).
6. Take the first whitespace-delimited token.
7. Strip trailing punctuation (`.`, `;`, `:`, `?`, `-`).
8. Strip SSReflect intro pattern operator: if the token ends with `=>`, remove it. This collapses `move=>` → `move`, `case=>` → `case`, etc.
9. Lowercase.
10. Apply alias mapping (same as `extract_tactic_family`: `intro` → `intros`, `Proof` → `intros`, `now` → `auto`).

- REQUIRES: `tactic_text` is a string (may be empty).
- ENSURES: Returns a lowercase string representing the normalized tactic family, or `"other"` if the input is empty or produces an empty result after normalization.

> **Given** tactic text `"destruct(q_dec foo bar)"`
> **When** `normalize_tactic_family` runs
> **Then** returns `"destruct"` (parenthesized suffix is part of argument, first token after stripping is `destruct(q_dec`, leading paren stripped → `destruct`)

Wait — the first token of `"destruct(q_dec foo bar)"` is `"destruct(q_dec"`. After stripping trailing non-alpha: `"destruct(q_dec"`. We need to handle embedded parens. Revised rule: after extracting the first token, strip everything from the first `(` onward.

Revised step 6a: After extracting the first whitespace-delimited token, truncate at the first `(` character if present.

> **Given** tactic text `"destruct(q_dec foo bar)."`
> **When** `normalize_tactic_family` runs
> **Then** returns `"destruct"` (first token `destruct(q_dec` truncated at `(`)

> **Given** tactic text `"1:lia."`
> **When** `normalize_tactic_family` runs
> **Then** returns `"lia"` (goal selector `1:` stripped, trailing `.` stripped)

> **Given** tactic text `"(apply H)."`
> **When** `normalize_tactic_family` runs
> **Then** returns `"apply"` (leading `(` stripped)

> **Given** tactic text `"clear- x y"`
> **When** `normalize_tactic_family` runs
> **Then** returns `"clear"` (trailing `-` stripped)

#### CollapseReport

| Field | Type | Description |
|-------|------|-------------|
| `total_records` | int | Total `"s"` records read from all input files |
| `input_files` | int | Number of input files processed |
| `families_before` | int | Distinct family count before min-count thresholding |
| `families_after` | int | Distinct family count after thresholding (including "other") |
| `collapsed_to_other` | int | Number of families merged into "other" |
| `family_distribution` | list of (str, int) | Final family distribution sorted by count descending |
| `output_path` | str or None | Path to written output file, or None if dry_run |

### 4.1 TrainingDataLoader

#### load(jsonl_paths)

- REQUIRES: `jsonl_paths` is a non-empty list of paths to compact training data JSONL files (as produced by the extraction pipeline).
- ENSURES: Returns a `TacticDataset` containing all valid `(proof_state_text, tactic_family_index)` pairs from `"s"` records, the label map, and train/validation/test splits.

#### Step extraction and tactic family labeling

Each `"s"` record in the compact JSONL contains a proof step:

```
For each line in the JSONL files:
    record = json.loads(line)
    If record["t"] == "s":
        family = extract_tactic_family(record["c"])
        If family is not None:
            Emit (record["s"], family) grouped by record["f"]
```

Steps with missing or empty `"c"` fields shall be skipped.

> **Given** a JSONL file with 10,000 `"s"` records, each with a non-empty `"c"` field
> **When** steps are extracted
> **Then** up to 10,000 `(proof_state, tactic_family)` pairs are emitted (some may be filtered to `other` or skipped)

#### extract_tactic_family(tactic_text)

Extracts the normalized tactic family name from raw tactic command text:

1. Strip leading and trailing whitespace.
2. Handle SSReflect: if the text starts with `by ` (followed by space), strip the `by ` prefix.
3. Take the first whitespace-delimited token.
4. Normalize: lowercase, strip trailing punctuation (`.`, `;`).
5. Apply alias mapping (e.g., `intro` → `intros`, `destruct` → `case` where applicable).
6. Return the normalized family name.

- REQUIRES: `tactic_text` is a non-empty string.
- ENSURES: Returns a lowercase string representing the tactic family.

> **Given** tactic text `"apply Nat.add_comm."`
> **When** `extract_tactic_family` runs
> **Then** returns `"apply"`

> **Given** tactic text `"by rewrite IHn."`
> **When** `extract_tactic_family` runs
> **Then** returns `"rewrite"` (SSReflect `by` prefix stripped)

> **Given** tactic text `"  intros n m. "`
> **When** `extract_tactic_family` runs
> **Then** returns `"intros"` (whitespace stripped, trailing punctuation removed)

#### Label map construction

After all steps are extracted, build a `label_map: dict[str, int]` mapping tactic family names to contiguous integer class indices:

1. Count occurrences of each tactic family across all extracted steps.
2. Families appearing fewer than `min_family_count` times (default: 50) are mapped to the family `"other"`.
3. Assign class indices 0, 1, 2, ... to families sorted lexicographically. The `"other"` family is always included.

- MAINTAINS: The label map has contiguous integer values starting from 0. Every tactic family in the dataset maps to exactly one class index.
- MAINTAINS: Target is approximately 30 families covering >95% of proof steps.

> **Given** extracted steps with families: `apply` (5000), `rewrite` (3000), `simpl` (2000), `intros` (4000), `rare_tactic` (10)
> **When** label map is built with `min_family_count=50`
> **Then** `rare_tactic` is mapped to `"other"`, and label_map contains `{"apply": 0, "intros": 1, "other": 2, "rewrite": 3, "simpl": 4}` (lexicographic order)

#### TacticDataset

A dataset holding `(state_text, label_index)` pairs with train/validation/test splits:

| Field | Type | Description |
|-------|------|-------------|
| `train` | list of (str, int) | Training pairs: (proof_state_text, tactic_family_index) |
| `val` | list of (str, int) | Validation pairs |
| `test` | list of (str, int) | Test pairs |
| `label_map` | dict[str, int] | Tactic family name → class index |
| `num_classes` | int | Number of distinct tactic families (including `"other"`) |

#### Train/validation/test split

Files shall be split deterministically by fully qualified source file path:

1. Sort all unique source file paths lexicographically
2. Assign files at positions where `position % 10 == 8` to validation
3. Assign files at positions where `position % 10 == 9` to test
4. Assign all remaining files to training

All steps from the same file go into the same split.

- MAINTAINS: No step from the same source file appears in more than one split.

> **Given** 100 source files sorted lexicographically
> **When** the split is computed
> **Then** files at indices 8, 18, 28, ... → validation; indices 9, 19, 29, ... → test; all others → train

#### Split diagnostic report

`SplitReport.generate(dataset: TacticDataset) -> SplitReport`

- REQUIRES: `dataset` is a populated `TacticDataset`.
- ENSURES: Returns a `SplitReport` with per-split file/step counts, tactic family distributions, and diagnostic warnings. All division-by-zero cases (empty splits) yield `0.0`.

**SplitReport fields:**

| Field | Type | Description |
|-------|------|-------------|
| `train_files` | int | Unique source files in train split |
| `val_files` | int | Unique source files in validation split |
| `test_files` | int | Unique source files in test split |
| `train_steps` | int | Total steps in train split |
| `val_steps` | int | Total steps in validation split |
| `test_steps` | int | Total steps in test split |
| `train_mean_steps_per_file` | float | Mean steps per file in train |
| `train_median_steps_per_file` | float | Median steps per file in train |
| `val_mean_steps_per_file` | float | Mean steps per file in validation |
| `val_median_steps_per_file` | float | Median steps per file in validation |
| `test_mean_steps_per_file` | float | Mean steps per file in test |
| `test_median_steps_per_file` | float | Median steps per file in test |
| `num_classes` | int | Number of tactic families (including `"other"`) |
| `train_family_distribution` | dict[str, int] | Per-family step counts in train |
| `val_family_distribution` | dict[str, int] | Per-family step counts in validation |
| `test_family_distribution` | dict[str, int] | Per-family step counts in test |
| `train_top_families` | list of (name, count) | 10 most frequent families in train |
| `val_top_families` | list of (name, count) | 10 most frequent families in validation |
| `test_top_families` | list of (name, count) | 10 most frequent families in test |
| `warnings` | list of string | Diagnostic warnings (see conditions below) |

**Warning conditions:**

| Condition | Warning message |
|-----------|----------------|
| Any family has > 30% of train steps | `"Tactic family '{name}' accounts for {pct}% of training steps — model may be biased toward this family"` |
| Any family (excluding `"other"`) has < 100 train steps | `"Tactic family '{name}' has only {n} training steps — may be under-represented"` |
| `num_classes < 5` | `"Only {n} tactic families — classification may be too coarse"` |
| `test_steps < 100` | `"Test split has fewer than 100 steps — metrics will be noisy"` |
| `val_steps < 100` | `"Validation split has fewer than 100 steps — metrics will be noisy"` |

**JSON serialization**: `to_dict()` returns a JSON-serializable dictionary. Tuple lists are converted to lists of `[name, count]` pairs.

> **Given** a dataset with 10 source files, each with 100 steps
> **When** `SplitReport.generate` runs
> **Then** `train_files` = 8, `val_files` = 1, `test_files` = 1, `train_steps` = 800, `val_steps` = 100, `test_steps` = 100

> **Given** a dataset where `intros` accounts for 40% of training steps
> **When** `SplitReport.generate` runs
> **Then** warnings includes "Tactic family 'intros' accounts for 40% of training steps — model may be biased toward this family"

### 4.3 TacticClassifierTrainer

#### train(dataset, output_path, vocabulary_path, hyperparams, epoch_callback)

- REQUIRES: `dataset` is a `TacticDataset` with at least 1,000 training steps (after sampling, if applied). `output_path` is a writable path. `vocabulary_path` points to a valid vocabulary JSON file (as produced by `VocabularyBuilder.build`). `hyperparams` has defaults as specified below. `sample` is `None` or a float in (0.0, 1.0]. `epoch_callback` is `None` or a callable `(epoch: int, val_accuracy: float) -> None`.
- ENSURES: When `sample` is not `None`, randomly sub-samples the training split to `ceil(len(dataset.train) * sample)` steps before training begins (validation and test splits are not affected). Constructs a `CoqTokenizer` from `vocabulary_path`. Creates a `TacticClassifier` model with `num_hidden_layers` transformer layers (default 6, layer-dropped from CodeBERT's 12 layers), an embedding layer sized to the vocabulary, and a classification head sized to `dataset.num_classes`. Copies overlapping pretrained embeddings from CodeBERT for tokens that appear in both vocabularies (digits, punctuation, common words). Initializes remaining embeddings randomly (σ=0.02). Trains using class-weighted cross-entropy loss. Saves the best checkpoint (by validation accuracy@5) to `output_path`. The checkpoint includes `num_hidden_layers`, the vocabulary path, and label map for reproducibility. Prints training metrics (loss, validation accuracy@1, validation accuracy@5) after each epoch. When `epoch_callback` is not `None`, invokes it after each epoch's validation with the epoch number and validation accuracy@5; if the callback raises an exception, the training loop terminates and the exception propagates to the caller.
- On training completion: saves final checkpoint alongside best checkpoint.
- On GPU OOM: raises `TrainingResourceError` with message suggesting batch size reduction.
- When `vocabulary_path` is `None`: falls back to CodeBERT's default tokenizer and embedding layer (backward compatibility).

**Default hyperparameters:**

| Parameter | Default | Constraint |
|-----------|---------|-----------|
| `num_hidden_layers` | 6 | Must be in {4, 6, 8, 12} |
| `batch_size` | 16 | Must be positive |
| `learning_rate` | 2e-5 | Must be positive |
| `weight_decay` | 1e-2 | Must be non-negative |
| `class_weight_alpha` | 0.5 | Must be in [0.0, 1.0] |
| `label_smoothing` | 0.1 | Must be in [0.0, 1.0) |
| `sam_rho` | 0.05 | Must be positive. When 0.0, SAM is disabled (plain AdamW). |
| `max_seq_length` | 512 | Must be positive |
| `max_epochs` | 20 | Must be positive |
| `early_stopping_patience` | 3 | Must be positive |
| `embedding_dim` | 768 | Fixed — not configurable |

#### Model architecture: TacticClassifier

```
Input: input_ids [B, 512], attention_mask [B, 512]
  |
  |-- CodeBERT encoder (num_hidden_layers layers, 768 hidden, 12 heads)
  |-- Mean pooling (attention-masked)
  |-- nn.Linear(768, num_classes)
  |-- Output: logits [B, num_classes]
```

Default `num_hidden_layers` is 6. Single forward pass per batch. No premise encoding, no contrastive pairs, no hard negatives.

#### Construction

`TacticClassifier(model_name, num_classes, vocab_size, num_hidden_layers=6)`

- REQUIRES: `model_name` is a valid HuggingFace model name (default: `"microsoft/codebert-base"`). `num_classes` is a positive integer. `vocab_size` is `None` or a positive integer. `num_hidden_layers` is in {4, 6, 8, 12}.
- ENSURES: Loads the pretrained model, then applies layer dropping if `num_hidden_layers` < 12. Layer dropping selects `num_hidden_layers` layers at evenly spaced indices from the 12-layer source: `indices = [i * 12 // num_hidden_layers for i in range(num_hidden_layers)]`. Builds a new encoder with only the selected layers. Updates the model config's `num_hidden_layers`. When `vocab_size` is not `None`, replaces the embedding layer (same procedure as before). Creates the classification head `nn.Linear(768, num_classes)`.
- When `num_hidden_layers` is 12: no layer dropping; loads all pretrained layers (backward compatible).

> **Given** `num_hidden_layers=6`
> **When** `TacticClassifier` is constructed
> **Then** layer indices [0, 2, 4, 6, 8, 10] are selected from CodeBERT's 12 layers

> **Given** `num_hidden_layers=4`
> **When** `TacticClassifier` is constructed
> **Then** layer indices [0, 3, 6, 9] are selected from CodeBERT's 12 layers

#### from_checkpoint(checkpoint)

- REQUIRES: `checkpoint` is a dict containing `model_state_dict`, `num_classes`, and optionally `num_hidden_layers`.
- ENSURES: Reads `num_hidden_layers` from the checkpoint (default 12 for backward compatibility with existing checkpoints). Builds a `RobertaModel` with the specified layer count. Loads weights with `strict=False`.

> **Given** a checkpoint saved with `num_hidden_layers=6`
> **When** `from_checkpoint` reconstructs the model
> **Then** the encoder has 6 transformer layers

> **Given** a checkpoint saved before layer dropping was introduced (no `num_hidden_layers` key)
> **When** `from_checkpoint` reconstructs the model
> **Then** the encoder has 12 transformer layers (backward compatible)

#### forward(input_ids, attention_mask)

- REQUIRES: `input_ids` is a tensor of shape `[B, seq_len]`. `attention_mask` is a tensor of shape `[B, seq_len]` with values 0 or 1.
- ENSURES: Returns logits of shape `[B, num_classes]`.
  1. Token embeddings: `embedding(input_ids)` → `[B, seq_len, 768]`
  2. Transformer encoding (`num_hidden_layers` layers)
  3. Mean pooling: `sum(output * mask.unsqueeze(-1)) / sum(mask).unsqueeze(-1)` per sequence
  4. Linear projection: `nn.Linear(768, num_classes)` → `[B, num_classes]`

#### Class-weighted cross-entropy loss with label smoothing

```
loss = CrossEntropyLoss(weight=class_weights, label_smoothing=label_smoothing)(logits, labels)
```

Class weights are computed from inverse frequency:

```
weight[c] = (total_samples / (num_classes * count[c])) ^ alpha
```

where `alpha` is `class_weight_alpha` (default 0.5). When `alpha=0`, all weights are 1.0 (no rebalancing). When `alpha=1`, weights are fully inverse-frequency.

Label smoothing parameter `label_smoothing` (default 0.1) replaces hard targets with soft targets: y = 1 - ε + ε/K for the correct class, y = ε/K for incorrect classes, where K is the number of classes. When `label_smoothing=0.0`, standard hard targets are used (backward compatible).

- MAINTAINS: Class weights are computed once from the training split before training begins and remain fixed throughout training.
- MAINTAINS: Label smoothing is applied via PyTorch's built-in `CrossEntropyLoss(label_smoothing=...)` parameter. No custom loss function is needed.

> **Given** a training set with 3 families: `apply` (5000), `intros` (4000), `simpl` (1000), alpha=0.5
> **When** class weights are computed (total=10000, num_classes=3)
> **Then** weight[apply] = (10000 / (3 * 5000))^0.5 ≈ 0.816, weight[simpl] = (10000 / (3 * 1000))^0.5 ≈ 1.826

> **Given** `label_smoothing=0.1` and `num_classes=30`
> **When** cross-entropy loss is constructed
> **Then** `CrossEntropyLoss(weight=class_weights, label_smoothing=0.1)` is used

#### Optimizer: SAM-AdamW

- REQUIRES: `sam_rho` is a non-negative float. When `sam_rho > 0`, SAM wraps AdamW.
- ENSURES: When `sam_rho > 0`, each training step performs two forward-backward passes: (1) compute gradient at current parameters, perturb parameters by `rho * grad / ||grad||`, (2) compute gradient at perturbed parameters, apply AdamW step using this second gradient, restore original parameters. When `sam_rho == 0.0`, uses plain AdamW (no perturbation step).
- MAINTAINS: SAM doubles the compute cost per batch. The perturbation is applied to all model parameters.

> **Given** `sam_rho=0.05`
> **When** a training step executes
> **Then** the optimizer performs two forward-backward passes per batch

> **Given** `sam_rho=0.0`
> **When** a training step executes
> **Then** the optimizer uses plain AdamW (single forward-backward pass)

#### Embedding layer integration

The closed vocabulary replaces CodeBERT's 50,265-token vocabulary with ~150K tokens. The TacticClassifier model reinitializes its embedding layer:

1. Load CodeBERT and apply layer dropping (selecting `num_hidden_layers` layers from the 12-layer source).
2. Create `nn.Embedding(vocab_size, 768)`.
3. Copy pretrained embeddings for overlapping tokens (digits, punctuation, common words).
4. Initialize Coq-specific tokens randomly (sigma=0.02).

#### Early stopping

After each epoch, compute accuracy@5 on the validation split. If validation accuracy@5 does not improve for `early_stopping_patience` consecutive epochs, stop training and retain the best checkpoint.

> **Given** patience=3 and validation accuracy@5 does not improve for epochs 8, 9, 10
> **When** epoch 10 completes
> **Then** training stops and the checkpoint from epoch 7 (last improvement) is retained as the best model

#### Checkpoint format

The checkpoint shall include:
- Model state dict (encoder weights, classification head, including the custom embedding layer when using closed vocabulary)
- `num_classes` (int) — number of tactic family classes
- `num_hidden_layers` (int) — number of transformer layers in the encoder (4, 6, 8, or 12)
- Optimizer state dict
- Epoch number
- Best validation accuracy@5
- Hyperparameters used
- `vocabulary_path` (string or None) — the path to the vocabulary JSON used during training
- `label_map` (dict) — mapping of tactic family names to class indices

### 4.4 Fine-Tuning

#### fine_tune(checkpoint_path, dataset, output_path, hyperparams, epoch_callback)

- REQUIRES: `checkpoint_path` points to a valid training checkpoint. `dataset` contains project-specific training steps. `output_path` is writable. `epoch_callback` is `None` or a callable `(epoch: int, val_accuracy: float) -> None`.
- ENSURES: Loads the pre-trained checkpoint, including the vocabulary path and label map from the checkpoint. Resumes training with adjusted hyperparameters and the same tokenizer. If the project dataset introduces tactic families not in the checkpoint's label map, they are added (extending the classification head). Saves best fine-tuned checkpoint by validation accuracy@5. When `epoch_callback` is not `None`, invokes it after each epoch's validation; if the callback raises an exception, the training loop terminates and the exception propagates.

**Fine-tuning hyperparameter overrides:**

| Parameter | Override | Rationale |
|-----------|----------|-----------|
| `learning_rate` | 5e-6 (default) | Lower LR to avoid catastrophic forgetting |
| `max_epochs` | 10 (default) | Smaller dataset converges faster |

All other hyperparameters default to the same values as `train`.

> **Given** a pre-trained checkpoint and 2,000 project-specific training steps
> **When** `fine_tune` runs on a consumer GPU (≤ 24GB VRAM)
> **Then** fine-tuning completes in under 4 hours

### 4.5 TacticEvaluator

#### evaluate(checkpoint_path, test_data)

- REQUIRES: `checkpoint_path` points to a valid model checkpoint (containing `label_map` and `vocabulary_path`). `test_data` is a list of `(proof_state_text, tactic_family_index)` pairs.
- ENSURES: Loads the model. For each test state, encodes it, computes logits, and evaluates classification metrics. Returns an `EvaluationReport`.

**EvaluationReport fields:**

| Field | Type | Definition |
|-------|------|-----------|
| `accuracy_at_1` | float | Fraction of test steps where top-1 prediction matches ground truth |
| `accuracy_at_5` | float | Fraction of test steps where correct family is in top-5 predictions |
| `per_family_precision` | dict[str, float] | For each tactic family, fraction of predictions for that family that are correct |
| `per_family_recall` | dict[str, float] | For each tactic family, fraction of true instances correctly predicted |
| `confusion_matrix` | list[list[int]] | `num_classes x num_classes` matrix of prediction counts; row = true, column = predicted |
| `test_count` | integer | Number of test steps evaluated |
| `num_classes` | integer | Number of tactic families |
| `label_names` | list[str] | Ordered list of tactic family names (index corresponds to class index) |

**Deployment thresholds** (advisory):
- Accuracy@1 >= 40%
- Accuracy@5 >= 80%

When `accuracy_at_1 < 0.40`, the report shall include a warning: `"Model does not meet deployment threshold (accuracy@1 < 40%)"`.
When `accuracy_at_5 < 0.80`, the report shall include a warning: `"Model does not meet deployment threshold (accuracy@5 < 80%)"`.

> **Given** a test set of 1,000 steps across 25 tactic families
> **When** `evaluate` completes
> **Then** returns an EvaluationReport with all metrics computed, confusion_matrix of shape 25x25

> **Given** a model where `apply` is predicted correctly 80% of the time but `omega` only 20%
> **When** `evaluate` computes per-family metrics
> **Then** per_family_recall["apply"] ≈ 0.80, per_family_recall["omega"] ≈ 0.20

### 4.6 ModelQuantizer

#### quantize(checkpoint_path, output_path)

- REQUIRES: `checkpoint_path` points to a valid PyTorch training checkpoint (containing `label_map`, `vocabulary_path`, and optionally `num_hidden_layers`). `output_path` is a writable path.
- ENSURES: Reads `vocabulary_path`, `label_map`, and `num_hidden_layers` (default 12 for backward compatibility) from the checkpoint. Reconstructs the model with the custom vocab size, `num_classes` from the label map, and the correct layer count. Exports the model to ONNX (opset 17+). Output shape: `[B, num_classes]`. Applies dynamic INT8 quantization. Validates quantization quality. Writes the INT8 ONNX model to `output_path`. Also writes `tactic-labels.json` alongside the ONNX model.

**ONNX export:**
- Input names: `input_ids` (shape `[B, seq_len]`), `attention_mask` (shape `[B, seq_len]`)
- Output name: `logits` (shape `[B, num_classes]`)
- Dynamic axes on batch dimension and sequence length

**tactic-labels.json:**
An ordered JSON list of tactic family names where the list index corresponds to the class index. Written to the same directory as `output_path`.

```json
["apply", "auto", "case", "intros", "omega", "other", "rewrite", "simpl", ...]
```

**Validation step:**
1. Generate 100 random input texts (from test set or synthetic).
2. Run each through both full-precision PyTorch and quantized ONNX models.
3. Compare predicted labels (argmax of logits) between the two models.
4. If predicted labels disagree on > 2% of inputs (i.e., match on < 98%): raise `QuantizationError` with the agreement percentage.

> **Given** a trained model checkpoint with 30 tactic families
> **When** `quantize` runs
> **Then** produces an INT8 ONNX file at `output_path` with output shape [B, 30], predicted labels match on >= 98% of validation inputs, and `tactic-labels.json` is written alongside

### 4.7 TrainingDataValidator

#### validate(jsonl_paths)

- REQUIRES: `jsonl_paths` is a non-empty list of paths to JSON Lines extraction output files.
- ENSURES: Scans all files in a single pass. Returns a `ValidationReport`.

**ValidationReport fields:**

| Field | Type | Definition |
|-------|------|-----------|
| `total_steps` | integer | Total `"s"` records with non-empty tactic text |
| `missing_tactic_steps` | integer | `"s"` records with missing or empty `"c"` field |
| `malformed_records` | integer | Lines with missing or invalid JSON or missing required fields |
| `unique_families` | integer | Distinct tactic families extracted |
| `family_distribution` | dict[str, int] | Per-family step counts |
| `top_families` | list of (name, count) | 10 most frequently occurring tactic families |
| `warnings` | list of string | Human-readable warning messages |

**Warning conditions:**

| Condition | Warning message |
|-----------|----------------|
| `missing_tactic_steps > 0` | `"Found {n} step records with missing tactic text"` |
| `malformed_records > 0` | `"Found {n} malformed records — check extraction output format"` |
| `total_steps < 10000` | `"Only {n} training steps — model quality may be limited"` |
| Any family (excluding `"other"`) has < 100 examples | `"Tactic family '{name}' has only {n} examples — may be under-represented"` |
| Any family accounts for > 30% of all steps | `"Tactic family '{name}' accounts for {pct}% of all steps — model may be biased"` |

> **Given** a JSONL file with 50,000 `"s"` records, all with non-empty `"c"` fields
> **When** `validate` runs
> **Then** returns report with total_steps=50,000, missing_tactic_steps=0

> **Given** a JSONL file where `intros` accounts for 35% of all steps
> **When** `validate` runs
> **Then** warnings includes "Tactic family 'intros' accounts for 35% of all steps — model may be biased"

### 4.8 HyperparameterTuner

Automated hyperparameter optimization using Optuna to maximize validation accuracy@5.

#### Tunable hyperparameters

| Parameter | Sampling type | Range | Default |
|-----------|--------------|-------|---------|
| `num_hidden_layers` | Categorical | {4, 6, 8, 12} | 6 |
| `learning_rate` | Log-uniform | [1e-6, 1e-4] | 2e-5 |
| `batch_size` | Categorical | {16, 32, 64} | 16 |
| `weight_decay` | Log-uniform | [1e-4, 1e-1] | 1e-2 |
| `class_weight_alpha` | Uniform | [0.0, 1.0] | 0.5 |
| `label_smoothing` | Uniform | [0.0, 0.3] | 0.1 |
| `sam_rho` | Log-uniform | [0.01, 0.2] | 0.05 |

All other hyperparameters (`max_seq_length`, `embedding_dim`, `max_epochs`, `early_stopping_patience`) are fixed at their default values and not tunable.

#### tune(dataset, output_dir, vocabulary_path, n_trials, study_name, resume)

- REQUIRES: `dataset` is a `TacticDataset` with at least 1,000 training steps. `output_dir` is a writable directory path. `vocabulary_path` points to a valid vocabulary JSON file. `n_trials` is a positive integer (default: 20). `study_name` is a non-empty string (default: `"poule-hpo"`). `resume` is a boolean (default: `False`).
- ENSURES: Creates an Optuna study with `TPESampler(seed=42)` and `MedianPruner(n_startup_trials=3, n_warmup_steps=3)`. Uses SQLite storage at `<output_dir>/hpo-study.db`. Runs `n_trials` trials sequentially. Each trial samples hyperparameters from the search space, creates a `TacticClassifierTrainer`, and trains using the sampled configuration. Each trial's checkpoint is saved to `<output_dir>/trial-<N>.pt`. On study completion, copies the best trial's checkpoint to `<output_dir>/best-model.pt`. Returns a `TuningResult`.
- When `resume` is `True`: loads the existing study from `<output_dir>/hpo-study.db` and continues from the last completed trial.
- When a trial raises `TrainingResourceError` (OOM): logs the error and continues to the next trial.
- When all trials fail (zero complete successfully): raises `TuningError`.
- Between trials: calls `gc.collect()` and `torch.cuda.empty_cache()` (when CUDA is available) to release memory.

**Pruner configuration:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `n_startup_trials` | 3 | First 3 trials run to completion to establish a baseline distribution |
| `n_warmup_steps` | 3 | Epochs 1–3 are immune to pruning within each trial (early metrics are noisy) |

**Pruning integration with training loop:**

1. The objective function defines an `epoch_callback` that calls `trial.report(val_accuracy, epoch)` and then checks `trial.should_prune()`.
2. If `should_prune()` returns `True`, the callback raises `optuna.TrialPruned`.
3. `TrialPruned` propagates through `_train_impl()` (only `RuntimeError` for OOM is caught in the inner loop).
4. Optuna's study runner catches `TrialPruned` and records the trial as pruned.

> **Given** a study with n_trials=20 and a dataset of 10,000 steps
> **When** `tune` completes
> **Then** the best checkpoint is at `<output_dir>/best-model.pt`, the study database is at `<output_dir>/hpo-study.db`, and `TuningResult` contains the best hyperparameters, best accuracy@5, trial count, and prune count

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
| `best_value` | float | Best validation accuracy@5 across all completed trials |
| `n_trials` | integer | Total number of trials (completed + pruned + failed) |
| `n_pruned` | integer | Number of trials pruned by the MedianPruner |
| `study_path` | string | Path to the SQLite study database |
| `all_trials` | list of dict | Per-trial summary: `{"number": int, "value": float or None, "state": str, "hyperparams": dict}` |

> **Given** a study with 20 trials where 12 completed, 5 were pruned, and 3 failed
> **When** `TuningResult` is constructed
> **Then** `n_trials=20`, `n_pruned=5`, `best_value` is the max accuracy@5 among the 12 completed trials, and `all_trials` has 20 entries

### 4.9 Device Detection

#### get_device()

- REQUIRES: Nothing.
- ENSURES: Returns a `torch.device` in priority order: CUDA (if `torch.cuda.is_available()`), CPU (fallback). MPS is not used due to memory leak issues.
- When the `POULE_DEVICE` environment variable is set: returns `torch.device(POULE_DEVICE)` regardless of detection.
- This is a module-level utility function used by `TacticClassifierTrainer._train_impl()`, `TacticEvaluator`, and `HyperparameterTuner`.

### 4.10 MLXTacticClassifier

MLX port of the tactic classifier model, architecturally identical to the PyTorch `TacticClassifier`.

#### Construction

`MLXTacticClassifier(vocab_size, num_classes, num_layers=6, hidden_size=768, num_heads=12)`

- REQUIRES: `vocab_size` is a positive integer matching the closed vocabulary size. `num_classes` is a positive integer matching the number of tactic families. `num_layers` is in {4, 6, 8, 12}.
- ENSURES: Creates an `mlx.nn.Module` with:
  - `mlx.nn.Embedding(vocab_size, hidden_size)` — token embedding layer
  - Transformer encoder with `num_layers` `mlx.nn.TransformerEncoderLayer` blocks, each with `hidden_size` hidden dimension and `num_heads` attention heads
  - No positional encoding module — position IDs are added as a learned embedding
  - `mlx.nn.Linear(hidden_size, num_classes)` — classification head

#### forward(input_ids, attention_mask)

- REQUIRES: `input_ids` is an `mx.array` of shape `[B, seq_len]`. `attention_mask` is an `mx.array` of shape `[B, seq_len]` with values 0 or 1.
- ENSURES: Returns logits of shape `[B, num_classes]`.
  1. Token embeddings: `embedding(input_ids)` → `[B, seq_len, 768]`
  2. Add positional embeddings
  3. Transformer encoding (`num_layers` layers)
  4. Mean pooling: `sum(output * mask) / sum(mask)` per sequence
  5. Linear projection: `linear(pooled)` → `[B, num_classes]`

#### load_codebert_weights(pytorch_model_name="microsoft/codebert-base")

- REQUIRES: `transformers` and `torch` are installed. `pytorch_model_name` is a valid HuggingFace model name.
- ENSURES: Loads CodeBERT weights from HuggingFace, applies layer dropping (selecting `num_layers` layers at evenly spaced indices from the 12-layer source, same index computation as PyTorch `TacticClassifier`), converts each parameter `torch.Tensor` → `numpy` → `mx.array`, maps parameter names from HuggingFace convention to MLX convention, and loads into the model. The embedding layer is replaced with one sized to `vocab_size`: overlapping tokens get copied pretrained vectors, new tokens are initialized from `N(0, 0.02)`. The classification head `Linear(768, num_classes)` is initialized randomly (not from CodeBERT).
- When `num_layers` is 12: all layers are loaded (no dropping).
- When `transformers` is not installed: raises `ImportError` with message `"transformers is required for CodeBERT weight initialization"`.

**Parameter name mapping (HuggingFace → MLX):**

| HuggingFace path | MLX path |
|-----------------|----------|
| `roberta.embeddings.word_embeddings.weight` | `embedding.weight` |
| `roberta.embeddings.position_embeddings.weight` | `position_embedding.weight` |
| `roberta.encoder.layer.{i}.attention.self.query.weight` | `layers.{i}.attention.query_proj.weight` |
| `roberta.encoder.layer.{i}.attention.self.query.bias` | `layers.{i}.attention.query_proj.bias` |
| `roberta.encoder.layer.{i}.attention.self.key.weight` | `layers.{i}.attention.key_proj.weight` |
| `roberta.encoder.layer.{i}.attention.self.key.bias` | `layers.{i}.attention.key_proj.bias` |
| `roberta.encoder.layer.{i}.attention.self.value.weight` | `layers.{i}.attention.value_proj.weight` |
| `roberta.encoder.layer.{i}.attention.self.value.bias` | `layers.{i}.attention.value_proj.bias` |
| `roberta.encoder.layer.{i}.attention.output.dense.weight` | `layers.{i}.attention.out_proj.weight` |
| `roberta.encoder.layer.{i}.attention.output.dense.bias` | `layers.{i}.attention.out_proj.bias` |
| `roberta.encoder.layer.{i}.attention.output.LayerNorm.weight` | `layers.{i}.ln1.weight` |
| `roberta.encoder.layer.{i}.attention.output.LayerNorm.bias` | `layers.{i}.ln1.bias` |
| `roberta.encoder.layer.{i}.intermediate.dense.weight` | `layers.{i}.linear1.weight` |
| `roberta.encoder.layer.{i}.intermediate.dense.bias` | `layers.{i}.linear1.bias` |
| `roberta.encoder.layer.{i}.output.dense.weight` | `layers.{i}.linear2.weight` |
| `roberta.encoder.layer.{i}.output.dense.bias` | `layers.{i}.linear2.bias` |
| `roberta.encoder.layer.{i}.output.LayerNorm.weight` | `layers.{i}.ln2.weight` |
| `roberta.encoder.layer.{i}.output.LayerNorm.bias` | `layers.{i}.ln2.bias` |

### 4.11 MLXTrainer

Training loop using MLX's functional gradient computation.

#### train(dataset, output_dir, vocabulary_path, hyperparams, epoch_callback)

- REQUIRES: `dataset` is a `TacticDataset` with at least 1,000 training steps. `output_dir` is a writable directory path. `vocabulary_path` points to a valid vocabulary JSON file. `hyperparams` has defaults matching `TacticClassifierTrainer`. `epoch_callback` is `None` or a callable `(epoch: int, val_accuracy: float) -> None`. Platform is macOS with Apple Silicon. `mlx` package is installed.
- ENSURES: Creates an `MLXTacticClassifier` with vocabulary-sized embeddings and `num_classes` from the dataset. Loads CodeBERT pretrained weights via `load_codebert_weights()`. Trains using functional gradient computation (`nn.value_and_grad`). Saves the best checkpoint (by validation accuracy@5) as MLX safetensors to `output_dir`. Prints training metrics after each epoch. When `epoch_callback` is not `None`, invokes it after each epoch's validation.
- When `mlx` is not installed: raises `BackendNotAvailableError("MLX is not installed. Install with: pip install mlx")`.
- When platform is not macOS: raises `BackendNotAvailableError("MLX training requires macOS with Apple Silicon")`.

**Training loop structure:**

```python
loss_and_grad_fn = nn.value_and_grad(model, cross_entropy_loss)

for epoch in range(max_epochs):
    for micro_batch in batches:
        state_ids, state_mask = tokenize(micro_batch.states)
        labels = mx.array(micro_batch.labels)

        loss, grads = loss_and_grad_fn(
            model, state_ids, state_mask, labels, class_weights
        )

        optimizer.update(model, grads)
        mx.eval(model.parameters(), optimizer.state)

    val_accuracy = compute_accuracy_at_k(model, dataset.val, k=5)
    # early stopping, checkpointing, callback
```

- MAINTAINS: `mx.eval()` is called once per optimizer step, not per operation. This allows MLX to build and optimize the computation graph before executing.
- MAINTAINS: Gradient accumulation uses the same micro-batch/accumulation pattern as the PyTorch trainer.

#### Cross-entropy loss (MLX)

```python
def cross_entropy_loss_mlx(model, state_ids, state_mask, labels, class_weights):
    logits = model(state_ids, state_mask)  # [B, num_classes]
    # Compute weighted cross-entropy with class_weights
    # Return scalar loss
```

- MAINTAINS: Numerically identical to the PyTorch implementation (within floating-point tolerance). Same class weighting, same mean reduction.

#### Checkpoint format (MLX)

Checkpoints are saved as a directory:

```
<output_dir>/
├── model.safetensors       # MLX model weights (mx.save_safetensors)
├── config.json             # {"vocab_size": int, "num_classes": int, "num_layers": 6, "hidden_size": 768, "num_heads": 12}
├── hyperparams.json        # Training hyperparameters used
├── label_map.json          # Tactic family name → class index mapping
├── vocabulary_path.txt     # Path to vocabulary JSON (single line)
├── best_accuracy_5.txt     # Best validation accuracy@5 (single line, float)
└── training_log.jsonl      # Per-epoch metrics: {"epoch": int, "loss": float, "val_acc_1": float, "val_acc_5": float}
```

- MAINTAINS: `model.safetensors` uses the safetensors format compatible with `mx.load()`.

#### Validation accuracy computation

During training, validation accuracy@5 is computed:

1. Encode all validation states through the model
2. Compute logits for each state
3. Check whether the ground-truth label is in the top-5 predicted classes (by logit value)
4. accuracy@5 = fraction of validation steps where ground truth is in top-5
5. All arrays are `mx.array`; `mx.eval()` is called before measuring accuracy

### 4.12 WeightConverter

Converts MLX-trained checkpoints to PyTorch format for the quantization and inference pipelines.

#### convert(mlx_checkpoint_dir, output_path)

- REQUIRES: `mlx_checkpoint_dir` is a directory containing `model.safetensors`, `config.json`, `hyperparams.json`, `label_map.json`, and `vocabulary_path.txt` (as produced by `MLXTrainer`). `output_path` is a writable path. Both `mlx` and `torch` are installed.
- ENSURES: Loads MLX weights from safetensors. Maps parameter names from MLX convention to PyTorch/HuggingFace convention (reverse of the table in 4.10). Converts each parameter: `mx.array` → `numpy` → `torch.Tensor`. Creates a PyTorch `TacticClassifier` with the same architecture, vocabulary size, and `num_classes`. Loads the converted state dict. Validates conversion quality. Saves as a PyTorch checkpoint (`.pt`) with `model_state_dict`, `hyperparams`, `vocabulary_path`, `label_map`, `epoch`, and `best_accuracy_5`.

**Validation step:**

1. Generate 100 random input tensors (input_ids in vocabulary range, attention_mask of 1s).
2. Run the same inputs through both MLX and PyTorch models.
3. Compare predicted labels (argmax of logits) between the two models.
4. If predicted labels disagree on > 1% of inputs: raise `WeightConversionError` with the agreement percentage.

- MAINTAINS: The converted PyTorch checkpoint is indistinguishable from one produced by `TacticClassifierTrainer.train()` — same keys, same format, compatible with `ModelQuantizer.quantize()` and `TacticEvaluator.evaluate()`.

> **Given** an MLX checkpoint directory produced by `MLXTrainer.train()`
> **When** `convert` runs
> **Then** a PyTorch `.pt` checkpoint is produced that passes the 99% label agreement validation

> **Given** a converted PyTorch checkpoint
> **When** passed to `ModelQuantizer.quantize()`
> **Then** ONNX export and INT8 quantization succeed with label agreement >= 98%

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| JSONL file not found | `FileNotFoundError` | Propagated to CLI |
| JSONL parse error (invalid JSON on a line) | `DataFormatError` | Line skipped, counted as malformed record |
| Index database not found | `IndexNotFoundError` | Propagated to CLI |
| Index database has no declarations (vocabulary build) | `InsufficientDataError` | Propagated with message: `"No declarations found in index database"` |
| Checkpoint file not found | `CheckpointNotFoundError` | Propagated to CLI |
| GPU out of memory during training | `TrainingResourceError` | Propagated with batch size suggestion |
| Quantization validation failure (label agreement < 98%) | `QuantizationError` | Propagated with agreement percentage |
| Training dataset has < 1,000 steps after filtering | `InsufficientDataError` | Propagated to CLI |
| Validation split is empty | `InsufficientDataError` | Propagated (split has 0 files in validation position) |
| Vocabulary JSON not found | `FileNotFoundError` | Propagated to CLI |
| Vocabulary JSON malformed | `DataFormatError` | Propagated with message: `"Invalid vocabulary file"` |
| All HPO trials fail (zero complete) | `TuningError` | Propagated with message: `"Hyperparameter optimization failed: 0 of {n} trials completed successfully"` |
| MLX not installed | `BackendNotAvailableError` | Propagated with message: `"MLX is not installed. Install with: pip install mlx"` |
| MLX requested on non-macOS | `BackendNotAvailableError` | Propagated with message: `"MLX training requires macOS with Apple Silicon"` |
| Weight conversion label disagreement > 1% | `WeightConversionError` | Propagated with agreement percentage |
| MLX checkpoint directory missing required files | `CheckpointNotFoundError` | Propagated with missing file list |

Error hierarchy:
- `NeuralTrainingError` — base class for all training pipeline errors
  - `DataFormatError` — JSONL parse or schema error
  - `CheckpointNotFoundError` — model checkpoint missing
  - `TrainingResourceError` — GPU OOM or insufficient compute
  - `QuantizationError` — INT8 conversion quality check failed
  - `InsufficientDataError` — not enough training data
  - `TuningError` — hyperparameter optimization study failed (zero trials completed)
  - `BackendNotAvailableError` — requested training backend (MLX) is not available
  - `WeightConversionError` — MLX → PyTorch weight conversion quality check failed

## 6. Non-Functional Requirements

| Metric | Target |
|--------|--------|
| Training time (105K steps, 16GB+ GPU) | < 4 hours |
| Training time (15K steps, 16GB+ GPU) | < 1 hour |
| Fine-tuning time (2K steps, 16GB+ GPU) | < 4 hours |
| Validation pass (per epoch) | < 60 seconds |
| Vocabulary build (15K declarations + 100K steps) | < 60 seconds |
| Data validation (single pass, 100K steps) | < 30 seconds |
| Quantization (export + validate) | < 5 minutes |
| Peak GPU memory (batch_size=64, seq_len=512) | ≤ 16GB |
| Training time (15K steps, M2 Pro MLX) | < 30 minutes |
| Training time (105K steps, M2 Pro MLX) | < 3 hours |
| HPO (20 trials, 15K steps, M2 Pro MLX) | < 5 hours (with pruning) |
| Weight conversion (MLX → PyTorch) | < 2 minutes |
| HPO (20 trials, 15K steps, 16GB+ GPU) | < 2 hours (with pruning) |

## 7. Examples

### Full training workflow

```
# 0. Build vocabulary
vocab_report = build("index.db", ["stdlib.jsonl", "mathcomp.jsonl"], "coq-vocabulary.json")
# vocab_report.total_tokens = 15,425

# 1. Validate data
report = validate(["stdlib.jsonl", "mathcomp.jsonl"])
# report.total_steps = 105,000, no warnings

# 2. Load data
dataset = load(["stdlib.jsonl", "mathcomp.jsonl"])
# dataset.train: 84,000 steps, dataset.val: 10,500 steps, dataset.test: 10,500 steps
# dataset.num_classes = 28

# 3. Train (with closed vocabulary)
train(dataset, "model.pt", vocabulary_path="coq-vocabulary.json",
      hyperparams={batch_size: 64, lr: 2e-5, epochs: 20})
# Epoch 1: loss=3.2, val_acc@1=0.15, val_acc@5=0.42
# Epoch 2: loss=2.4, val_acc@1=0.28, val_acc@5=0.61
# ...
# Epoch 12: loss=0.9, val_acc@1=0.45, val_acc@5=0.83 (best)
# Epoch 13-15: no improvement -> early stopping

# 4. Evaluate
eval_report = evaluate("model.pt", dataset.test)
# acc@1=0.43, acc@5=0.82, 28 families

# 5. Quantize
quantize("model.pt", "tactic-predictor.onnx")
# Label agreement: 99.0% (>= 98% threshold)
# tactic-labels.json written alongside

# 6. Deploy: copy .onnx + tactic-labels.json to well-known model path
```

### Hyperparameter optimization workflow

```
# 1. Load data (same as training)
dataset = load(["stdlib.jsonl", "mathcomp.jsonl"])

# 2. Run HPO
result = tune(dataset, "hpo-output/", vocabulary_path="coq-vocabulary.json", n_trials=20)
# Trial 0: lr=3.2e-5, batch=64, wd=5.1e-3, alpha=0.6 -> acc@5=0.78
# Trial 1: lr=8.7e-6, batch=128, wd=2.3e-2, alpha=0.3 -> acc@5=0.72
# Trial 2: lr=1.2e-4, batch=32, wd=8.9e-4, alpha=0.9 -> pruned at epoch 5
# ...
# Trial 19: lr=2.8e-5, batch=64, wd=7.2e-3, alpha=0.5 -> acc@5=0.84
#
# result.best_value = 0.84, result.n_pruned = 7
# Best checkpoint: hpo-output/best-model.pt

# 3. Resume an interrupted study
result = tune(dataset, "hpo-output/", vocabulary_path="coq-vocabulary.json",
              n_trials=30, resume=True)
# Continues from trial 20 (10 more trials)
```

### MLX training workflow (Apple Silicon)

```
# 0-2. Build vocabulary, validate, load -- same as PyTorch workflow

# 3. Train with MLX backend (on Mac)
mlx_train(dataset, "mlx-model/", vocabulary_path="coq-vocabulary.json",
          hyperparams={batch_size: 64, lr: 2e-5, epochs: 20})
# Epoch 1: loss=3.2, val_acc@1=0.15, val_acc@5=0.42
# ...
# Epoch 12: loss=0.9, val_acc@1=0.45, val_acc@5=0.83 (best)

# 4. Convert MLX -> PyTorch
convert("mlx-model/", "model.pt")
# Label agreement: 100% (>= 99% threshold)

# 5-6. Evaluate, quantize -- same as PyTorch workflow
# These use the converted PyTorch checkpoint
eval_report = evaluate("model.pt", dataset.test)
quantize("model.pt", "tactic-predictor.onnx")
```

### Fine-tuning workflow

```
# User extracts their project's proofs
# poule extract /path/to/my-project --output my-project.jsonl

dataset = load(["my-project.jsonl"])
fine_tune("model.pt", dataset, "fine-tuned.pt", hyperparams={lr: 5e-6, epochs: 10})
# Adapts to project-specific tactic patterns
```

## 8. Language-Specific Notes (Python)

- Use `torch` for model definition, training loop, and checkpoint management (PyTorch backend).
- Use `transformers` for the base encoder model (CodeBERT or equivalent) and tokenizer.
- Use `torch.cuda.amp` for mixed-precision training (FP16 forward pass, FP32 gradients).
- Use `torch.utils.data.DataLoader` with a custom `Dataset` for batching and shuffling.
- Use `onnx` and `onnxruntime.quantization` for ONNX export and dynamic INT8 quantization.
- Checkpoint format: `torch.save({"model_state_dict": ..., "optimizer_state_dict": ..., "epoch": ..., "best_accuracy_5": ..., "hyperparams": ..., "label_map": ..., "vocabulary_path": ...})`.
- Use `optuna` for hyperparameter optimization. Import lazily — only required when `tune()` is called.
- Use `mlx` for the MLX training backend. Import lazily — only required when `--backend mlx` is specified.
- Use `mlx.nn` for model definition, `mlx.optimizers` for optimizer, `mlx.nn.value_and_grad` for functional gradients.
- MLX checkpoint format: `mx.save_safetensors()` for weights, JSON files for config, hyperparameters, and label map.
- Weight conversion uses `mx.load()` → `numpy` → `torch.Tensor` for parameter conversion.
- PyTorch backend package: `src/Poule/neural/training/`.
- MLX backend package: `src/Poule/neural/training/mlx_backend/`.
- Inference package: `src/Poule/neural/predictor.py`.

## 8. TacticPredictor (Inference)

**Architecture**: [neural-tactic-prediction.md](../doc/architecture/neural-tactic-prediction.md)

### 8.1 TacticPredictor

`TacticPredictor(model_path, labels_path, vocabulary_path)`

- REQUIRES: `model_path` is a valid ONNX file. `labels_path` is a JSON list of tactic family names. `vocabulary_path` is a vocabulary JSON file.
- ENSURES: Loads the ONNX model via `onnxruntime.InferenceSession`, the label names from `labels_path`, and constructs a `CoqTokenizer` from `vocabulary_path`. All three files must exist.
- On missing file: raises `FileNotFoundError`.

#### predict(proof_state_text, top_k=5)

- REQUIRES: `proof_state_text` is a non-empty string. `top_k >= 1`.
- ENSURES: Returns a list of `(family_name, confidence)` tuples, sorted by confidence descending, length = min(top_k, num_classes). Confidence values sum to approximately 1.0 across all classes (softmax output).

Algorithm:
1. Tokenize `proof_state_text` via `CoqTokenizer.encode(text, max_length=512)`.
2. Run ONNX session: input `[1, seq_len]` → output logits `[1, num_classes]`.
3. Apply softmax to logits → probability distribution.
4. Return top-K `(label_names[i], prob[i])` pairs sorted by probability descending.

> **Given** a proof state "n : nat\nn + 0 = n" and a trained model
> **When** `predict(state, top_k=3)` is called
> **Then** returns 3 tuples like `[("rewrite", 0.35), ("simpl", 0.28), ("induction", 0.15)]`

#### is_available() (static)

- ENSURES: Returns `True` if all three required files (model, labels, vocabulary) exist at their expected paths. Returns `False` otherwise.

### 8.2 Integration with suggest_tactics

The `tactic_suggest()` function in `src/Poule/tactics/suggest.py` integrates neural predictions:

1. Check if `TacticPredictor.is_available()`.
2. If available: call `predict(proof_state_text, top_k=5)`.
3. Generate rule-based suggestions from goal structure (existing behavior).
4. Merge: neural predictions first (sorted by confidence), then rule-based suggestions not already covered by neural predictions.
5. Return combined list as `list[TacticSuggestion]`.

- ENSURES: When predictor is unavailable, behavior is identical to the existing rule-based implementation. No errors raised.
- ENSURES: Neural suggestions include `source="neural"` in their metadata. Rule-based suggestions include `source="rule"`.

> **Given** a `suggest_tactics` call with no trained model
> **When** the tool executes
> **Then** only rule-based suggestions are returned (existing behavior, unchanged)

### 8.3 ArgumentRetriever

The `ArgumentRetriever` class in `src/Poule/tactics/argument_retriever.py` resolves tactic family predictions into full tactic suggestions by querying the retrieval pipeline for lemma candidates.

#### Constructor

```python
ArgumentRetriever(pipeline_context: PipelineContext | None)
```

- REQUIRES: `pipeline_context` is either a valid `PipelineContext` with a loaded search index, or `None`.
- ENSURES: When `pipeline_context` is None, all calls to `retrieve()` return an empty list.

#### Tactic family classification

Each tactic family is classified as either **argument-taking** or **argument-free**:

| Classification | Families | Behavior |
|---|---|---|
| Argument-taking (type match) | `apply`, `exact` | Retrieve lemmas whose conclusion matches the goal type |
| Argument-taking (rewrite) | `rewrite` | Retrieve equality lemmas containing symbols from the goal |
| Argument-free | All others (`intros`, `simpl`, `auto`, `destruct`, `induction`, `unfold`, `split`, `case`, etc.) | No retrieval; return empty list |

This classification is defined as a constant mapping `ARGUMENT_FAMILIES: dict[str, str]` where the key is the tactic family name and the value is the retrieval strategy name (`"type_match"` or `"rewrite"`).

#### retrieve(family, goal_type, hypotheses, limit=5)

```python
def retrieve(
    self,
    family: str,
    goal_type: str,
    hypotheses: list[Hypothesis],
    limit: int = 5,
) -> list[ArgumentCandidate]
```

- REQUIRES: `family` is a tactic family name. `goal_type` is the focused goal's type string. `hypotheses` is the list of hypotheses in scope. `limit >= 1`.
- ENSURES: Returns a list of `ArgumentCandidate` objects, each containing a lemma name and a retrieval score in [0.0, 1.0]. The list has at most `limit` entries, sorted by score descending.
- ENSURES: If `family` is not in `ARGUMENT_FAMILIES`, returns an empty list.
- ENSURES: If `pipeline_context` is None, returns an empty list.
- ENSURES: If the retrieval pipeline raises an exception, catches it, logs a warning, and returns an empty list.

**Strategy: type_match** (for `apply`, `exact`):
1. Call `search_by_type(pipeline_context, goal_type, limit=limit * 2)` to find lemmas whose type structurally matches the goal.
2. Also scan hypotheses: any hypothesis whose type string equals the goal type is included as a candidate with score 1.0.
3. Deduplicate by name (hypotheses take priority over index results).
4. Return the top `limit` candidates.

**Strategy: rewrite** (for `rewrite`):
1. Call `search_by_type(pipeline_context, goal_type, limit=limit * 3)` to find lemmas related to the goal.
2. Filter results to those whose statement contains `=` (equality lemmas).
3. Also scan hypotheses: any hypothesis whose type contains `=` is included as a candidate with score 1.0.
4. Deduplicate by name (hypotheses take priority).
5. Return the top `limit` candidates.

> **Given** a neural prediction of `apply` with confidence 0.35, a goal type `n + 0 = n`, and a search index
> **When** `retrieve("apply", "n + 0 = n", hypotheses, limit=3)` is called
> **Then** returns up to 3 `ArgumentCandidate` objects, e.g., `[ArgumentCandidate("Nat.add_0_r", 0.82), ...]`

> **Given** a neural prediction of `rewrite` and a goal type `n + 0 = n`
> **When** `retrieve("rewrite", "n + 0 = n", hypotheses, limit=3)` is called
> **Then** returns candidates that are equality lemmas, filtered from retrieval results

> **Given** a neural prediction of `simpl`
> **When** `retrieve("simpl", goal_type, hypotheses)` is called
> **Then** returns an empty list (simpl is argument-free)

> **Given** no search index loaded (pipeline_context is None)
> **When** `retrieve("apply", goal_type, hypotheses)` is called
> **Then** returns an empty list

#### ArgumentCandidate

```python
@dataclass(frozen=True)
class ArgumentCandidate:
    name: str       # Lemma name (e.g., "Nat.add_0_r")
    score: float    # Retrieval score in [0.0, 1.0]
```

### 8.4 Integration of argument retrieval with suggest_tactics

The `tactic_suggest()` function is extended to call `ArgumentRetriever` after neural prediction:

1. Neural predictor returns top-K families with confidence scores (existing §8.2 behavior).
2. For each neural prediction with confidence >= 0.1:
   a. Call `ArgumentRetriever.retrieve(family, goal_type, hypotheses, limit=3)`.
   b. For each `ArgumentCandidate`, construct a `TacticSuggestion` with `tactic="{family} {candidate.name}"`, `confidence` derived from `family_confidence × candidate.score`, and `source="neural+retrieval"`.
3. Insert argument-enriched suggestions immediately after their parent family suggestion.
4. The family-only suggestion is preserved (it remains useful when the argument candidates are wrong).
5. Apply deduplication and limit as before.

- ENSURES: When `ArgumentRetriever` returns no candidates for a family, the family-only suggestion is still included.
- ENSURES: Argument-enriched suggestions have `source="neural+retrieval"` to distinguish them from family-only neural suggestions (`source="neural"`) and rule-based suggestions (`source="rule"`).
- ENSURES: The `ArgumentRetriever` is initialized once (lazy singleton) alongside the `TacticPredictor`, using the same `PipelineContext` as the retrieval pipeline.

> **Given** a neural prediction of `apply` (confidence 0.35) and retrieval returning `Nat.add_0_r` (score 0.82)
> **When** suggestions are constructed
> **Then** the output includes both `TacticSuggestion(tactic="apply", source="neural")` and `TacticSuggestion(tactic="apply Nat.add_0_r", source="neural+retrieval")`
