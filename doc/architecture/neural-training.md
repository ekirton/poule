# Neural Training Pipeline

Technical design for the training, evaluation, and quantization pipeline for the neural tactic prediction model.

**Feature**: [Model Training CLI](../features/model-training-cli.md), [Pre-trained Model](../features/pre-trained-model.md)

---

## Component Diagram

```
Search index (index.db) + Extracted training data (JSON Lines)
  │
  │ poule build-vocabulary
  ▼
Closed vocabulary (coq-vocabulary.json)
  │
  │ poule train
  ▼
┌──────────────────────────────────────────────────────────┐
│                  Training Pipeline                        │
│                                                          │
│  ┌────────────────┐  ┌───────────────┐  ┌──────────────┐│
│  │ Data Loader    │  │ Tactic        │  │ Loss         ││
│  │                │  │ Classifier    │  │ Computation  ││
│  │ Read JSONL     │  │               │  │              ││
│  │ Parse (state,  │  │ CodeBERT      │  │ Weighted     ││
│  │  tactic)       │  │ encoder       │  │ cross-       ││
│  │ Extract tactic │  │ Mean pooling  │  │ entropy      ││
│  │  family        │  │ Linear head   │  │              ││
│  └───────┬────────┘  └───────┬───────┘  └──────┬───────┘│
│          │                   │                  │        │
│          └───────────────────┴──────────────────┘        │
│                          │                               │
│                          │ checkpoint                    │
│                          ▼                               │
│              Model Checkpoint (.pt)                      │
│                          │                               │
│                          │ poule quantize                │
│                          ▼                               │
│              INT8 ONNX Model (.onnx)                     │
└──────────────────────────────────────────────────────────┘
  │
  │ poule evaluate
  ▼
Evaluation Report
(accuracy@1, accuracy@5, per-family precision/recall)
```

## Vocabulary Building

```
poule build-vocabulary --db <index.db> --data <traces.jsonl> --output <coq-vocabulary.json>
```

Constructs a closed-vocabulary tokenizer that maps every Coq identifier to a unique integer token ID. This replaces CodeBERT's generic BPE tokenizer, which fragments Coq identifiers into 3-9 subword tokens. With a closed vocabulary, every identifier is exactly 1 token. See `coq-vocabulary.md` for the full design rationale.

### Sources

The vocabulary is built from two sources:

1. **Search index** (`index.db`) -- all fully-qualified declaration names from the `declarations` table.
2. **Serialized proof states** from the training data -- scanning the JSONL extraction output captures hypothesis variable names and syntax tokens that appear in the model's input distribution. Both `"s"` (step) and `"g"` (goal) records are processed.

### Fixed Token Sets

| Category | Examples | Count |
|----------|----------|-------|
| Special tokens | `[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]` | 5 |
| Punctuation / delimiters | `(`, `)`, `{`, `}`, `[`, `]`, `:`, `;`, `,`, `.`, `|`, `@`, `!`, `?`, `_`, `'`, `#`, `=`, `+`, `-`, `*`, `/`, `<`, `>`, `~` | ~25 |
| SSReflect tacticals | `/=`, `//`, `//=`, `=>`, `->`, `<-` | 6 |
| Scope delimiters | `%N`, `%Z`, `%R`, `%Q`, `%positive`, `%type` | 6 |
| Unicode math symbols | `forall`, `exists`, `->`, `<-`, `<->`, `|-`, `<=`, `>=`, `<>`, etc. | 31 |
| Greek letters | alpha-omega, Gamma-Omega | 33 |
| Digits | `0`-`9` | 10 |

### Construction Procedure

1. Initialize the vocabulary with the 5 special tokens at IDs 0-4.
2. Add all fixed token sets.
3. Read all declaration names from `index.db`.
4. Scan the JSONL training data: for each `"s"` and `"g"` record, split proof state text on whitespace and collect unique tokens.
5. Apply NFC Unicode normalization.
6. Assign sequential integer IDs.
7. Write as JSON mapping token strings to integer IDs.

### Expected Size

~150K tokens: ~118K library identifiers, ~33K variable names and syntax fragments, ~110 fixed tokens, 64 Unicode/Greek symbols, 5 special tokens.

### Tokenization at Inference

Whitespace split + O(1) dictionary lookup per token:
1. NFC Unicode normalization
2. Split on whitespace
3. Look up each token -> ID (or `[UNK]`)
4. Prepend `[CLS]`, append `[SEP]`
5. Pad or truncate to `max_length=512`

### Embedding Layer Integration

The closed vocabulary replaces CodeBERT's 50,265-token vocabulary with ~150K tokens. The TacticClassifier model reinitializes its embedding layer:

1. Load CodeBERT's transformer layers (1-12) with pretrained weights.
2. Create `nn.Embedding(vocab_size, 768)`.
3. Copy pretrained embeddings for overlapping tokens (digits, punctuation, common words).
4. Initialize Coq-specific tokens randomly (sigma=0.02).

### Embedding Factorization

The 158K-token embedding matrix dominates model size (121.5M of 150.4M parameters, 81%). Most tokens are rare Coq identifiers that appear in a handful of training examples and cannot learn meaningful 768-dimensional representations.

Following ALBERT (Lan et al., 2020), the embedding matrix is decomposed into two smaller matrices:

```
Standard:   nn.Embedding(V, H)                  158,242 × 768 = 121.5M params
Factored:   nn.Embedding(V, D) + nn.Linear(D, H)  158,242 × 128 + 128 × 768 = 20.4M params
```

where D is a configurable bottleneck dimension (default 128). Each token gets a compact D-dimensional embedding, which a bias-free linear projection expands to the hidden dimension H=768 that the transformer expects. When `embedding_dim` equals `hidden_size` (768), no projection is applied and the model behaves identically to the standard architecture.

The position embedding remains at H dimensions — it is small (514 × 768 = 0.4M) and benefits from full-rank representation.

**Initialization:** Embedding weights are initialized randomly (σ=0.02) with CodeBERT overlap copied as before — but only the first D dimensions are stored. The projection matrix is initialized from a truncated SVD of CodeBERT's original 768-dim embedding matrix, preserving the most important directions. Since the custom vocabulary already discards CodeBERT's tokens, there are no pretrained embedding weights to preserve.

**Checkpoint format:** The `embedding_dim` value is stored in checkpoints alongside `num_hidden_layers`. On load, the model reconstructs the correct architecture (with or without projection) from the checkpoint metadata.

### CoqTokenizer

A lightweight tokenizer class wrapping the vocabulary JSON:
- `encode(text, max_length=512)` -> `(input_ids, attention_mask)` tensors
- `encode_batch(texts, max_length=512)` -> batched tensors with padding
- `vocab_size` property for embedding layer construction

## Training Data Collapse

A post-extraction preprocessing step that merges per-library JSONL files into a single training file with normalized tactic families. This addresses severe class imbalance in the raw extraction output: 2,113 raw families, of which 1,330 are singletons and many are parsing artifacts (compound tactic fragments like `destruct(q_dec`, `1:lia`).

```
poule collapse-training-data --min-count 50 --output training.jsonl training-stdlib.jsonl training-mathcomp.jsonl ...
```

### Pipeline

```
Per-library JSONL files (training-stdlib.jsonl, training-mathcomp.jsonl, ...)
  │
  │ 1. Read all "s" records
  │ 2. Normalize tactic family (enhanced extraction)
  │ 3. Count families across all inputs
  │ 4. Merge rare families → "other"
  │ 5. Write merged "s" records with updated "c" field
  ▼
Single collapsed JSONL file (training.jsonl)
```

### Enhanced Tactic Family Normalization

Extends the existing `extract_tactic_family` with additional rules to clean up compound tactic fragments:

1. **Strip parenthesized prefixes**: `destruct(q_dec` → `destruct`, `(apply` → `apply`, `(do` → `do`
2. **Strip numeric prefixes**: `1:lia` → `lia`, `2:reflexivity` → `reflexivity`
3. **Strip trailing modifiers**: `clear-` → `clear`, `split_and?` → `split`
4. All existing normalization (SSReflect `by` stripping, alias mapping, lowercasing, punctuation stripping)

### Output Format

The collapsed file contains only `"s"` records. Metadata, goal, error, and summary records from the per-library files are not copied — the collapsed file is a pure training input. Each record's `"c"` field is replaced with the normalized tactic family name:

```json
{"t":"s", "f":"Arith/Plus.v", "s":"n : nat\n...", "c":"simpl"}
```

### Configurable Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--min-count` | 50 | Families with fewer occurrences are mapped to "other" |
| `--output` | `training.jsonl` | Output file path |
| `--dry-run` | false | Print family distribution without writing output |

### Relationship to Data Loading

The collapsed file is consumed by `TrainingDataLoader.load()` identically to the per-library files. The loader filters tactics through the hierarchical taxonomy — only tactics listed in `TACTIC_TO_CATEGORY` are included, and proof structure tokens in `EXCLUDED_TOKENS` are skipped. There is no frequency thresholding or `"other"` catch-all at the loader level. The collapse step is optional — the training pipeline works with or without it.

## Data Loading

### Input Format

The training pipeline consumes `"s"` (step) records from JSON Lines files produced by the extraction pipeline:

```json
{"t":"s", "f":"Arith/Plus.v", "s":"n : nat\nm : nat\nn + S m = S (n + m)", "c":"simpl"}
```

Fields: `t` = record type, `f` = source file, `s` = serialized proof state, `c` = tactic command text.

The data loader:
1. Reads `"s"` records from JSONL files
2. Extracts tactic family from the tactic command text (first token, normalized)
3. Builds a label map: `dict[str, int]` mapping tactic family names to class indices
4. Constructs `(proof_state, tactic_family_index)` pairs

### Tactic Family Extraction

The tactic family is extracted from the raw tactic text:
1. Strip whitespace
2. Handle SSReflect: strip `by` prefix if present
3. Strip `/`-suffix for SSReflect compounds (`apply/eqp` → `apply`)
4. Take the first whitespace-delimited token
5. Normalize: lowercase, strip trailing punctuation
6. Map aliases (`intro` -> `intros`, etc.)
7. Map to a canonical category via `taxonomy.py`

### Hierarchical Tactic Taxonomy

Every tactic maps to one of 8 categories via a canonical taxonomy (`taxonomy.py`). All 8 categories have dedicated classification heads. Proof structure tokens (`-`, `+`, `*`, `{`, `}`) are excluded from training.

| Category | Example tactics | Estimated % |
|----------|----------------|----------:|
| Rewriting | rewrite, simpl, unfold, reflexivity | 25.8% |
| Hypothesis Management | apply, have, assert, specialize | 22.5% |
| Introduction | intros, split, left, right, exact | 12.2% |
| Elimination | destruct, induction, case, inversion | 7.0% |
| Automation | auto, eauto, trivial, tauto | 4.1% |
| SSReflect | move, suff, wlog, congr, unlock | ~3% |
| Arithmetic | lia, omega, ring, field | ~1% |
| Contradiction | exfalso, absurd, contradiction | <1% |

### Hierarchical Architecture

```
Encoder (shared, factored embeddings D=128, CodeBERT) → representation z [B, 768]
    ↓
Category Head: nn.Linear(768, 8) → category logits [B, 8]
    ↓
Per-Category Heads (8 heads):
    introduction_head:    nn.Linear(768, N_introduction)
    elimination_head:     nn.Linear(768, N_elimination)
    rewriting_head:       nn.Linear(768, N_rewriting)
    hypothesis_mgmt_head: nn.Linear(768, N_hypothesis_mgmt)
    automation_head:      nn.Linear(768, N_automation)
    ssreflect_head:       nn.Linear(768, N_ssreflect)
    arithmetic_head:      nn.Linear(768, N_arithmetic)
    contradiction_head:   nn.Linear(768, N_contradiction)
```

Joint loss: `L = L_category + λ · L_within(active head)`, where λ balances category vs. within-category loss (default 1.0, tunable [0.3, 3.0]).

Inference uses product rule: `P(tactic) = P(category) × P(tactic | category)`, returning top-k by final probability.

### Train/Validation/Test Split

Identical to the previous design: file-level split, deterministic by position modulo 10.

| Split | Fraction | Purpose |
|-------|----------|---------|
| Train | 80% of files | Model training |
| Validation | 10% of files | Early stopping during HPO |
| Test | 10% of files | Final evaluation |

### Final Model Selection

The final model is the best trial's checkpoint from HPO — no separate retraining step is performed. The tuner already saves each trial's best checkpoint (by validation accuracy@5) and copies the winning trial's checkpoint to `best-model.pt`. The `run-full-training.py` script copies this checkpoint to the final model directory for evaluation and ONNX export.

**Rationale:** Retraining on a merged train+val split with a fixed epoch count introduced a risk of overfitting (no validation signal to monitor) and added training time without reliably improving test accuracy. The HPO trial's checkpoint was already trained with early stopping against validation accuracy@5, making it the most reliable artifact.

**Pipeline flow:**

1. **HPO phase:** Standard train/val/test split. Each trial trains on the 80% train split with early stopping against the 10% validation split. The tuner uses validation accuracy@5 to select the winning trial.

2. **Model promotion:** The best trial's checkpoint (`hpo-results/best-model.pt`) is copied to the final model directory. No additional training occurs.

3. **Evaluation and export:** The promoted checkpoint is evaluated on the held-out test split and exported to ONNX.

### Head-Class Undersampling

After the file-level split, the training split is optionally undersampled to cap dominant tactic families. This reduces head-class redundancy and increases tail-class exposure per epoch.

**Parameters:**
- `undersample_cap`: maximum examples per tactic family in the training split (default: 2000). Set to `None` to disable.
- `undersample_seed`: random seed for reproducible selection (default: 42).

**Procedure:**
1. Group training pairs by tactic family (resolved from the hierarchical `(category_idx, within_idx)` labels).
2. For each family with more examples than `undersample_cap`, randomly sample `undersample_cap` examples using `undersample_seed`.
3. For families at or below the cap, retain all examples.
4. Concatenate the (possibly reduced) per-family groups into the new training split.

**Scope:** Only the training split is affected. Validation and test splits are never undersampled — they must reflect the true data distribution for unbiased evaluation.

**Effect on class weights:** Class weights are recomputed from the undersampled training distribution, not the original distribution. This ensures the loss function reflects the actual training data.

**Expected impact:** With a 2,000-example cap on the 6 dominant families (rewrite, intros, apply, auto, destruct, split), training reduces from ~114K to ~40–50K samples. Per-epoch tail-class exposure increases proportionally.

### Minority Oversampling

After undersampling caps dominant families, minority families in the 100–500 example range face a 4–20× imbalance against capped families within the same category head. Oversampling generates augmented copies of these families' training examples up to a configurable floor, reducing the maximum within-category imbalance ratio.

**Parameters:**
- `oversample_floor`: minimum examples per tactic family in the training split after oversampling (default: 500, i.e., 25% of the undersample cap). Set to `None` to disable.
- `oversample_seed`: random seed for reproducible augmentation (default: 42).

**Procedure:**
1. Run after `undersample_train()` — operates on the already-undersampled training split.
2. Group training pairs by tactic family.
3. For each family with fewer examples than `oversample_floor`, sample source examples with replacement from that family's existing pool using `oversample_seed`, generating `floor - len(family)` augmented examples. Each augmented example is created by applying label-preserving perturbations to the sampled source (see below).
4. For families already at or above the floor, retain all examples unchanged.
5. Concatenate the per-family groups into the new training split.

#### Proof State Perturbation

Each augmented example applies two label-preserving perturbations to the source proof state:

**Hypothesis shuffling.** Reorder hypotheses within each goal block. Proof states may contain multiple goal blocks separated by `\n\n`. Within each block, lines matching the hypothesis pattern (`identifier : type`) are shuffled randomly; the goal line (the final non-hypothesis line) stays in place. The correct tactic is independent of hypothesis ordering — Coq's context is an unordered set.

A line is a hypothesis if it matches: one or more identifier characters (`[a-zA-Z_][a-zA-Z_0-9']*`), followed by ` : ` (space-colon-space), followed by any text. Lines not matching this pattern are treated as goal lines.

**Identifier renaming.** Replace hypothesis variable names with random alternatives. For each goal block, collect all hypothesis names (the identifier before ` : `). Map each name to a fresh random identifier (drawn from a pool of synthetic names like `v0`, `v1`, ..., `v99`). Replace all occurrences of each original name with its replacement throughout the entire block (hypotheses and goal), using word-boundary-aware replacement to avoid partial matches (e.g., replacing `H` must not affect `H0`). Replacements are applied simultaneously to avoid cascading collisions.

Both perturbations are provably label-preserving: hypothesis order is semantically irrelevant, and tactic selection depends on the structure of types and the goal, not on variable names.

**Scope:** Only the training split is affected. Validation and test splits are never oversampled.

**Effect on class weights:** Class weights are recomputed from the oversampled training distribution. Capped families (2,000 examples) are unchanged; oversampled families (now 500 examples) have a 4:1 ratio against capped families instead of 20:1.

**Interaction with undersample_train min_count:** Families below `min_count` (default 100, i.e., 5% of cap) are dropped by `undersample_train` before oversampling runs. Oversampling does not resurrect dropped families — it only amplifies families that survived the minimum trainability threshold.

**Expected impact:** Families in the 100–500 range (the "trainable but underrepresented" bucket) get 2–5× augmented copies. The maximum augmentation factor is 5× (for a family with exactly 100 examples). Each augmented copy is a novel training example with shuffled hypotheses and renamed identifiers, providing genuine new signal unlike plain duplication.

### Leave-One-Library-Out Cross-Validation

A diagnostic evaluation mode that replaces the file-level split with a library-level split. For each fold, one of the 4 vanilla-Coq libraries is held out entirely as the test set, and the remaining 3 vanilla-Coq libraries plus MathComp provide training and validation data. This isolates whether the model generalizes across library boundaries or memorizes library-specific tactic conventions.

CoqInterval is excluded — its specialized interval-arithmetic proof style does not transfer (64/65 dead families in LOOCV). MathComp is included in training (it provides the SSReflect signal for the dedicated SSReflect head) but excluded from LOOCV hold-out because its SSReflect-dialect tactics (71% of steps) make it a poor hold-out candidate against vanilla-Coq libraries. The 4 vanilla-Coq libraries (stdlib, stdpp, flocq, coquelicot) are 78–99% vanilla Coq and serve as LOOCV folds.

```
poule loocv stdlib.jsonl stdpp.jsonl flocq.jsonl coquelicot.jsonl mathcomp.jsonl \
  --output-dir loocv-results/ --vocabulary coq-vocabulary.json --undersample-cap 1000
```

#### Data Loading: `load_by_library()`

An alternative to `TrainingDataLoader.load()` that splits by library membership:

1. Accept a `library_paths: dict[str, list[Path]]` mapping library names to their JSONL files, a `held_out_library: str`, and an optional `always_train_libraries: list[str]` (libraries that are always in the training set, never held out — default: `["mathcomp"]`).
2. Parse all JSONL files identically to `load()` (step extraction, taxonomy filtering, hierarchical labeling).
3. All steps from the held-out library → test set.
4. Steps from `always_train_libraries` always go to the training set (never held out, never used as validation).
5. Remaining libraries' files → shuffled (seeded) and split 90/10 for train/val at the file level.
6. Apply undersampling to the training split (default cap=1000, lower than the standard 2000 because holding out a library shrinks the training pool).

The same `TacticDataset` structure is returned — downstream training code is unchanged.

#### LOOCV Orchestration

`LibraryLOOCV.run()` iterates over the vanilla-Coq libraries (MathComp always trains, never held out):

```
For each library L in {stdlib, stdpp, flocq, coquelicot}:
    1. Load data with L held out (MathComp always in training set)
    2. Undersample training split at configured cap
    3. Train model with fixed hyperparameters (best from undersampled HPO)
    4. Evaluate on held-out library
    5. Collect FoldResult (accuracies, dead families, per-family recall, timing)
    6. Delete checkpoint (only aggregate results matter)

Aggregate into LOOCVReport: mean/std of test_acc@5, per-library comparison.
```

#### CLI

```
poule loocv DATA... --output-dir DIR --vocabulary PATH [--undersample-cap 1000] [--backend mlx|pytorch]
```

Library name is inferred from each JSONL filename stem (e.g., `stdlib.jsonl` → `"stdlib"`).

## Training

### Objective: Cross-Entropy with Class-Conditional Label Smoothing

**Class-conditional label smoothing.** Distributes smoothing mass ε proportionally to the inverse-frequency class weights rather than uniformly:

```
weight[c] = (total_samples / (num_classes * count[c])) ^ alpha
smooth_distribution[c] = weight[c] / sum(weights)
y_target = (1 - ε) * one_hot(label) + ε * smooth_distribution
```

This directs more smoothing probability mass toward minority classes, acting as targeted regularization against overfitting on underrepresented groups (Shwartz-Ziv et al., 2023).

When `label_smoothing=0.0`, standard hard targets are used (backward compatible).

### Optimizer: SAM-AdamW

Sharpness-Aware Minimization (SAM) with AdamW as the base optimizer. SAM seeks parameters that lie in flat loss neighborhoods rather than sharp minima, improving generalization — especially for minority classes whose loss landscape is poorly sampled.

The SAM update has two steps per batch:
1. **Perturbation**: compute gradient g, take an ascent step of size ρ in the gradient direction to find the worst-case neighborhood point.
2. **Descent**: compute gradient at the perturbed point, then take a standard AdamW step using this gradient.

This doubles the cost per batch (two forward-backward passes), but Shwartz-Ziv et al. found it significantly improves tail-class accuracy. The perturbation radius ρ (default 0.05) is tunable via HPO.

SAM is applied only to the PyTorch backend. The MLX backend continues to use plain AdamW (SAM support in MLX is not available).

### Model Architecture

```
Input: input_ids [B, 512], attention_mask [B, 512]
  |
  |-- CodeBERT encoder (num_hidden_layers layers, 768 hidden, 12 heads)
  |-- Mean pooling (attention-masked)
  |-- nn.Linear(768, num_classes)
  |-- Output: logits [B, num_classes]
```

Default `num_hidden_layers` is 6 (layer-dropped from CodeBERT's 12). Single forward pass per batch. No premise encoding, no contrastive pairs, no hard negatives.

#### Layer Dropping Initialization

New models are initialized with 6 transformer layers copied from every other layer of CodeBERT-base (layers 0, 2, 4, 6, 8, 10). This follows the DistilBERT approach (Sanh et al., 2019): halving the encoder preserves pretrained structural knowledge while reducing transformer parameters from ~85M to ~42M.

Rationale: Shwartz-Ziv et al. (2023) found that larger architectures overfit on class-imbalanced data. With an imbalance ratio of 26,950:1 and 86% of tactic families having ≤5 examples, a 12-layer encoder is unnecessarily large. CodeBERT's pretraining on six programming languages captures structural patterns (scoping, types, function application) that transfer to Coq — layer dropping preserves this knowledge more efficiently than training from scratch.

Initialization procedure:
1. Load full CodeBERT-base (12 layers) from HuggingFace.
2. Select layers at even indices: 0, 2, 4, 6, 8, 10.
3. Build a new `RobertaModel` with `num_hidden_layers=6`.
4. Copy the selected layers into the new model's encoder.
5. Copy all non-layer weights (embeddings, pooler) unchanged.
6. Replace the embedding layer with the custom vocabulary (same as current procedure).

The layer count is configurable via `num_hidden_layers`. Values of 4, 6, 8, and 12 are supported. For values less than 12, layers are selected at evenly spaced indices from the 12-layer source.

#### Knowledge Distillation (Backup)

If layer dropping alone does not meet accuracy targets, the 6-layer model can be trained with knowledge distillation from a fine-tuned 12-layer teacher:

```
L = α · CE(student_logits, labels) + (1 - α) · T² · KL(student_logits / T, teacher_logits / T)
```

- T (temperature): softens the teacher's output distribution, exposing inter-class relationships (e.g., `apply` and `exact` are more similar than `apply` and `intros`). Typical values: 3–5.
- α: balances hard-label loss (correct answer) vs. soft-label loss (teacher's distribution). Typical value: 0.5.

This requires two training runs: (1) fine-tune the full 12-layer CodeBERT on Coq tactic prediction, (2) train the 6-layer student against the teacher's soft targets. The distillation path is not implemented in the initial version — it is documented here as the escalation strategy if layer dropping underperforms.

### Hyperparameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Num hidden layers | 6 | Layer-dropped from CodeBERT-12; smaller model for imbalanced data (Shwartz-Ziv et al., 2023) |
| Batch size | 16 | Smaller batches improve tail-class generalization under severe imbalance (Shwartz-Ziv et al., 2023) |
| Learning rate | 2e-5 | Standard for BERT fine-tuning |
| Weight decay | 1e-2 | Standard AdamW |
| Class weight alpha | 0.5 | Moderate inverse-frequency rebalancing for label smoothing |
| Label smoothing | 0.1 | Prevents overfitting on minority classes (Shwartz-Ziv et al., 2023) |
| SAM rho | 0.15 | SAM perturbation radius; experimentally critical for generalization (collapsed val–test gap from 35pp to 6pp) |
| Max sequence length | 512 tokens | Standard |
| Training epochs | 20 | Early stopping on validation accuracy@5 |
| Early stopping patience | 3 epochs | Stop if accuracy@5 does not improve |

### Training Hardware

| Corpus size | Hardware | Estimated wall time | Estimated cost |
|-------------|----------|---------------------|----------------|
| ~140K steps (all 5 libraries) | Any 16GB+ GPU | ~4 hours | $20-50 |
| ~140K steps (all 5 libraries) | M2 Pro, 32GB (MLX) | ~3 hours | $0 (local) |
| 15K steps (stdlib only) | M2 Pro, 32GB (MLX) | ~30 min | $0 (local) |

Training uses FP16 mixed precision on CUDA. On Apple Silicon with MLX, training runs in FP32 with lazy evaluation.

### Device Detection

CUDA GPU -> CPU. MPS is not used (memory leak issues). MLX is selected explicitly via `--backend mlx`.

## MLX Training Backend

```
poule train --backend mlx --db <index.db> --vocab <coq-vocabulary.json> --output <model/> <traces.jsonl>
```

An alternative training backend using Apple's MLX framework for Apple Silicon's unified memory architecture.

### Why MLX Instead of PyTorch MPS

PyTorch's MPS backend has known memory leak issues (open as of PyTorch 2.7+). MLX was designed for unified memory from scratch -- no memory leaks, predictable memory usage.

### MLX TacticClassifier

Architecturally identical to the PyTorch version:

```
Input: input_ids [B, seq_len], attention_mask [B, seq_len]  (mx.array)
  |-- mlx.nn.TransformerEncoder (num_hidden_layers layers, 768 hidden, 12 heads)
  |-- Mean pooling (attention-masked)
  |-- mlx.nn.Linear(768, num_classes)
  |-- Output: logits [B, num_classes] (mx.array)
```

Default `num_hidden_layers` is 6 (matching PyTorch). Layer dropping initialization applies the same layer selection from CodeBERT weights converted to MLX arrays.

### MLX Training Loop

```python
loss_fn = nn.value_and_grad(model, cross_entropy_loss)
loss, grads = loss_fn(model, input_ids, attention_mask, labels, class_weights)
optimizer.update(model, grads)
mx.eval(model.parameters(), optimizer.state)
```

### Checkpoint Format and Conversion

MLX checkpoints: safetensors format. Converted to PyTorch via `poule convert-weights` for ONNX quantization.

## Hyperparameter Optimization

```
poule tune --db <index.db> --output-dir <hpo-output/> --n-trials 20 <traces.jsonl>
```

Optuna with TPE sampler, maximizing validation accuracy@5.

### Search Space

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| Num hidden layers | Categorical | {4, 6, 8, 12} | 6 |
| Learning rate | Log-uniform | [1e-6, 1e-4] | 2e-5 |
| Batch size | Categorical | {16, 32, 64} | 16 |
| Weight decay | Log-uniform | [1e-4, 1e-1] | 1e-2 |
| Class weight alpha | Uniform | [0.0, 1.0] | 0.5 |
| Label smoothing | Uniform | [0.0, 0.3] | 0.1 |
| SAM rho | Log-uniform | [0.15, 0.3] | 0.15 |

### Pruning

`MedianPruner(n_startup_trials=3, n_warmup_steps=3)`: prunes trials performing below the median of completed trials at the same epoch.

## Evaluation

```
poule evaluate --checkpoint <model.pt> --test-data <test.jsonl> --db <index.db>
```

Computes:

| Metric | Definition |
|--------|------------|
| Accuracy@1 | Fraction of test steps where top-1 prediction matches ground truth |
| Accuracy@5 | Fraction where correct family is in top-5 predictions |
| Per-family precision | For each tactic family, fraction of predictions that are correct |
| Per-family recall | For each tactic family, fraction of true instances correctly predicted |
| Confusion matrix | num_classes x num_classes matrix of prediction counts |

**Deployment thresholds** (advisory):
- Accuracy@1 >= 40%
- Accuracy@5 >= 80%

## Quantization

```
poule quantize --checkpoint <model.pt> --output <tactic-predictor.onnx>
```

1. Export TacticClassifier to ONNX (opset 17+). Output shape: `[B, num_classes]`.
2. Apply dynamic INT8 quantization via ONNX Runtime.
3. Validate: run 100 random inputs through both models, assert predicted labels match on >= 98% of inputs.
4. Write quantized ONNX model.

Also write `tactic-labels.json` alongside the ONNX model: an ordered list of tactic family names mapping class index to family name.

## Data Validation

```
poule validate-training-data <traces.jsonl>
```

| Check | Warning threshold |
|-------|-------------------|
| Missing tactic text in `"s"` records | Any occurrence |
| Total step count | < 10,000 steps |
| Tactic families with < 100 examples | List affected families |
| Dominant family > 30% of all steps | Name the family |
| Unknown record types | Any occurrence |

## Design Rationale

### Why cross-entropy instead of contrastive loss

Tactic prediction is a classification problem, not a retrieval problem. Each proof state maps to exactly one tactic family. Cross-entropy is the standard loss for multi-class classification and is simpler, faster (single forward pass), and more data-efficient than contrastive learning.

### Why head-class undersampling

Class-weighted loss helps the model attend to rare tactics, but does not reduce the sheer number of redundant head-class examples the model sees each epoch. With rewrite (26,950) and apply (24,562) dominating the training set, the model spends most of each epoch on near-identical proof states. Undersampling caps these families at ~2,000 examples, forcing more tail-class exposure per epoch. The literature (see `doc/background/class-imbalance.md`) finds that undersampling is effective when the majority class has high redundancy — which holds here, since proof states within a single tactic family are highly similar. Undersampling and class weighting are complementary: undersampling balances the data distribution, weighting balances the loss gradient.

### Why minority oversampling after undersampling

Undersampling caps dominant families to increase tail-class exposure per epoch, but does not address the remaining imbalance among trainable families. With a cap of 2,000 and a min_count floor of 100, families between 100–500 examples are still 4–20× smaller than capped families. The best model showed 37 families with ≥100 training examples but zero recall — these families have enough unique signal to be trainable, but are drowned out within their category heads. Oversampling to 25% of the cap (500) reduces the maximum ratio to 4:1, which is within the range where class-weighted cross-entropy and SAM can compensate. Simple duplication (random sampling with replacement) is the first approach because it adds no implementation complexity beyond a second data pass; embedding-space interpolation (SMOTE) is a follow-up if duplication causes overfitting (detectable via val–test gap widening).

### Why file-level split

Same rationale as for retrieval: prevents leakage from related proof steps in the same file.

### Why ONNX

Hardware-agnostic INT8 inference without a full PyTorch installation. The classification model's inference is even simpler than retrieval (no FAISS search, just softmax over ~30 classes).
