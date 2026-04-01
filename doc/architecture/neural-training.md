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

### CoqTokenizer

A lightweight tokenizer class wrapping the vocabulary JSON:
- `encode(text, max_length=512)` -> `(input_ids, attention_mask)` tensors
- `encode_batch(texts, max_length=512)` -> batched tensors with padding
- `vocab_size` property for embedding layer construction

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
3. Take the first whitespace-delimited token
4. Normalize: lowercase, strip trailing punctuation
5. Map aliases (`intro` -> `intros`, etc.)
6. If the family appears fewer than N times in the dataset, map to `other`

Target: ~30 families covering >95% of proof steps.

### Train/Validation/Test Split

Identical to the previous design: file-level split, deterministic by position modulo 10.

| Split | Fraction | Purpose |
|-------|----------|---------|
| Train | 80% of files | Model training |
| Validation | 10% of files | Early stopping |
| Test | 10% of files | Final evaluation |

## Training

### Objective: Class-Weighted Cross-Entropy

```
loss = CrossEntropyLoss(weight=class_weights)(logits, labels)
```

Class weights are computed from inverse frequency to handle the long-tailed tactic distribution:

```
weight[c] = (total_samples / (num_classes * count[c])) ^ alpha
```

where `alpha` controls the strength of rebalancing (default 0.5; tunable via HPO).

### Model Architecture

```
Input: input_ids [B, 512], attention_mask [B, 512]
  |
  |-- CodeBERT encoder (12 layers, 768 hidden, 12 heads)
  |-- Mean pooling (attention-masked)
  |-- nn.Linear(768, num_classes)
  |-- Output: logits [B, num_classes]
```

Single forward pass per batch. No premise encoding, no contrastive pairs, no hard negatives.

### Hyperparameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Batch size | 64 | Larger batches not needed (no in-batch negatives) |
| Learning rate | 2e-5 | Standard for BERT fine-tuning |
| Weight decay | 1e-2 | Standard AdamW |
| Class weight alpha | 0.5 | Moderate inverse-frequency rebalancing |
| Max sequence length | 512 tokens | Standard |
| Training epochs | 20 | Early stopping on validation accuracy@5 |
| Early stopping patience | 3 epochs | Stop if accuracy@5 does not improve |

### Training Hardware

| Corpus size | Hardware | Estimated wall time | Estimated cost |
|-------------|----------|---------------------|----------------|
| 105K steps (all 6 libraries) | Any 16GB+ GPU | ~4 hours | $20-50 |
| 105K steps (all 6 libraries) | M2 Pro, 32GB (MLX) | ~3 hours | $0 (local) |
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
  |-- mlx.nn.TransformerEncoder (12 layers, 768 hidden, 12 heads)
  |-- Mean pooling (attention-masked)
  |-- mlx.nn.Linear(768, num_classes)
  |-- Output: logits [B, num_classes] (mx.array)
```

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
| Learning rate | Log-uniform | [1e-6, 1e-4] | 2e-5 |
| Batch size | Categorical | {32, 64, 128} | 64 |
| Weight decay | Log-uniform | [1e-4, 1e-1] | 1e-2 |
| Class weight alpha | Uniform | [0.0, 1.0] | 0.5 |

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

### Why class-weighted loss

The tactic distribution is heavily long-tailed: `intros`, `apply`, `rewrite`, `simpl`, and `auto` dominate. Without class weighting, the model would achieve reasonable accuracy by always predicting the majority class. Inverse-frequency weighting forces the model to also learn minority tactic families. The alpha exponent controls the strength -- alpha=0 means no weighting, alpha=1 means full inverse frequency.

### Why file-level split

Same rationale as for retrieval: prevents leakage from related proof steps in the same file.

### Why ONNX

Hardware-agnostic INT8 inference without a full PyTorch installation. The classification model's inference is even simpler than retrieval (no FAISS search, just softmax over ~30 classes).
