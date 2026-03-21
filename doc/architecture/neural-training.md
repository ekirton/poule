# Neural Training Pipeline

Technical design for the training, evaluation, fine-tuning, and quantization pipeline for the neural premise selection model.

**Feature**: [Model Training CLI](../features/model-training-cli.md), [Pre-trained Model](../features/pre-trained-model.md)

---

## Component Diagram

```
Extracted training data (JSON Lines)
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

## Data Loading

### Input Format

The training pipeline consumes JSON Lines files produced by the Training Data Extraction pipeline. Each line is an ExtractionRecord containing per-step proof states and premise annotations.

The data loader extracts `(proof_state, premises_used)` pairs from the ExtractionRecord's step sequence. Each ExtractionStep contains the proof state (goals and hypotheses) *after* the step's tactic was applied, plus the premises used by that tactic. Step 0 is the initial state with no tactic. The training pair for a tactic at step k uses the proof state from step k-1 (the state *before* the tactic) and the premises from step k:

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

| Corpus size | GPU requirement | Estimated wall time | Estimated cost |
|-------------|----------------|---------------------|----------------|
| 10K pairs (stdlib only) | Any 16GB+ GPU | ~2 hours | <$10 |
| 50K pairs (stdlib + MathComp) | 24GB GPU (A6000/4090) | ~8 hours | $50–100 |
| 100K+ pairs (multi-project) | 24GB GPU (A6000/4090) | ~16 hours | $100–200 |

Training uses mixed precision (FP16) with gradient accumulation to fit within 24GB VRAM at batch size 256.

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
| Total pair count | < 5,000 pairs |
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
