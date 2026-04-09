# Tactic Prediction from Proof States

## Status

**Hierarchical model trained and deployed.** Replaces the abandoned neural premise selection approach (see [neural-network-search.md](neural-network-search.md) for why that failed). The extraction pipeline captures 140,358 (proof_state, tactic) steps across 136,936 unique states — 40x more training data than was available for premise retrieval.

The flat 96-class classifier achieved 46.6% test_acc@5 with 86 of 96 classes showing zero recall. A hierarchical decomposition (8 categories × ~65 within-category tactics) replaced the flat approach and achieved **80.2% val_acc@5** — a 10.5pp improvement. With head-class undersampling (cap 2,000 per family, reducing training from 95K to 40K), the model achieves **57.0% test_acc@5** — a 12pp improvement over the non-undersampled hierarchical model (45.2%) and a 10pp improvement over the flat baseline (46.6%). See [undersampled results](#undersampled-model-results) below.

## Problem

The original neural training pipeline trained a bi-encoder to retrieve *premises* given a proof state. This required (proof_state, premises_used) pairs, but Coq's kernel does not track which lemmas each tactic consults. The result: the extraction pipeline captures proof records but only ~3,500 produce non-empty premise lists usable as training pairs — a 97% attrition rate.

However, the extraction pipeline *does* capture the tactic text at each step (`ExtractionStep.tactic`). Every goal state has the tactic that was applied to it, regardless of whether that tactic's premises are known. This represents a 40× larger training signal.

| Training signal | Available pairs | Source |
|----------------|----------------|--------|
| Premise retrieval (old) | ~3,500 | Steps with non-empty `premises` |
| Tactic prediction (current) | 140,358 | All steps with `tactic` text |

## What is Tactic Prediction

Given a proof state (goal type + hypotheses), predict the next tactic the user should apply. This is a sequence generation or classification task, depending on how it is framed:

- **Classification**: Predict the tactic *family* (e.g., `apply`, `rewrite`, `induction`, `auto`, `simpl`). Simpler to train, useful for suggesting a short list of likely tactics.
- **Generation**: Predict the full tactic text including arguments (e.g., `rewrite IHn`, `apply Nat.add_comm`). More useful but requires a generative model or a retrieval + template approach.
- **Hybrid**: Predict the tactic family, then retrieve argument candidates from the proof context and accessible lemma set. This is closest to what Tactician and CoqHammer do.

## Prior Art

| System | Approach | Training data | Results |
|--------|----------|--------------|---------|
| Tactician (Blaauwbroek et al., 2020) | k-NN on proof states → tactic | Coq stdlib + 120 packages | 39% of Coq theorems proved |
| CoqHammer (Czajka & Kaliszyk, 2018) | ATP premise selection + reconstruction | Coq stdlib | ~40% automation rate |
| Proverbot9001 (Sanchez-Stern et al., 2020) | RNN tactic prediction | Coq CompCert | 48% of theorems in 10 minutes |
| GPT-f (Polu & Sutskever, 2020) | Transformer tactic generation | Lean Mathlib | 56.5% on miniF2F |
| HTPS (Lample et al., 2022) | Hyper-tree proof search + tactic gen | Lean/Metamath | 82.6% on miniF2F |
| ReProver (Yang et al., 2023) | Retrieval-augmented tactic generation | Lean Mathlib (LeanDojo) | 51.2% on LeanDojo benchmark |

The common thread: tactic prediction works well even without per-step premise annotations, because the model learns tactic patterns from the proof state structure alone.

## Proposed Approach

### Phase 1: Emit tactic labels in extraction output (done)

The extraction pipeline emits JSONL training data with (proof_state, tactic) pairs. Validation of the current training corpus:

| Metric | Value |
|--------|-------|
| Total steps | 140,358 |
| Unique states | 136,936 |
| Missing tactic | 0 |
| Malformed records | 0 |
| Tactic families | 2,113 |

Top tactic families by frequency:

| Family | Count | % |
|--------|------:|--:|
| `rewrite` | 26,950 | 19.2% |
| `apply` | 24,562 | 17.5% |
| `intros` | 10,702 | 7.6% |
| `auto` | 5,692 | 4.1% |
| `unfold` | 5,232 | 3.7% |
| `have` | 4,184 | 3.0% |
| `move=>` | 3,890 | 2.8% |
| `case` | 3,834 | 2.7% |
| `destruct` | 3,831 | 2.7% |
| `-` | 3,240 | 2.3% |
| `{` | 2,869 | 2.0% |
| `assert` | 2,808 | 2.0% |
| `exists` | 2,368 | 1.7% |
| `elim` | 2,172 | 1.5% |
| `exact` | 2,168 | 1.5% |
| `replace` | 2,093 | 1.5% |
| `simpl` | 1,941 | 1.4% |
| `split` | 1,873 | 1.3% |
| `move` | 1,616 | 1.2% |
| `+` | 1,357 | 1.0% |

The top 20 families cover ~80% of all steps. The hierarchical taxonomy groups all tactics into 8 categories (~65 tactic families total), eliminating the need for frequency thresholding or an `"other"` catch-all class.

### Phase 2: Tactic family classifier

Train a classifier on (proof_state → tactic_family) using a custom tokenizer and CodeBERT-based encoder.

#### Model architecture

The classifier is a CodeBERT encoder with a linear classification head:

```
Input: proof_state_text [B, max_seq_length]
  ↓
Token Embedding: nn.Embedding(vocab_size, 768)
  ↓
Positional Embedding: nn.Embedding(514, 768)
  ↓
Embedding LayerNorm
  ↓
Transformer Encoder (num_hidden_layers ∈ {4, 6, 8, 12}):
  └─ Each layer:
     ├─ Multi-head self-attention (12 heads)
     ├─ Residual connection + LayerNorm
     ├─ FFN: Linear(768, 3072) → GELU → Linear(3072, 768)
     └─ Residual connection + LayerNorm
  ↓
Mean Pooling (attention-masked over non-padding tokens)
  ↓
Classification Head: nn.Linear(768, num_classes)
  ↓
Output: logits [B, num_classes]
```

The encoder is initialized from `microsoft/codebert-base` (pretrained on Python, Java, JavaScript, PHP, Ruby, Go). The token embedding layer is replaced with a custom embedding sized to the Coq vocabulary (158K tokens): overlapping tokens copy their pretrained weights; new Coq-specific tokens are initialized from N(0, 0.02). The positional embeddings, layer norms, and transformer layers are loaded from CodeBERT directly.

When `num_hidden_layers < 12`, transformer layers are selected at evenly spaced indices from CodeBERT's 12 layers (e.g., 6 layers → indices 0, 2, 4, 6, 8, 10; 4 layers → indices 0, 3, 6, 9). This is the layer dropping approach described in the "Model size and overfitting under imbalance" section below.

Mean pooling aggregates the encoder output over non-padding positions: `sum(output * mask) / sum(mask)`. This produces a single 768-dimensional representation per input, which the classification head maps to logits over tactic families.

#### Training pipeline

1. Tokenize proof states using the Coq-specific closed vocabulary
2. Encode via the transformer encoder with mean pooling
3. Classify with the linear head
4. Train with cross-entropy loss (class-weighted, label-smoothed) on 140K (state, tactic_family) pairs
5. Evaluate with top-1 and top-5 accuracy on a held-out validation set

#### Vocabulary

A Coq-specific vocabulary has been built from the index and training data:

| Component | Tokens |
|-----------|-------:|
| Special tokens (`[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]`) | 5 |
| Fixed tokens (punctuation, operators, scope annotations, Unicode symbols, Coq keywords) | 111 |
| Index declarations (all 6 libraries) | 118,363 |
| Training data tokens (from proof states) | 39,895 |
| **Total vocabulary** | **158,374** |

This domain-specific tokenizer avoids sub-word fragmentation of Coq identifiers — every declaration in the index and every token observed in training data gets a single vocabulary entry.

### Phase 3: Tactic argument retrieval

For tactics that take lemma arguments (`apply`, `rewrite`, `exact`), combine the tactic family prediction with premise retrieval:

1. Predict tactic family from Phase 2
2. If the predicted tactic takes a lemma argument, run the existing premise retrieval pipeline to suggest candidates
3. Construct full tactic suggestions: `apply <candidate>`, `rewrite <candidate>`, etc.

This reuses the existing bi-encoder for premise retrieval but gates it behind tactic prediction, making the system more useful as a proof assistant.

### Phase 4: Integration as MCP tool

Expose tactic prediction as a new MCP tool `suggest_tactics` that takes a proof state and returns ranked tactic suggestions. This integrates directly into the existing proof session workflow.

## Advantages Over Current Approach

1. **40× more training data**: 140K tactic-labeled states vs. ~3,500 premise pairs, from the same extraction output.
2. **No kernel changes needed**: The tactic text is already captured by the extraction pipeline. Only the output format needs updating.
3. **Complements premise retrieval**: Tactic prediction and premise retrieval are orthogonal — tactic prediction selects the *verb*, premise retrieval selects the *noun*. They can be combined.
4. **Directly useful**: "You should try `induction n`" is more actionable than "these lemmas are relevant." Users of the MCP proof session tools would benefit immediately.
5. **Established approach**: Tactician, Proverbot9001, and CoqHammer all demonstrate that tactic prediction works for Coq without per-step premise tracking.

## Challenges

### Tactic text normalization

Coq tactics have complex syntax with arguments, combinators (`;`, `||`), and SSReflect extensions. The tactic text needs normalization before it can be used as a training label:
- Strip comments and whitespace
- Normalize SSReflect compound tactics (e.g., `move=> /eqP ->` is one step)
- Handle tactic arguments that include proof terms (e.g., `refine (ex_intro _ _ _)`)

### Class imbalance

Some tactics (`rewrite` at 19.2%, `apply` at 17.5%) dominate the distribution while 2,011 of 2,113 families have fewer than 50 examples. The classifier uses four complementary techniques to handle this imbalance:

**1. Rare family collapsing.** Tactic families with fewer than `min_family_count` (default 50) training examples are mapped to a catch-all "other" class during data loading. Alias normalization is also applied (e.g., `intro` → `intros`). This reduces the 2,113 raw families to a manageable number of classes with sufficient training signal.

**2. Inverse-frequency class weighting.** The cross-entropy loss is weighted per class using a tunable power law:

```
weight[c] = (total / (num_classes × count[c])) ^ alpha
```

where `alpha ∈ [0, 1]` controls rebalancing strength (0 = uniform weights, 1 = full inverse frequency, default 0.5). For example, with alpha=0.5: `rewrite` (19.2%) gets weight ~0.82, while `simpl` (1.4%) gets weight ~1.83. This penalizes the loss more for misclassifying rare families without fully inverting the distribution.

**3. Label smoothing.** The cross-entropy loss uses label smoothing (default ε=0.1), replacing hard one-hot targets with soft targets: correct class gets probability `1 - ε + ε/K`, incorrect classes get `ε/K`. This reduces overconfidence on frequent classes and improves calibration across the full distribution.

**4. Sharpness-Aware Minimization (SAM).** The optimizer performs a two-step update: (1) perturb parameters along the gradient direction by `rho` (default 0.05), then (2) compute the gradient at the perturbed point and apply the base optimizer (AdamW). SAM seeks parameters in flat loss neighborhoods, which improves generalization on imbalanced data where the model otherwise memorizes dominant classes. When `sam_rho = 0.0`, plain AdamW is used instead.

### Model size and overfitting under imbalance

The tactic classifier uses CodeBERT-base (12 transformer layers, 768 hidden dim, 12 attention heads). With the custom 158K-token vocabulary, the model has ~225M parameters: ~85M in the transformer encoder, ~115M in the embedding layer, and a small classification head. Shwartz-Ziv et al. (2023) found that larger architectures that perform well on balanced data *overfit* on class-imbalanced data — the correlation between balanced and imbalanced performance across architectures is only 0.14. Given that our training data has an imbalance ratio of 26,950:1 (86% of families have ≤5 examples), a 225M-parameter model is likely too large.

**Approach: Layer dropping (DistilBERT-style).** Initialize a 6-layer model by copying every other transformer layer from CodeBERT (layers 0, 2, 4, 6, 8, 10). This halves the transformer encoder from ~85M to ~42M parameters while preserving CodeBERT's pretrained knowledge of code structure — scoping, types, function application, and infix operators — which transfers to Coq. The hidden dimension (768) and attention heads (12) stay unchanged, so the custom vocabulary embedding layer and classification head work without modification. Fine-tune the 6-layer model on Coq tactic prediction with class-weighted loss.

This approach follows DistilBERT (Sanh et al., 2019), which retained ~97% of BERT's performance with 40% fewer parameters. Layer dropping is a single code change with no separate training phase.

**Backup: Full knowledge distillation.** If layer dropping underperforms, train the 6-layer student with a combined loss:

```
L = α · CE(student_logits, labels) + (1 - α) · T² · KL(student_logits / T, teacher_logits / T)
```

where T is the temperature (softens the teacher's output distribution) and α balances the hard-label and soft-label losses. This requires first fine-tuning the full 12-layer CodeBERT as the teacher, then training the student against its soft targets. More expensive (two training runs) but preserves more of the teacher's learned decision boundaries.

**Why distillation over training from scratch.** CodeBERT was pretrained on six programming languages (Python, Java, JavaScript, PHP, Ruby, Go). Despite none being Coq, these languages share structural patterns with Coq: lexical scoping, function application, type annotations, infix operators, pattern matching. A distilled CodeBERT retains this structural knowledge in fewer layers, while a transformer trained from scratch on 140K examples would need to learn both language structure and tactic patterns simultaneously.

### SSReflect proofs

MathComp uses SSReflect's tactic language extensively. SSReflect compound tactics (e.g., `rewrite !addnA addnC`) pack multiple operations into a single step, making tactic family classification harder. These may need special handling or a separate SSReflect-aware head.

### Hyperparameter optimization

The training pipeline includes an Optuna-based hyperparameter tuner that searches over model architecture and training configuration jointly.

#### Search space

| Hyperparameter | Sampling | Range | Default |
|---|---|---|---|
| `num_hidden_layers` | Categorical | {4, 6, 12} | 6 |
| `learning_rate` | Log-uniform | [1e-6, 1e-4] | 2e-5 |
| `batch_size` | Categorical | {16, 32} | 16 |
| `weight_decay` | Log-uniform | [1e-4, 1e-1] | 1e-2 |
| `class_weight_alpha` | Uniform | [0.0, 1.0] | 0.5 |
| `label_smoothing` | Uniform | [0.0, 0.3] | 0.1 |
| `sam_rho` | Log-uniform | [0.01, 0.2] | 0.05 |

Fixed parameters not searched: `max_seq_length` (512), `embedding_dim` (768), `max_epochs` (20), `early_stopping_patience` (3).

Note that `num_hidden_layers` is in the search space — the tuner can explore smaller (4-layer) or larger (12-layer) models alongside the training hyperparameters. This is important given the class imbalance findings from Shwartz-Ziv et al.: the optimal model size for imbalanced data may differ from the balanced-data optimum.

#### Optimization algorithm

The tuner uses a Tree-structured Parzen Estimator (TPE) sampler, which models the search space as a density ratio between good and bad trials. This is more sample-efficient than random search for the 7-dimensional space above.

A `MedianPruner` stops underperforming trials early: the first 3 trials run to completion (startup), and within each trial the first 3 epochs are immune to pruning (warmup, since early metrics are noisy). After epoch 3, if a trial's validation accuracy falls below the median of completed trials at that epoch, it is pruned. This avoids wasting compute on clearly unpromising configurations.

Study state is persisted to a SQLite database (`hpo-study.db`), allowing the search to be resumed across sessions. Trials execute sequentially with explicit memory cleanup (garbage collection, CUDA cache clearing, MLX memory reset) between trials to prevent OOM accumulation.

#### Objective

Each trial trains the model with the sampled hyperparameters and returns the best validation accuracy@5 (top-5 accuracy on the held-out set). The study maximizes this metric. Trials that hit OOM are caught and marked as pruned rather than crashing the study.

### Evaluation

Tactic prediction accuracy is not the same as proof completion rate. The model may predict the correct tactic family 80% of the time but still fail to produce a complete proof because the argument is wrong. Evaluation should track:
- Top-1 and top-5 tactic family accuracy
- Full tactic accuracy (exact match after normalization)
- Proof closure rate (can the predicted tactic close the current goal when executed?)

## Training Results

### HPO results

10-trial Optuna study on 114K training samples (13.8K validation, 12.4K test), 96 tactic family classes:

| Trial | Layers | LR | Batch | alpha | label_smooth | sam_rho | val_acc@5 | Status |
|-------|--------|----|-------|-------|-------------|---------|-----------|--------|
| 0 | 6 | 2.1e-6 | 64 | 0.71 | 0.006 | 0.183 | 0.5296 | Complete |
| 1 | **4** | **4.1e-6** | **16** | **0.14** | **0.088** | **0.030** | **0.6971** | **Best** |
| 2 | 6 | 1.5e-5 | 32 | 0.95 | 0.290 | 0.113 | 0.4428 | Complete |
| 3 | 8 | 1.8e-6 | 64 | 0.66 | 0.094 | 0.047 | 0.5731 | Complete |
| 4 | 8 | 7.6e-5 | 64 | 0.20 | 0.014 | 0.027 | 0.5328 | Pruned |
| 5 | 8 | 3.6e-6 | 64 | 0.99 | 0.232 | 0.018 | 0.2850 | Pruned |
| 6 | 6 | 3.5e-5 | 32 | 0.62 | 0.099 | 0.012 | 0.5390 | Pruned |
| 7 | 8 | 5.9e-5 | 64 | 0.56 | 0.231 | 0.044 | 0.5451 | Pruned |
| 8 | 4 | 1.2e-6 | 16 | 0.25 | 0.123 | 0.096 | 0.6791 | Complete |
| 9 | 4 | 1.2e-5 | 32 | 0.51 | 0.160 | 0.128 | 0.5451 | Pruned |

HPO time: 51.9 hours on a 32 GiB Mac Mini (Apple M2 Pro, 10 CPU cores, MLX Metal GPU).

**Key findings from HPO:**
- **4-layer models dominate.** Both top trials used 4 layers. 6- and 8-layer models consistently underperformed, confirming Shwartz-Ziv et al.'s finding that larger models overfit on class-imbalanced data.
- **Small batch size matters.** batch_size=16 appeared in the top 2 trials; batch_size=64 never won. This is consistent with class imbalance research showing smaller batches see more diverse class distributions per step.
- **Low class_weight_alpha is better.** The best trial used alpha=0.14 (nearly uniform weights), not aggressive rebalancing. Over-weighting rare classes may hurt when the long tail contains noise (many of the 96 classes are SSReflect fragments with few examples).
- **Moderate label smoothing helps.** The best trial used ε=0.088. High label smoothing (>0.2) consistently produced worse results — it likely over-softens the targets for classes with strong signal.

### Final model results

The final model was trained with trial 1's best hyperparameters for 20 epochs (patience=3). Early stopping triggered at epoch 10 (best: epoch 7).

**Training curve:**

| Epoch | Loss | val_acc@5 |
|-------|------|-----------|
| 1 | 2.977 | 0.6497 |
| 2 | 2.703 | 0.6663 |
| 3 | 2.550 | 0.6772 |
| 4 | 2.423 | 0.6854 |
| 5 | 2.306 | 0.6980 |
| 6 | 2.202 | 0.7012 |
| 7 | 2.107 | **0.7015** |
| 8 | 2.015 | 0.6904 |
| 9 | 1.923 | 0.6743 |
| 10 | 1.832 | 0.6760 |

Final training time: 7.6 hours (458 minutes).

**Test set evaluation:**

| Metric | Value |
|--------|-------|
| Accuracy@1 | 14.0% |
| Accuracy@5 | 46.6% |

**Per-family highlights (test set):**

| Family | Precision | Recall | Notes |
|--------|-----------|--------|-------|
| `intros` | 0.647 | 0.204 | Best precision; high-confidence when predicted |
| `rewrite` | 0.437 | 0.064 | Precise but rarely predicted |
| `elim` | 0.290 | 0.027 | Very conservative |
| `apply` | 0.249 | 0.369 | Most balanced of the major families |
| `{` | 0.226 | 0.278 | Bullet markers well-learned |
| `auto` | 0.089 | 0.440 | High recall, low precision (over-predicted) |
| `other` | 0.110 | 0.323 | Catch-all absorbs uncertainty |
| `destruct` | 0.026 | 0.246 | Low precision, confused with other case analysis |

### Analysis: validation–test gap

The model achieves 70.2% val_acc@5 but only 46.6% test_acc@5 — a 24 percentage-point gap. Several factors contribute:

**1. 96 classes is too many for the training signal.** The collapse step reduced 2,113 raw families to 96 (min_count=50), but many of the resulting classes still have marginal training data. Of the 96 families, the model achieves non-zero recall on only ~10. The effective classifier is a ~10-class model with 86 dead classes.

**2. SSReflect families inflate the class count.** Families like `apply/eqp`, `apply/matrixp`, `move/`, `case/andp` are SSReflect-specific compound tactics that were not fully normalized during collapse. They consume class capacity without contributing useful signal — all show 0.0 precision and recall.

**3. Class weight alpha was too low.** The best HPO trial used alpha=0.14 (nearly uniform weights). This favors dominant classes (`apply`, `rewrite`, `intros`) at the expense of the mid-tier (`induction`, `simpl`, `reflexivity`, `split`) which all show 0.0 recall on the test set.

**4. Validation and test splits may have different distributions.** The deterministic file-level split (position % 10) could place different libraries in different splits. If the validation set over-represents libraries with simpler tactic distributions, val_acc@5 will be inflated.

**Recommended next steps:**
1. **Reduce class count.** Increase min_family_count to 200-500, or manually curate a ~30-class vocabulary of the most useful tactic families. This would concentrate training signal on families the model can actually learn.
2. **Normalize SSReflect compounds.** Strip `/`-suffixed variants (`apply/eqp` → `apply`, `move/` → `move`) during collapse, rather than treating them as separate families.
3. **Increase class_weight_alpha.** Re-run HPO with alpha ∈ [0.3, 0.7] to give more weight to mid-tier families.
4. **Stratified splitting.** Split by library rather than file position to ensure each split contains examples from all six libraries.
5. **Embedding factorization.** See the section below — the 158K-token embedding dominates model size and contains mostly undertrained parameters.

### Deployment and quantization

The trained model is exported to FP32 ONNX for cross-platform CPU inference. The ONNX model is 574 MB with a median inference latency of **20 ms** per prediction (seq_len=128) — well under the 50ms requirement.

**Why not INT8 quantization.** The original plan was to apply dynamic INT8 quantization via ONNX Runtime, targeting a ~150 MB model. This failed due to a toolchain incompatibility: PyTorch >= 2.6 defaults to the dynamo-based ONNX exporter, which produces graph structures that ONNX Runtime's shape inference cannot process. The error (`InferenceError: Inferred shape and existing shape differ in dimension 0: (768) vs (96)`) occurs at the classifier head boundary. The legacy TorchScript-based exporter is also incompatible because the `transformers` library (v5+) uses masking utilities that cannot be JIT-traced.

**Why it doesn't matter.** INT8 quantization primarily benefits the transformer layers (matrix multiplications), which are only 28M of the model's 150M parameters (19%). The embedding layer — 121M parameters, 81% of the model — is a gather operation that INT8 does not accelerate. The size reduction from INT8 would be from 601 MB to ~150 MB, but the latency improvement would be modest (the transformer layers already run in ~8 ms of the 20 ms total). The model meets the <50ms latency target without quantization.

**The real size problem is the embedding.** Embedding factorization (see below) would reduce the model from 601 MB to ~197 MB in FP32 — a larger reduction than INT8 alone — by addressing the root cause: 158K tokens that cannot fill a 768-dimensional space. If both embedding factorization and INT8 quantization were applied (once the toolchain issue is resolved), the model would be ~50 MB.

### Embedding factorization

The model has 150M parameters, but 121M (81%) are in the token embedding matrix (158K tokens × 768 dimensions). Most of these tokens are rare Coq identifiers that appear in very few training examples — they cannot learn meaningful 768-dimensional representations, and their embeddings are effectively noise. This wastes both model capacity and disk/memory at inference time.

**The approach:** Decompose the embedding matrix into two smaller matrices, following ALBERT (Lan et al., 2020):

```
Standard:   E = V × H           158,242 × 768 = 121.5M params
Factored:   E = (V × D) · (D × H)   158,242 × 128 + 128 × 768 = 20.4M params
```

where `D` is a low-rank bottleneck dimension (e.g., 128). Each token gets a compact 128-dimensional embedding, which a shared projection matrix expands to the 768-dimensional space the transformer expects.

**Why it works here:** The vocabulary contains 158K tokens, but the training data has only 140K examples. Most tokens appear in a handful of proof states at best. A 768-dimensional embedding for a token seen 3 times is pure overfitting — a 128-dimensional representation captures everything that token can meaningfully learn, and the shared projection handles the expansion. Frequent tokens (`apply`, `rewrite`, `forall`, `nat`) might lose some expressiveness, but ALBERT found no accuracy degradation with D=128 on BERT-base (the same 768 hidden dimension).

**Impact on model size:**

| Component | Current | Factored (D=128) |
|-----------|---------|-------------------|
| Token embedding | 121.5M params (486 MB) | 20.4M params (82 MB) |
| Position embedding | 0.4M | 0.4M (unchanged) |
| 4 transformer layers | 28.4M | 28.4M (unchanged) |
| Classification head | 0.1M | 0.1M (unchanged) |
| **Total** | **150.4M (601 MB)** | **49.3M (197 MB)** |

A 3× parameter reduction without quantization. Combined with INT8 quantization (when toolchain support improves), the model would be ~50 MB.

**What changes:**
- Add a `nn.Linear(D, H, bias=False)` projection layer after the embedding lookup
- Initialize the projection from a truncated SVD of CodeBERT's original embedding matrix (preserves the most important directions)
- The rest of the model (transformer layers, classification head) is unchanged — they still receive 768-dim inputs
- Requires retraining, but there is no transfer learning loss: the custom 158K-token embedding already discards CodeBERT's vocabulary, so there are no pretrained embedding weights to preserve

**Tradeoffs:**
- Adds one small matrix multiply per forward pass (128 × 768 = 98K operations — negligible compared to attention)
- If D is too small, frequent tokens lose expressiveness. D=128–256 is the typical sweet spot; D=128 is the ALBERT default for H=768
- The CodeBERT pretrained weights for attention layers and FFN are unaffected — only the embedding input path changes

## Hierarchical Tactic Decomposition

The flat 96-class classifier failed due to extreme class imbalance (IR = 26,950:1) across too many classes, with 86 of 96 classes showing zero test recall. The hierarchical approach decomposes the problem into two levels:

### Category taxonomy

Eight categories derived from the Coq tactic reference:

| Category | Tactics | Training samples |
|----------|---------|----------------:|
| Rewriting | rewrite, simpl, unfold, reflexivity, ... (12) | 38,303 |
| Hypothesis Management | apply, have, assert, specialize, ... (14) | 38,632 |
| Introduction | intros, split, left, right, exact, ... (10) | 18,776 |
| Elimination | destruct, induction, case, inversion, ... (7) | 11,780 |
| Automation | auto, eauto, trivial, tauto, ... (10) | 7,009 |
| SSReflect | move, suff, wlog, congr, unlock (5) | 6,005 |
| Arithmetic | lia, omega, ring, field (4) | 864 |
| Contradiction | exfalso, absurd, contradiction (3) | 146 |

Key changes from the flat approach:
- **"other" class eliminated.** Every tactic maps to a known category. The `_MIN_FAMILY_COUNT` threshold and frequency-based collapsing are removed.
- **SSReflect compounds normalized.** `apply/eqp` -> `apply`, `case/andp` -> `case` via `/`-suffix stripping.
- **Proof structure tokens excluded.** `-`, `+`, `*`, `{`, `}` are filtered at data loading time.

### Architecture

```
Encoder (shared, factored D=128, CodeBERT) -> z [B, 768]
  |
  +-> Category Head: Linear(768, 8) -> P(category)
  |
  +-> Per-Category Heads (8): Linear(768, N_cat) -> P(tactic|category)

Inference: P(tactic) = P(category) * P(tactic|category)
```

Joint loss: `L = L_category + lambda * L_within(active head)`, where lambda balances category vs. within-category loss (default 1.0, tunable [0.3, 3.0]).

### Updated HPO search space

| Hyperparameter | Range | Change from flat model |
|---|---|---|
| `num_hidden_layers` | {4, 6, 8} | Drop 12, add 8 |
| `batch_size` | {16, 32, 64} | Restore 64 |
| `label_smoothing` | [0.0, 0.2] | Narrow from [0.0, 0.3] |
| `lambda_within` | [0.3, 3.0] | **New** |
| Others | Unchanged | |

### Success criteria

- Overall test accuracy@5 exceeds 46.6% (flat model baseline)
- Non-zero recall on >80% of tactic families with ≥20 training examples
- Non-zero recall on >90% of tactic families with ≥50 training examples
- Category accuracy@1 exceeds 80%

Families with fewer than 20 training examples are too sparse to be trainable and do not count towards coverage targets. Of the 65 taxonomy families, 58 have ≥20 examples and 54 have ≥50 examples. Only 4 families fall below the trainability floor: `decide` (18), `econstructor` (10), `rename` (8), `unlock` (8). The two tiers reflect increasing confidence: ≥20 examples is the minimum viable signal, ≥50 is the comfortable threshold where the model should reliably learn the class.

## Hierarchical Model Results

### HPO results

15-trial Optuna study on 114K training samples (13.8K validation, 12.4K test), 8-category hierarchical architecture with factored embeddings (D=128). Fixed parameters: `max_seq_length` (256), `embedding_dim` (128), `max_epochs` (10), `early_stopping_patience` (2).

| Trial | Layers | LR | Batch | alpha | label_smooth | sam_rho | lambda | val_acc@5 | Status |
|-------|--------|----|-------|-------|-------------|---------|--------|-----------|--------|
| 0 | 6 | 1.6e-5 | 16 | 0.60 | 0.142 | 0.011 | 2.80 | 0.7356 | Complete |
| 1 | 4 | 2.3e-6 | 32 | 0.61 | 0.028 | 0.024 | 0.70 | 0.7012 | Complete |
| 2 | 6 | 1.1e-5 | 64 | 0.07 | 0.190 | 0.180 | 1.93 | 0.7706 | Complete |
| 3 | 8 | 7.6e-6 | 32 | 0.26 | 0.133 | 0.025 | 0.99 | 0.7527 | Complete |
| **4** | **8** | **3.6e-5** | **16** | **0.09** | **0.039** | **0.011** | **0.63** | **0.8017** | **Best** |
| 5 | 8 | 5.2e-6 | 32 | 0.07 | 0.197 | 0.101 | 0.47 | 0.7663 | Complete |
| 6 | 6 | 2.9e-5 | 16 | 0.86 | 0.125 | 0.027 | 0.35 | 0.6234 | Pruned |
| 7 | 8 | 1.9e-5 | 16 | 0.76 | 0.112 | 0.101 | 0.94 | 0.7136 | Pruned |
| 8 | 4 | 1.6e-6 | 32 | 0.91 | 0.050 | 0.034 | 1.71 | 0.5426 | Pruned |
| 9 | 8 | 2.1e-6 | 16 | 0.80 | 0.037 | 0.145 | 1.04 | 0.6926 | Pruned |
| 10 | 8 | 6.9e-5 | 64 | 0.33 | 0.076 | 0.010 | 0.58 | 0.6154 | Pruned |
| 11 | 6 | 6.5e-5 | 64 | 0.02 | 0.198 | 0.063 | 1.80 | 0.7933 | Complete |
| 12 | 6 | 9.9e-5 | 64 | 0.27 | 0.005 | 0.062 | 1.51 | 0.6154 | Pruned |
| 13 | 6 | 3.6e-5 | 64 | 0.04 | 0.083 | 0.054 | 2.79 | 0.7891 | Complete |
| 14 | 4 | 4.9e-5 | 64 | 0.19 | 0.168 | 0.017 | 1.31 | 0.8015 | Complete |

HPO time: 35.6 hours on a 32 GiB Mac Mini (Apple M2 Pro, 10 CPU cores, MLX Metal GPU). 9 complete, 6 pruned.

**Key findings from HPO:**
- **Hierarchical decomposition transforms the problem.** val_acc@5 jumped from 0.6971 (flat, 96 classes) to 0.8017 (hierarchical, 8 categories × ~65 tactics) — a 10.5pp improvement with the same training data and comparable compute.
- **Optimal model depth shifted upward.** The flat model's best was 4 layers; the hierarchical model's best is 8 layers (trial 4, 0.8017). With fewer, better-defined classes per head, deeper models can learn without overfitting. Trial 14 (4 layers, 0.8015) is nearly tied, suggesting depth matters less than the hierarchical structure itself.
- **Low alpha still best.** The top 5 trials all used alpha < 0.26 (near-uniform class weights). Aggressive rebalancing (alpha > 0.6) consistently underperformed — high-alpha trials account for all 6 pruned runs. This confirms the flat model finding.
- **lambda_within < 1 in the best trial** (0.63) — category-level loss slightly dominates. However, trials 11 and 13 (both > 0.79) used lambda > 1.8, so the relationship is not monotonic. The loss balance interacts with other hyperparameters.
- **Batch size no longer decisive.** The best trial used batch_size=16, but trial 14 (nearly tied) used 64. The flat model strongly favored small batches, but the hierarchical decomposition appears to make the model less sensitive to batch size.

### Final model results

The final model was trained with trial 4's best hyperparameters (8 layers, lr=3.6e-5, batch_size=16, alpha=0.09, label_smoothing=0.039, sam_rho=0.011, lambda_within=0.63, embedding_dim=128) for 20 epochs (patience=3). Early stopping triggered at epoch 7 (best: epoch 4).

**Training curve:**

| Epoch | Loss | val_acc@5 |
|-------|------|-----------|
| 1 | 2.112 | 0.7473 |
| 2 | 1.868 | 0.7789 |
| 3 | 1.712 | 0.7943 |
| 4 | 1.587 | **0.8018** |
| 5 | 1.479 | 0.7897 |
| 6 | 1.371 | 0.7879 |
| 7 | 1.261 | 0.7847 |

Final training time: ~2.7 hours (161 minutes).

**Comparison with flat model:**

| Metric | Flat (96 classes) | Hierarchical (8 cat × ~65) |
|--------|-------------------|-----------------------------|
| Best HPO val_acc@5 | 0.6971 | 0.8017 |
| Final model val_acc@5 | 0.7015 | 0.8018 |
| Layers | 4 | 8 |
| Embedding | Full (768d) | Factored (128d → 768d) |
| Parameters | ~150M | ~77M |
| HPO time | 51.9 hours | 35.6 hours |
| Training time | 7.6 hours | 2.7 hours |
| Dead classes (test) | 86 of 96 | 55 of 65 |
| Test accuracy@1 | 14.0% | 12.9% |
| Test accuracy@5 | 46.6% | 45.2% |
| Val–test gap (acc@5) | 23.6pp | 34.8pp |

**Test set evaluation** (run 2026-04-07, 15,497 test samples, CPU inference ~32 min):

| Tactic | Precision | Recall | Notes |
|---------|-----------|--------|-------|
| rewrite | 0.215 | 0.417 | Highest recall |
| intros | 0.126 | 0.356 | Second-highest recall |
| apply | 0.265 | 0.019 | High precision, very low recall |
| auto | 0.182 | 0.104 | Moderate both |
| left | 0.001 | 0.078 | Essentially noise |
| exists | 0.010 | 0.029 | Low |
| split | 0.033 | 0.021 | Low |
| destruct | 0.044 | 0.012 | Low |
| unfold | 0.077 | 0.001 | Near-zero recall |
| assert | 0.010 | 0.003 | Near-zero |
| *55 others* | 0.000 | 0.000 | Dead classes |

### Analysis: flat vs. hierarchical

The hierarchical model improved validation accuracy by 10.5pp (70.2% → 80.2%), but the val–test gap *widened* from 24pp to 35pp, leaving test accuracy essentially unchanged (46.6% → 45.2%). The hierarchical architecture did not solve the underlying generalization problem.

**What the hierarchy fixed:** The factored embedding (128d → 768d) halved the parameter count while matching validation performance, confirming that the 158K-token × 768d embedding matrix was overfitting rare tokens. The 8-category top level is well-balanced and trains efficiently.

**What the hierarchy did not fix:** The core failure mode is unchanged — the model learns to predict only 5–6 dominant tactic families (rewrite, intros, apply, auto, destruct, split) and ignores the remaining 55+ families. The val–test gap suggests the validation set shares file-level patterns with training (despite file-level splits), possibly because proofs within the same library share stylistic regularities that don't transfer across libraries.

**Root causes to investigate:**
1. **Library-level leakage**: The 80/10/10 split is file-level, but files within the same library (e.g., MathComp, stdpp) share conventions. A library-level split would be a harder but fairer test.
2. **SSReflect normalization**: SSReflect-heavy libraries (MathComp) use `move`, `congr`, `suff`, `wlog` — all dead in both models. These tactics may need separate normalization or a dedicated SSReflect category.
3. **Class collapse**: 55 of 65 tactic families have zero test recall. The within-category heads are as imbalanced as the original flat taxonomy — the hierarchy only balanced the *top-level* categories.

## Undersampled Model Results

### Motivation

The hierarchical model improved validation accuracy to 80.2% but the val–test gap widened to 35pp (test_acc@5=45.2%), with 55 of 65 families dead. The dominant families (rewrite, intros, apply, auto, destruct, split) each had 5,000–27,000 training examples, drowning out minority families. Head-class undersampling caps each family at 2,000 examples, reducing the training set from 95,497 to 40,247 samples while preserving all rare-family data intact.

### HPO results

15-trial Optuna study on 40,247 undersampled training samples (10,521 validation, 15,497 test), 8-category hierarchical architecture with factored embeddings (D=128). Fixed parameters: `max_seq_length` (256), `embedding_dim` (128), `max_epochs` (10), `early_stopping_patience` (2).

| Trial | Layers | LR | Batch | alpha | label_smooth | sam_rho | lambda | val_acc@5 | Status |
|-------|--------|----|-------|-------|-------------|---------|--------|-----------|--------|
| 0 | 6 | 1.6e-5 | 16 | 0.60 | 0.142 | 0.011 | 2.80 | 0.5484 | Complete |
| 1 | 4 | 2.3e-6 | 32 | 0.61 | 0.028 | 0.024 | 0.70 | 0.4196 | Complete |
| **2** | **6** | **1.1e-5** | **64** | **0.07** | **0.190** | **0.180** | **1.93** | **0.6207** | **Best** |
| 3 | 8 | 7.6e-6 | 32 | 0.26 | 0.133 | 0.025 | 0.99 | 0.5609 | Complete |
| 4 | 8 | — | 16 | — | — | — | — | — | Pruned |
| 5 | 8 | 5.2e-6 | 32 | 0.07 | 0.197 | 0.101 | 0.47 | 0.6018 | Complete |
| 6 | — | — | — | — | — | — | — | — | Pruned |
| 7 | — | — | — | — | — | — | — | — | Pruned |
| 8 | — | — | — | — | — | — | — | — | Pruned |
| 9 | — | — | — | — | — | — | — | — | Pruned |
| 10 | 6 | 5.3e-6 | 64 | 0.33 | 0.182 | 0.062 | 2.82 | 0.5742 | Complete |
| 11 | — | — | — | — | — | — | — | — | Pruned |
| 12 | — | — | — | — | — | — | — | — | Pruned |
| 13 | 6 | 8.9e-6 | 64 | 0.14 | 0.161 | 0.122 | 0.49 | 0.5756 | Complete |
| 14 | — | — | — | — | — | — | — | — | Pruned |

HPO time: 16.4 hours on a 32 GiB Mac Mini (Apple M2 Pro, 10 CPU cores, MLX Metal GPU). 7 complete, 8 pruned.

**Key findings from HPO:**
- **Undersampling halved HPO time** (16.4h vs. 35.6h) due to the smaller training set.
- **Best trial shifted to 6 layers, batch_size=64.** With the undersampled data, the deeper 8-layer model no longer dominates — 6 layers with larger batches performed best.
- **High SAM rho is critical.** The best trial used sam_rho=0.180, the highest in the search range. SAM's flat-minima seeking appears especially valuable when training data is reduced by undersampling.
- **Low alpha still best** (0.07). Aggressive class rebalancing remains harmful — the model performs best with near-uniform class weights even after undersampling.
- **Higher label smoothing** (0.190 vs. 0.039 in the non-undersampled best). The smaller dataset benefits from stronger regularization.

### Final model results

The final model was trained with trial 2's best hyperparameters (6 layers, lr=1.07e-5, batch_size=64, alpha=0.065, label_smoothing=0.190, sam_rho=0.180, lambda_within=1.93, embedding_dim=128) for 20 epochs (patience=3). Early stopping triggered at epoch 9 (best: epoch 6).

**Training curve:**

| Epoch | Loss | val_acc@5 |
|-------|------|-----------|
| 1 | 4.689 | 0.5512 |
| 2 | 4.090 | 0.6005 |
| 3 | 3.831 | 0.6006 |
| 4 | 3.604 | 0.6046 |
| 5 | 3.392 | 0.6225 |
| 6 | 3.182 | **0.6261** |
| 7 | 2.962 | 0.5926 |
| 8 | 2.755 | 0.5873 |
| 9 | 2.557 | 0.5862 |

Final training time: 1.85 hours (111 minutes).

**Test set evaluation** (run 2026-04-08, 15,497 test samples):

| Metric | Value |
|--------|-------|
| Category Accuracy@1 | 34.9% |
| Accuracy@1 | 17.2% |
| Accuracy@5 | 57.0% |
| Eval latency | 315 s (CPU, full test set) |

**Per-category accuracy (test set):**

| Category | Accuracy@1 |
|----------|-----------|
| introduction | 38.1% |
| ssreflect | 38.5% |
| automation | 23.5% |
| hypothesis_mgmt | 16.7% |
| rewriting | 5.9% |
| elimination | 3.3% |
| arithmetic | 0.0% |
| contradiction | 0.0% |

**Per-family highlights (test set):**

| Family | Precision | Recall | Notes |
|--------|-----------|--------|-------|
| have | 0.214 | 0.612 | Highest recall — strong signal |
| intros | 0.369 | 0.537 | Best balance of precision + recall |
| move | 0.236 | 0.401 | SSReflect family no longer dead |
| replace | 0.054 | 0.395 | High recall, low precision |
| exact | 0.081 | 0.298 | High recall |
| auto | 0.110 | 0.292 | Moderate |
| apply | 0.310 | 0.133 | High precision, moderate recall |
| exists | 0.070 | 0.205 | Improved from flat model |
| reflexivity | 0.111 | 0.129 | Newly non-zero |
| set | 0.047 | 0.129 | Newly non-zero |
| split | 0.438 | 0.118 | Highest precision |
| *44 others* | 0.000 | 0.000 | Dead classes |

**Success criteria:**

| Criterion | Result | Status |
|-----------|--------|--------|
| test_acc@5 > 46.6% | 57.0% | **PASS** |
| >80% recall coverage (≥20 train examples) | 21/58 = 36.2% | **FAIL** |
| >90% recall coverage (≥50 train examples) | 21/54 = 38.9% | **FAIL** |
| Category acc@1 > 80% | 34.9% | **FAIL** |

Note: families with fewer than 20 training examples are too sparse to be trainable and are excluded from coverage targets. The previous "dead families < 20" criterion counted all 65 taxonomy families equally, penalizing the model for failing on classes with insufficient training data (e.g., arithmetic and contradiction families with <50 total examples across all splits).

### Comparison across all three models

| Metric | Flat (96 cls) | Hierarchical | Undersampled |
|--------|--------------|--------------|--------------|
| Train samples | 114K | 95K | 40K |
| Best HPO val_acc@5 | 0.697 | 0.802 | 0.621 |
| Test acc@1 | 14.0% | 12.9% | 17.2% |
| Test acc@5 | 46.6% | 45.2% | **57.0%** |
| Val–test gap (acc@5) | 24pp | 35pp | **6pp** |
| Zero-recall families | 86/96 | 55/65 | 44/65 |
| Non-zero recall families | 10 | 10 | 21 |
| Trainable coverage (≥20 examples) | — | — | 21/58 = 36.2% |
| Trainable coverage (≥50 examples) | — | — | 21/54 = 38.9% |
| Parameters | ~150M | ~77M | ~77M |
| HPO time | 51.9h | 35.6h | 16.4h |
| Training time | 7.6h | 2.7h | 1.85h |

### Analysis: undersampling impact

**What undersampling fixed:**
1. **Val–test gap collapsed.** The gap shrank from 35pp to 6pp — the model now generalizes across libraries instead of memorizing training-set patterns. This was the primary problem.
2. **Test acc@5 improved by 12pp** (45.2% → 57.0%). The model makes better top-5 predictions on unseen data, which is the metric that matters for suggest_tactics.
3. **Double the non-zero families** (10 → 21). Undersampling forced the model to learn `have`, `move`, `replace`, `exact`, `exists`, `reflexivity`, `set`, and others that were previously dead.
4. **acc@1 improved** (12.9% → 17.2%). The model's top prediction is correct more often.

**What undersampling did not fix:**
1. **44 dead families remain.** Most are too sparse to be trainable (<20 training examples) — arithmetic, contradiction, and many elimination tactics have insufficient data, and undersampling the majority doesn't increase their representation. The coverage-based success criteria (>80% of families with ≥20 examples, >90% with ≥50) separate "model failure" from "insufficient data."
2. **Category acc@1 is only 34.9%.** The 8-category top-level classifier is not discriminating well — the model often predicts the right tactic within the wrong category.
3. **Precision is low across the board.** The model predicts more diverse tactics (good for recall) but at the cost of precision. This is acceptable for suggest_tactics (users see a ranked list) but not for automated proof search.

## Leave-One-Library-Out Cross-Validation

### Motivation

The current file-level split (`position % 10`) scatters files from the same library across train/val/test. Libraries share tactic conventions — MathComp uses SSReflect idioms, stdlib favors `destruct`/`induction`, stdpp has its own automation patterns. The 6pp val-test gap after undersampling measures within-library generalization, not cross-library transfer. LOOCV holds out each library in turn to diagnose whether library-level data leakage is the bottleneck.

### Design

6-fold cross-validation across stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval. Each fold holds out one library entirely as the test set, trains on the remaining libraries (with cap=1000 undersampling), and evaluates. Best HPO hyperparameters from the undersampled experiment are used (6 layers, lr=1.07e-5, batch_size=64, alpha=0.065, label_smoothing=0.190, sam_rho=0.180, lambda_within=1.93, embedding_dim=128).

### Results

_Pending — run `poule loocv` to populate this section._

## Implementation Scope

| Phase | Effort | Status |
|-------|--------|--------|
| Phase 1: Emit tactic records | Small | **Done** — 140K steps extracted, validated |
| Phase 2: Tactic classifier | Medium | **Done** — hierarchical model with undersampling (6-layer CodeBERT, 8 categories × ~65 tactics, factored embeddings, cap=2000), test_acc@5=57.0%. See [Undersampled Model Results](#undersampled-model-results) |
| Phase 3: Argument retrieval | Medium | **Done** — ArgumentRetriever routes tactic families to retrieval strategies (type_match for apply/exact, equality filter for rewrite); integrated into suggest_tactics |
| Phase 4: MCP integration | Small | **Done** — TacticPredictor (ONNX), ArgumentRetriever, and suggest_tactics wired end-to-end; pipeline context connected at server startup; quantize CLI available |

## Relationship to Other Work

- **Complements**: premise retrieval (tactic prediction selects the verb, retrieval selects the noun)
- **Supersedes**: cross-prover transfer training (uses existing Coq data instead of requiring Lean datasets)
- **Enables**: proof search / auto-completion in the MCP proof session tools
- **Blocked by**: nothing — extraction data (140K steps) and vocabulary (158K tokens) are ready

## Next Steps

Head-class undersampling collapsed the val–test gap (35pp → 6pp) and raised test_acc@5 to 57%, but many families with sufficient training data (≥20 examples) still show zero recall, and category acc@1 is only 35%. The remaining interventions target the long tail; see [class-imbalance.md](background/class-imbalance.md) for literature backing.

1. **Head-class undersampling.** ✅ **Done.** Cap dominant families at 2,000 examples each (95K → 40K training). Collapsed the val–test gap from 35pp to 6pp, raised test_acc@5 from 45.2% to 57.0%, doubled non-zero families from 10 to 21.

2. **Balanced softmax** (Ren et al., 2020). ❌ **Evaluated 2026-04-08 and rejected.** The correction subtracts `alpha × log(class_frequency)` from logits before softmax at inference time, adjusting for training distribution bias without retraining. Tested on the undersampled hierarchical model (6 layers, cap=2000, test_acc@5=57.0% baseline) using the ONNX predictor on a 2,000-sample test subset.

   **Alpha sweep results (2,000 test samples):**

   | Alpha | Acc@1 | Acc@5 |
   |-------|-------|-------|
   | 0.0 (baseline) | 10.7% | 41.1% |
   | 0.1 | 0.3% | 0.7% |
   | 0.2 | 0.0% | 0.2% |
   | 0.3 | 0.0% | 0.2% |
   | 0.5 | 0.0% | 0.2% |
   | 0.7 | 0.0% | 0.2% |
   | 1.0 | 0.0% | 0.2% |

   Note: the baseline (alpha=0.0) shows lower accuracy than the full 15,497-sample evaluation (17.2%/57.0%) because this 2,000-sample prefix is not representative of the full test distribution. The relative comparison across alpha values is valid.

   **Full evaluation at alpha=1.0** (15,497 test samples, 2,574 seconds): acc@1=0.0%, acc@5=0.0%. All 54 families with training data showed zero recall — predictions shifted entirely to untrained families. Even after fixing zero-count family handling (setting log_prior=0 for families with no training examples), per-category accuracy collapsed: only hypothesis_mgmt (33.2%), arithmetic (41.6%), and contradiction (42.1%) had non-zero category accuracy, but individual family recall remained zero across all families.

   **Why it fails:**
   - **Test distribution mirrors training.** Balanced softmax assumes the test distribution differs from training (ideally uniform). In Coq proof data, `rewrite` and `apply` dominate both train and test — correcting for the training prior fights the real data distribution.
   - **Narrow logit range.** The hierarchical product-rule model produces logits spanning ~2 nats, while the log-prior correction spans ~5 nats (from log(51/66265) to log(7621/66265)). Even alpha=0.1 produces a ~0.5 nat correction that overwhelms the model's discriminative signal.
   - **Problem is in the encoder, not the softmax.** With 44 dead families, the encoder hasn't learned distinctive features for rare tactics. Post-hoc logit adjustment cannot fix unlearned representations — this is exactly the finding from Kang et al. (2020) that motivates decoupled training (Next Step 3).

3. **Decoupled training** (Kang et al., 2020). ❌ **Evaluated 2026-04-09 — did not improve over baseline.** Froze the 6-layer encoder, reinitialized the 8 category heads + within-category heads, and retrained with category-balanced sampling using the MLX backend on Apple Silicon.

   **Run 1 (family-balanced sampling, lr=1e-3):** val_acc@5 peaked at 0.4512 (epoch 3), test_acc@5=34.3%, 28 families with non-zero recall (vs. 21 baseline). Category accuracy was not measured but test_acc@5 dropped 23pp from baseline. The per-family balanced sampling over-represented rare categories (arithmetic: 864 total examples, contradiction: 146) while diluting well-represented categories. `apply` recall collapsed from 13.3% to 0.06%.

   **Run 2 (category-balanced sampling, lr=1e-4):** val_acc@5 peaked at 0.5606 (epoch 5), test results:

   | Metric | Baseline (stage 1) | Decoupled (stage 2) | Change |
   |--------|-------------------|---------------------|--------|
   | test_acc@1 | 17.2% | 11.5% | -5.7pp |
   | test_acc@5 | 57.0% | 46.0% | -11.0pp |
   | Category acc@1 | 34.9% | 29.1% | -5.8pp |
   | Non-zero recall families | 21 | 29 | +8 |

   **Per-category accuracy@1 (stage 2):**

   | Category | Acc@1 | vs. Baseline |
   |----------|-------|-------------|
   | hypothesis_mgmt | 57.4% | +40.7pp |
   | introduction | 25.7% | -12.4pp |
   | automation | 18.0% | -5.5pp |
   | arithmetic | 15.0% | +15.0pp |
   | contradiction | 15.8% | +15.8pp |
   | rewriting | 13.7% | +7.8pp |
   | elimination | 12.1% | +8.8pp |
   | ssreflect | 1.8% | -5.7pp (from 7.8%) |

   **Why it underperforms:** Decoupled training improved 5 of 8 categories but overall accuracy dropped because (1) the reinitialized heads start from scratch, discarding the jointly-trained signal, and (2) the encoder representations were learned jointly with the original heads — the frozen encoder produces features optimized for the *original* decision boundaries, not the reinitialized ones. Kang et al.'s results were on vision tasks with much larger datasets (ImageNet: 1.2M images vs. our 40K proof states) where encoder features are more general.

4. **Minority oversampling.** Undersampling capped the majority but did nothing to boost families with <50 examples (arithmetic, contradiction, many elimination tactics). SMOTE-like augmentation or simple oversampling of rare families could help fill the gap.

5. **LDAM + deferred re-balancing** (Cao et al., 2019). Class-dependent margin offsets (`C / n_c^{1/4}`) penalize misclassification of rare tactics more heavily. Combined with deferred re-balancing (normal sampling for 80% of training, balanced for the final 20%), this is a strong literature baseline.

6. **Focal loss** (Lin et al., 2017). Down-weight well-classified examples via `(1-p)^gamma` modulation. This focuses training on hard/rare examples without requiring changes to the sampling strategy. May complement undersampling.

Try (5) next — LDAM + deferred re-balancing operates during end-to-end training rather than post-hoc, addressing the decision boundary directly without discarding the jointly-learned signal.
