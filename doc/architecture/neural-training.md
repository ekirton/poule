# Neural Training Pipeline

Technical design for the training, evaluation, fine-tuning, and quantization pipeline for the neural premise selection model.

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
  │ poule train / poule fine-tune
  ▼
┌──────────────────────────────────────────────────────────┐
│                  Training Pipeline                         │
│                                                           │
│  ┌────────────────┐  ┌───────────────┐  ┌──────────────┐ │
│  │ Data Loader    │  │ Bi-Encoder    │  │ Loss         │ │
│  │                │  │               │  │ Computation  │ │
│  │ Read JSONL     │  │ Shared-weight │  │              │ │
│  │ Parse (state,  │  │ encoder       │  │ Masked       │ │
│  │  premises)     │  │ Mean pooling  │  │ contrastive  │ │
│  │ Hard negative  │  │ 768-dim out   │  │ (InfoNCE)    │ │
│  │  sampling      │  │               │  │ τ = 0.05     │ │
│  └───────┬────────┘  └───────┬───────┘  └──────┬───────┘ │
│          │                   │                  │         │
│          └───────────────────┴──────────────────┘         │
│                          │                                │
│                          │ checkpoint                     │
│                          ▼                                │
│              Model Checkpoint (.pt)                       │
│                          │                                │
│                          │ poule quantize                 │
│                          ▼                                │
│              INT8 ONNX Model (.onnx)                      │
└──────────────────────────────────────────────────────────┘
  │                              │
  │ poule evaluate               │ poule compare
  ▼                              ▼
Evaluation Report            Comparison Report
(R@1, R@10, R@32, MRR)     (neural vs. symbolic vs. union)
```

## Vocabulary Building

```
poule build-vocabulary --db <index.db> --data <traces.jsonl> --output <coq-vocabulary.json>
```

Constructs a closed-vocabulary tokenizer that maps every Coq identifier to a unique integer token ID. This replaces CodeBERT's generic BPE tokenizer, which fragments Coq identifiers into 3–9 subword tokens. With a closed vocabulary, every identifier is exactly 1 token. See `coq-vocabulary.md` for the full design rationale.

### Sources

The vocabulary is built from two sources:

1. **Search index** (`index.db`) — all fully-qualified declaration names from the `declarations` table. This is the authoritative source for premise identifiers: every name in the index becomes a vocabulary entry.

2. **Serialized proof states** from the training data — scanning the JSONL extraction output captures hypothesis variable names (`n`, `m`, `H`, `H0`, `x`, `y`, `IHn'`) and any syntax tokens that appear in the model's actual input distribution.

### Fixed Token Sets

In addition to corpus-extracted tokens, the vocabulary includes fixed token sets that are always present regardless of input data:

| Category | Examples | Count |
|----------|----------|-------|
| Special tokens | `[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]` | 5 |
| Punctuation / delimiters | `(`, `)`, `{`, `}`, `[`, `]`, `:`, `;`, `,`, `.`, `\|`, `@`, `!`, `?`, `_`, `'`, `#`, `=`, `+`, `-`, `*`, `/`, `<`, `>`, `~` | ~25 |
| SSReflect tacticals | `/=`, `//`, `//=`, `=>`, `->`, `<-` | 6 |
| Scope delimiters | `%N`, `%Z`, `%R`, `%Q`, `%positive`, `%type` | 6 |
| Unicode math symbols | `∀`, `∃`, `→`, `←`, `↔`, `⊢`, `≤`, `≥`, `≠`, `≡`, `∧`, `∨`, `¬`, `⊆`, etc. | 31 |
| Greek letters | `α`–`ω`, `Γ`–`Ω` | 33 |
| Digits | `0`–`9` | 10 |

### Construction Procedure

1. Initialize the vocabulary with the 5 special tokens at IDs 0–4.
2. Add all fixed token sets (punctuation, tacticals, scope delimiters, Unicode, Greek, digits).
3. Read all declaration names from `index.db` — each name becomes a vocabulary entry.
4. Scan the JSONL training data: for each ExtractionRecord, serialize the proof states and split on whitespace. Collect all unique tokens not already in the vocabulary.
5. Apply NFC Unicode normalization to all token strings before insertion.
6. Assign sequential integer IDs (starting after the fixed tokens) to all collected tokens.
7. Write the vocabulary as a JSON object mapping token strings to integer IDs.

### Output Format

```json
{
  "[PAD]": 0,
  "[UNK]": 1,
  "[CLS]": 2,
  "[SEP]": 3,
  "[MASK]": 4,
  "∀": 5,
  "→": 6,
  ":": 7,
  "nat": 8,
  "Nat.add_comm": 9,
  ...
}
```

### Expected Size

~15,500 tokens: ~15,000 library identifiers, ~200 variable names, ~200 syntax/keyword/tactic tokens, 64 Unicode/Greek symbols, 5 special tokens.

### Tokenization at Inference

Tokenization is a whitespace split followed by O(1) dictionary lookup per token. The procedure:

1. Apply NFC Unicode normalization to the input text
2. Split on whitespace
3. Look up each token in the vocabulary dict → token ID (or `[UNK]` ID for unknown tokens)
4. Prepend `[CLS]`, append `[SEP]`
5. Pad or truncate to `max_length=512`

No regex pre-tokenizer. No subword search.

### Embedding Layer Integration

The closed vocabulary replaces CodeBERT's 50,265-token BPE vocabulary with ~15,500 tokens. The BiEncoder model reinitializes its embedding layer on construction:

1. Load CodeBERT's transformer layers (layers 1–12) with pretrained weights.
2. Create a new `nn.Embedding(vocab_size, 768)` sized to the closed vocabulary.
3. For tokens that overlap with CodeBERT's original vocabulary (digits, punctuation, common English words like `nat`, `list`, `bool`), copy the pretrained embedding vector.
4. For Coq-specific tokens (`Nat.add_comm`, `ssreflect`, `∀`), initialize randomly (normal distribution, σ = 0.02).

CodeBERT's 12 transformer layers retain their full pretrained weights — only the embedding layer is partially cold. Contrastive fine-tuning on ~15,000+ training pairs provides sufficient signal for the new embeddings to converge.

### CoqTokenizer

A lightweight tokenizer class wraps the vocabulary JSON for use by all pipeline components (trainer, evaluator, quantizer, inference encoder):

- Loads the vocabulary JSON file on construction.
- `encode(text, max_length=512)` → `(input_ids, attention_mask)` tensors.
- `encode_batch(texts, max_length=512)` → batched `(input_ids, attention_mask)` tensors with padding.
- `vocab_size` property returns the vocabulary size for embedding layer construction.

This replaces `AutoTokenizer.from_pretrained("microsoft/codebert-base")` throughout the pipeline.

## Data Loading

### Input Format

The training pipeline consumes JSON Lines files produced by the Training Data Extraction pipeline. Each line has a `record_type` field — one of `campaign_metadata`, `proof_trace`, `extraction_error`, or `extraction_summary`. The data loader filters to `proof_trace` records, each of which is an ExtractionRecord containing per-step proof states and premise annotations. Non-`proof_trace` records are skipped.

The data loader extracts `(proof_state, premises_used)` pairs from each ExtractionRecord's step sequence. Each ExtractionStep contains the proof state (goals and hypotheses) *after* the step's tactic was applied, plus the premises used by that tactic. Step 0 is the initial state with no tactic. The training pair for a tactic at step k uses the proof state from step k-1 (the state *before* the tactic) and the premises from step k:

```
For each ExtractionRecord:
  For step_index k = 1 to len(steps) - 1:
    proof_state = serialize_goals(steps[k-1].goals)   (pretty-printed text of goals and hypotheses)
    premises_used = [p.name for p in steps[k].premises if p.kind != "hypothesis"]
    If premises_used is non-empty:
      Emit (proof_state, premises_used) pair
```

**Proof state serialization**: The structured goal list (Goal objects with type and hypotheses) is serialized to a single text string by pretty-printing each goal's type and hypotheses, joined by newlines. This produces the same pretty-printed Coq text format that the encoder was designed to consume.

**Hypothesis filtering**: Local hypotheses (`kind: "hypothesis"`) are excluded from `premises_used` because they are proof-internal bindings that do not correspond to entries in the premise corpus (the SQLite declarations table). Including them would produce positive labels that can never be retrieved, degrading training quality.

Steps where all premises are local hypotheses (empty `premises_used` after filtering) are skipped — they provide no training signal for retrieval. Steps with no premises at all (e.g., `reflexivity`, `assumption`) are also skipped.

### Train/Validation/Test Split

The dataset is split by source file, not by individual pair. All pairs from the same .v file go into the same split. This prevents data leakage from related proofs in the same file.

| Split | Fraction | Purpose |
|-------|----------|---------|
| Train | 80% of files | Model training |
| Validation | 10% of files | Early stopping, hyperparameter selection |
| Test | 10% of files | Final evaluation (never used during training) |

File assignment to splits is deterministic: sort files by fully qualified path, then assign by position modulo 10 (files at positions 8, 9 → validation and test respectively, others → train).

### Premise Corpus

The full premise corpus is the set of all declarations in the indexed library. During training, premise declarations are read from the same SQLite index database used by the retrieval pipeline:

```
For each declaration in the index:
  premise_text = declarations.statement
  premise_id = declarations.id
  premise_name = declarations.name
```

This ensures the training corpus exactly matches the declarations that will be retrieved at inference time.

## Training

### Objective: Masked Contrastive Loss

Following LeanHammer's masked contrastive loss (InfoNCE variant with premise masking):

```
For a batch of B proof states {s_1, ..., s_B}:
  Each s_i has positive premises P_i = {p_i1, p_i2, ...}
  Each s_i has hard negatives N_i = {n_i1, n_i2, n_i3}

  For each (s_i, p_ij) positive pair:
    Candidates = {p_ij} ∪ N_i ∪ {all p_kl for k ≠ i, unless p_kl ∈ P_i}
                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                   Masking: if a premise is positive for s_i,
                                   it is excluded from the negative set for s_i

    loss_ij = -log( exp(sim(s_i, p_ij) / τ) / Σ_c exp(sim(s_i, c) / τ) )

  L = mean over all (i, j)
```

Temperature: τ = 0.05 (following LeanHammer — sharp temperature forces fine-grained discrimination).

**Why masked contrastive**: Premises like `Nat.add_comm` appear in hundreds of proofs. Without masking, these premises would appear as negatives for proof states where they are actually relevant, generating false negative signal. The mask eliminates this by excluding any premise that is positive for the current proof state from the negative set.

### Hard Negative Mining

For each proof state s_i, 3 hard negatives are sampled from the **accessible but unused** premise set:

```
accessible_premises(s_i) = all premises that are in scope for the theorem
                           containing s_i (respecting dependency ordering)
used_premises(s_i) = P_i (the positive set)
hard_negative_pool = accessible_premises(s_i) \ used_premises(s_i)
N_i = sample(hard_negative_pool, k=3)
```

**Accessibility computation**: Accessibility is approximated from the dependency graph. A premise p is accessible to theorem t if p appears in the transitive closure of t's file dependencies. This is an approximation — the true Coq accessibility check is more fine-grained (respecting `Require Import` chains), but file-level approximation is sufficient for negative sampling.

**Fallback**: When the dependency graph is not available (no `dependencies` table or incomplete extraction), negatives are sampled uniformly from the full premise corpus. This reduces hard negative quality but allows training to proceed.

### Hyperparameters

| Parameter | Value | Source |
|-----------|-------|--------|
| Batch size | 256 proof states | LeanHammer |
| Learning rate | 2e-5 | Standard for fine-tuning BERT-class encoders |
| Weight decay | 1e-2 | Standard |
| Temperature τ | 0.05 | LeanHammer |
| Hard negatives per state | 3 | LeanHammer (B⁻ = 3) |
| Max sequence length | 512 tokens | Standard; truncate longer expressions |
| Training epochs | 20 | Early stopping on validation R@32 |
| Early stopping patience | 3 epochs | Stop if validation R@32 does not improve for 3 consecutive epochs |

### Training Hardware

| Corpus size | Hardware | Estimated wall time | Estimated cost |
|-------------|----------|---------------------|----------------|
| 10K pairs (stdlib only) | Any 16GB+ GPU | ~2 hours | <$10 |
| 10K pairs (stdlib only) | M2 Pro, 32GB (MPS) | ~7 hours | $0 (local) |
| 50K pairs (stdlib + MathComp) | 24GB GPU (A6000/4090) | ~8 hours | $50–100 |
| 50K pairs (stdlib + MathComp) | M2 Pro, 32GB (MPS) | ~30 hours | $0 (local) |
| 100K+ pairs (multi-project) | 24GB GPU (A6000/4090) | ~16 hours | $100–200 |

Training uses mixed precision (FP16) with gradient accumulation to fit within 24GB VRAM at batch size 256. On Apple Silicon (MPS), training runs in FP32 without AMP — the unified memory architecture eliminates the CPU↔GPU transfer bottleneck, partially compensating for the lack of mixed-precision speedup.

### Device Detection

The training pipeline selects compute devices in priority order: CUDA GPU → Apple MPS → CPU. Mixed precision (AMP with GradScaler) is used only on CUDA; MPS and CPU use FP32. This is a shared utility used by both training and evaluation.

## Hyperparameter Optimization

```
poule tune --db <index.db> --output-dir <hpo-output/> --n-trials 20 <traces.jsonl>
```

Automated search over training hyperparameters to maximize validation Recall@32.

### Framework

Optuna with TPE (Tree-structured Parzen Estimator) sampler. Optuna was chosen over Ray Tune for single-machine training:

- **Lightweight**: ~10 MB, pure Python, no background processes or object store. Ray's worker/scheduler architecture and 2–4 GB object store are designed for distributed multi-GPU setups and provide no benefit on a single machine.
- **Sample-efficient**: TPE adapts the search space based on observed results, converging faster than random search for the ~20-trial budgets realistic on sequential single-machine execution.
- **Pruning**: Built-in `MedianPruner` observes per-epoch validation Recall@32 and kills trials performing below the median of completed trials. A bad trial that would otherwise run 20 epochs can be pruned after 3–5, saving 75–85% of wasted compute.
- **Crash recovery**: SQLite storage backend persists every completed trial. If the process is interrupted, the study resumes seamlessly.
- **Apple Silicon native**: No CUDA dependency. Works with MPS and CPU backends.

### Search Space

| Parameter | Type | Range | Fixed default | Rationale |
|-----------|------|-------|---------------|-----------|
| Learning rate | Log-uniform | [1e-6, 1e-4] | 2e-5 | Highest-impact hyperparameter for BERT fine-tuning |
| Temperature τ | Log-uniform | [0.01, 0.2] | 0.05 | LeanHammer value; Coq's identifier structure may warrant different sharpness |
| Batch size | Categorical | {64, 128, 256} | 256 | Affects effective learning rate and memory pressure; discrete due to gradient accumulation |
| Weight decay | Log-uniform | [1e-4, 1e-1] | 1e-2 | Standard AdamW regularization range |
| Hard negatives per state | Integer | [1, 5] | 3 | LeanHammer uses 3; fewer reduces batch complexity, more provides richer signal |

**Fixed (not tunable):** `max_seq_length` (512, architectural), `embedding_dim` (768, CodeBERT architecture), `max_epochs` (20, early stopping handles actual duration), `early_stopping_patience` (3, interacts poorly with pruning if also tuned — two competing stopping mechanisms).

### Pruning Strategy

`MedianPruner(n_startup_trials=3, n_warmup_steps=3)`:

- **n_startup_trials=3**: The first 3 trials run to completion without pruning, establishing a baseline distribution for the pruner. Without this, the pruner has no reference data and cannot make meaningful comparisons.
- **n_warmup_steps=3**: Within each trial, the first 3 epochs are immune to pruning. Early epochs produce noisy validation metrics as the model is still warming up; pruning on epoch-1 metrics would kill promising configurations that start slowly.

Interaction with early stopping: The trainer's `EarlyStoppingTracker` (patience=3) and Optuna's `MedianPruner` operate independently. The pruner kills trials that are bad relative to *other trials*; early stopping kills epochs within a trial that have stopped improving. A trial can be pruned by Optuna even if early stopping has not triggered (the trial is improving, but too slowly relative to others).

### Integration with Training Loop

The tuner reuses the existing `BiEncoderTrainer` without modifying the training loop. Integration is through an **epoch callback**:

1. `_train_impl()` accepts an optional `epoch_callback(epoch, val_recall)` parameter.
2. After each epoch's validation, the callback is invoked (if provided).
3. The Optuna objective passes a callback that calls `trial.report(val_recall, epoch)` and then `trial.should_prune()`.
4. If pruning is triggered, the callback raises `optuna.TrialPruned`, which propagates up through the training loop (only `RuntimeError` for OOM is caught in the inner loop).
5. Optuna catches `TrialPruned` in the study runner and records the trial as pruned.

This design adds 3 lines to `_train_impl()` and leaves all existing callers (`train()`, `fine_tune()`, CLI commands) unchanged.

### Study Persistence

Trials persist in a SQLite database at `<output_dir>/hpo-study.db`. Each trial's checkpoint is saved to `<output_dir>/trial-<N>.pt`. On study completion, the best trial's checkpoint is copied to `<output_dir>/best-model.pt`.

The `--resume` flag reloads an existing study and continues from the last completed trial. This is critical for long-running sequential HPO on development machines where interruptions (laptop sleep, crash) are expected.

### Memory Management

On a 32GB unified memory machine, each trial consumes ~3–4 GB (model + optimizer + gradients + data). Between trials:

1. The trainer, model, optimizer, and all tensors go out of scope when the objective function returns.
2. `gc.collect()` forces Python garbage collection.
3. `torch.mps.empty_cache()` releases the MPS device allocator's cache (Apple Silicon equivalent of `torch.cuda.empty_cache()`).

Sequential execution (one trial at a time) is the only safe mode — parallel trials would exceed available memory.

### Hardware Estimates

| Corpus size | Hardware | Est. time per trial | 20 trials (with pruning) |
|-------------|----------|---------------------|--------------------------|
| 10K pairs (stdlib) | M2 Pro, 32GB | ~20 min | ~4–5 hours |
| 10K pairs (stdlib) | 24GB GPU (A6000/4090) | ~6 min | ~1–2 hours |
| 50K pairs (stdlib + MathComp) | M2 Pro, 32GB | ~90 min | ~18–24 hours |
| 50K pairs (stdlib + MathComp) | 24GB GPU (A6000/4090) | ~25 min | ~5–6 hours |

Pruning typically eliminates ~40% of trial compute, reducing wall time by that factor from the naive n_trials × time_per_trial estimate.

## Fine-Tuning

Fine-tuning reuses the same training loop with a pre-trained checkpoint as initialization:

```
poule fine-tune --checkpoint <pre-trained.pt> --data <project_traces.jsonl> --output <fine-tuned.pt>
```

Differences from training from scratch:
- **Lower learning rate**: 5e-6 (1/4 of training LR) to avoid catastrophic forgetting
- **Fewer epochs**: 10 maximum (smaller dataset converges faster)
- **No early stopping patience change**: Still 3 epochs

The fine-tuned model's premise corpus is the union of the pre-trained library (stdlib + MathComp) and the user's project declarations. Embeddings for all declarations are recomputed from the fine-tuned encoder on the next index rebuild.

## Evaluation

### Retrieval Metrics

```
poule evaluate --checkpoint <model.pt> --test-data <test.jsonl> --db <index.db>
```

Computes:

| Metric | Definition |
|--------|------------|
| Recall@1 | Fraction of test states where at least one correct premise is in top-1 |
| Recall@10 | Fraction of test states where at least one correct premise is in top-10 |
| Recall@32 | Fraction of test states where at least one correct premise is in top-32 |
| MRR | Mean Reciprocal Rank of the first correct premise |
| Mean premises per state | Average number of ground-truth premises per test state |
| Evaluation latency | Mean time per query (encode + search) |

### Neural vs. Symbolic Comparison

```
poule compare --checkpoint <model.pt> --test-data <test.jsonl> --db <index.db>
```

Runs the same test set through three retrieval configurations:

1. **Neural-only**: Top-32 from the neural channel
2. **Symbolic-only**: Top-32 from the existing pipeline (WL + MePo + FTS5)
3. **Union**: Top-32 from the union of neural and symbolic results, re-ranked by RRF

Reports:

| Metric | Description |
|--------|-------------|
| R@32 per configuration | The primary comparison metric |
| Relative improvement | (union R@32 - symbolic R@32) / symbolic R@32 |
| Overlap | Percentage of correct retrievals found by both channels |
| Neural exclusive | Correct retrievals found only by neural |
| Symbolic exclusive | Correct retrievals found only by symbolic |

**Deployment gate**: The comparison command emits warnings if:
- Neural R@32 < 50% (model quality threshold)
- Union relative improvement < 15% (complementary value threshold)

These thresholds are advisory — the model can still be deployed, but warnings indicate it may not provide sufficient value to justify the added latency and complexity.

## Quantization

```
poule quantize --checkpoint <model.pt> --output <model.onnx>
```

Converts a trained PyTorch checkpoint to INT8 ONNX:

1. Export model to ONNX format (opset 17+)
2. Apply dynamic INT8 quantization via ONNX Runtime quantization tools
3. Validate: run 100 random encodings through both full-precision and quantized models, assert max cosine distance < 0.02
4. Write quantized ONNX model to output path

The validation step ensures quantization did not introduce unacceptable distortion. If the distance threshold is exceeded, quantization fails with an error.

## Data Validation

```
poule validate-training-data <traces.jsonl>
```

Checks extracted data before committing to a training run:

| Check | Warning threshold |
|-------|-------------------|
| Empty premise lists | > 10% of total pairs |
| Malformed fields (missing state, missing premises) | Any occurrence |
| Degenerate premise distribution (single premise accounts for > 5% of all occurrences) | Any occurrence |
| Total pair count | < 10,000 pairs |
| Unique premise count | < 1,000 unique premises |

Validation is instant (single pass over the JSONL file) and catches the most common data quality issues before GPU time is committed.

## Design Rationale

### Why file-level train/test split

Splitting by individual (state, premise) pairs would leak information: nearby tactic steps in the same proof share context, and the model could memorize proof-specific patterns rather than learning generalizable retrieval. File-level splits ensure the test set contains proofs the model has never seen during training. LeanDojo and LeanHammer both use file-level or theorem-level splits for the same reason.

### Why τ = 0.05

Sharp temperatures force the model to make fine-grained distinctions between similar premises. At τ = 0.05, the softmax distribution is very peaked — only the most similar premises receive significant probability mass. LeanHammer uses τ = 0.05; RGCN uses τ = 0.0138. Both achieve strong results. A higher temperature (e.g., τ = 0.1) produces smoother distributions that are easier to optimize but less discriminative. The aggressive temperature is justified because premise selection is a precision-critical task — retrieving the wrong lemma wastes proof search budget.

### Why 3 hard negatives rather than more

LeanHammer uses B⁻ = 3 and achieves state-of-the-art results. More negatives per state increase batch memory usage and training time without proportional quality gains — the masked contrastive loss already provides in-batch negatives from other proof states in the batch (up to B × |P| additional negatives). The hard negatives provide the most informative training signal; the in-batch negatives provide volume.

### Why ONNX rather than TorchScript

ONNX Runtime provides hardware-agnostic INT8 inference with consistent performance across platforms (Linux, macOS, Apple Silicon). TorchScript requires PyTorch at inference time, adding ~2GB to the deployment footprint. The ONNX model is self-contained and can be loaded by lightweight inference runtimes without a full ML framework installation.

### Why dynamic quantization rather than static

Dynamic INT8 quantization calibrates activation ranges at inference time, avoiding the need for a calibration dataset. Static quantization produces slightly faster inference but requires a representative calibration set and additional tooling. For a 100M model where single-item inference is already <10ms with dynamic quantization, the complexity of static quantization is not justified.

### Why Optuna rather than Ray Tune

Ray Tune (with ASHA or BOHB schedulers) is designed for distributed multi-GPU clusters. On a single machine running one sequential trial at a time, Ray's worker/scheduler architecture, 2–4 GB object store reservation, and heavy dependency footprint (grpc, protobuf, aiohttp) provide no benefit. Optuna is 10 MB, pure Python, uses TPE for sample-efficient Bayesian search, and persists trials in SQLite for crash recovery — the right tool for single-machine HPO on consumer hardware.

### Why MedianPruner rather than SuccessiveHalving

Optuna's `MedianPruner` compares each trial's intermediate value (epoch-level validation R@32) against the median of completed trials at the same step. `SuccessiveHalvingPruner` pre-allocates a fixed bracket structure and requires knowing the total trial count upfront. MedianPruner adapts dynamically as trials complete, which is better suited to sequential execution where the user may interrupt and resume the study. The warmup period (3 epochs) avoids premature pruning on noisy early-training metrics.
