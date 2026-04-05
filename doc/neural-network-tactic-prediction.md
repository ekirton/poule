# Tactic Prediction from Proof States

## Status

**Active development.** Replaces the abandoned neural premise selection approach (see [neural-network-search.md](neural-network-search.md) for why that failed). The extraction pipeline captures 140,358 (proof_state, tactic) steps across 136,936 unique states — 40x more training data than was available for premise retrieval.

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

The top 20 families cover ~80% of all steps. However, 2,011 families have fewer than 50 examples — these rare families will need grouping or exclusion during training.

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
| `num_hidden_layers` | Categorical | {4, 6, 8, 12} | 6 |
| `learning_rate` | Log-uniform | [1e-6, 1e-4] | 2e-5 |
| `batch_size` | Categorical | {16, 32, 64} | 16 |
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

## Implementation Scope

| Phase | Effort | Status |
|-------|--------|--------|
| Phase 1: Emit tactic records | Small | **Done** — 140K steps extracted, validated |
| Phase 2: Tactic classifier | Medium | **In progress** — model, training pipeline, HPO tuner, and evaluator implemented; supports PyTorch (CUDA/CPU) and MLX (Apple Silicon) backends |
| Phase 3: Argument retrieval | Medium | Blocked on Phase 2 |
| Phase 4: MCP integration | Small | Blocked on Phase 2 or 3 |

## Relationship to Other Work

- **Complements**: premise retrieval (tactic prediction selects the verb, retrieval selects the noun)
- **Supersedes**: cross-prover transfer training (uses existing Coq data instead of requiring Lean datasets)
- **Enables**: proof search / auto-completion in the MCP proof session tools
- **Blocked by**: nothing — extraction data (140K steps) and vocabulary (158K tokens) are ready
