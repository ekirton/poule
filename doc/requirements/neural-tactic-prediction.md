# Neural Tactic Prediction for Coq/Rocq — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context and initiative sequencing.

Lineage: Depends on Training Data Extraction for `(proof_state, tactic_text)` pairs. Enhances the `suggest_tactics` MCP tool with learned predictions. Independent of Semantic Lemma Search — tactic prediction is a proof assistance capability, not a search channel.

## 1. Business Goals

Students learning Coq need a thought partner who can suggest what tactic to try next and explain *why* it makes sense — linking the suggestion to proof strategy, mathematical intuition, and reference material so the student builds real understanding. Claude fills this role, but needs a signal for which tactics are most promising given the current proof state.

The neural tactic predictor provides that signal. Trained on (proof_state, tactic) pairs from five Coq libraries (stdlib, stdpp, flocq, coquelicot, MathComp), it predicts which tactic family is most likely to make progress. MathComp is included because it provides the SSReflect training signal needed by the dedicated SSReflect category head. CoqInterval is excluded — its specialized interval-arithmetic proof style does not transfer to other libraries (LOOCV showed 64/65 dead families). Claude uses these predictions as a starting point to explain the reasoning behind each suggestion, linking to relevant textbook material and proof techniques as needed.

This is not an automated prover. CoqHammer, Tactician, and similar solvers are mature products that aim to close proof goals without human involvement. The goal here is the opposite: keep the student in the loop, help them build intuition about proof structure, and accelerate learning by offering contextual suggestions with explanations. The model provides the "what to try next" signal; Claude provides the "why" and the pedagogical scaffolding.

**What this initiative does:** Train a tactic family classifier on (proof_state, tactic_text) pairs extracted from five Coq libraries (excluding CoqInterval), and integrate neural predictions into the existing `suggest_tactics` MCP tool. Claude uses these ranked suggestions to offer explained, contextual proof guidance. The classifier predicts which tactic family to apply; argument selection (e.g., which lemma to `apply`) remains a separate concern addressed by the existing rule-based system and premise retrieval in future work.

**What this initiative does not do:** It does not compete with automated provers. It does not add a neural retrieval channel to Semantic Lemma Search. It does not predict full tactic text with arguments (that is a future generation task). It does not replace the rule-based `suggest_tactics` — it enhances it with learned predictions that rank above rule-based fallbacks.

**Success metrics:**
- Top-1 tactic family accuracy >= 40% on a held-out test set of Coq proof steps
- Top-5 tactic family accuracy >= 80% on the same test set
- Inference latency < 50ms on CPU (no GPU required)
- Graceful degradation: `suggest_tactics` works identically without a trained model

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Students learning Coq with Claude as tutor | Explained tactic suggestions that build proof intuition — "try induction here because the goal quantifies over a recursive type" — with links to textbook material | Primary |
| Coq developers using Claude Code | Contextual tactic suggestions during interactive proof development, reducing trial-and-error | Primary |
| AI researchers | A tactic prediction baseline for Coq that can be evaluated, compared, and extended | Secondary |

---

## 3. Competitive Context

Cross-references:
- [AI-assisted theorem proving survey](../background/coq-ai-theorem-proving.md)
- [Neural encoder architectures for premise selection](../background/neural-encoder-architectures-premise-selection.md)

**Tactic prediction systems (comparative baselines):**
- Tactician (Blaauwbroek et al., 2020): k-NN on proof states for Coq, 39% of theorems proved. Requires the Tactician platform; niche adoption.
- Proverbot9001 (Sanchez-Stern et al., 2020): RNN tactic prediction for Coq CompCert, 48% of theorems in 10 minutes. Pinned to older Coq version.
- CoqHammer (Czajka & Kaliszyk, 2018): ATP premise selection + reconstruction, ~40% automation rate. No learned tactic prediction.
- GPT-f (Polu & Sutskever, 2020): Transformer tactic generation for Lean, 56.5% on miniF2F.
- HTPS (Lample et al., 2022): Hyper-tree proof search + tactic generation, 82.6% on miniF2F.
- ReProver (Yang et al., 2023): Retrieval-augmented tactic generation for Lean, 51.2% on LeanDojo benchmark.

**Key research findings informing design:**
- Tactic prediction works well without per-step premise annotations — models learn tactic patterns from proof state structure alone (Tactician, Proverbot9001)
- Small encoder models (82M-125M parameters) are sufficient for formal math tasks (LeanHammer, RocqStar)
- Domain-specific tokenization improves performance 33% for small models (CFR finding)
- Class imbalance is a known challenge: `auto`, `simpl`, `intros` dominate tactic distributions
- SSReflect compound tactics require special handling (MathComp uses a different proof style)

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R6-P0-1 | Train a hierarchical tactic classifier on `(proof_state, tactic_text)` pairs extracted by the Training Data Extraction pipeline, predicting both tactic category and specific tactic family |
| R6-P0-2 | Classify tactics into 8 categories (introduction, elimination, rewriting, hypothesis management, automation, arithmetic, contradiction, ssreflect) with within-category tactic families, covering >99% of extracted proof steps |
| R6-P0-3 | Handle class imbalance via LDAM (label-distribution-aware margin loss) with deferred re-balancing (DRW): class-dependent margin offsets penalize misclassification of rare tactics more heavily, combined with a two-phase training schedule that uses instance-balanced sampling initially and class-balanced sampling for the final training phase |
| R6-P0-16 | Exclude proof structure tokens (`-`, `+`, `*`, `{`, `}`) from training — they are not tactics and are trivially predictable from subgoal count |
| R6-P0-17 | Every tactic maps to a known category via a canonical taxonomy. All 8 categories have dedicated classification heads. |
| R6-P0-4 | Integrate neural predictions into the existing `suggest_tactics` MCP tool, ranking neural predictions above rule-based fallbacks |
| R6-P0-5 | Inference latency < 50ms per proof state on CPU without GPU |
| R6-P0-6 | Support INT8 quantized inference for the classifier model on CPU |
| R6-P0-7 | Achieve top-1 tactic family accuracy >= 40% on a held-out test set |
| R6-P0-8 | Achieve top-5 tactic family accuracy >= 80% on a held-out test set |
| R6-P0-9 | Provide a CLI command to train the tactic classifier from extracted training data |
| R6-P0-10 | Provide a CLI command to evaluate tactic prediction accuracy (accuracy@k, per-family metrics) on a held-out test set |
| R6-P0-11 | Graceful degradation: `suggest_tactics` operates with rule-based suggestions when no trained model is available |
| R6-P0-12 | Model training must complete on a single consumer GPU (<=24GB VRAM), Apple Silicon Mac (>=32GB unified memory) using MLX, or be offloadable to a cloud GPU within a $100 budget |
| R6-P0-13 | Build a closed-vocabulary tokenizer from the indexed library declarations and extracted proof states, replacing the generic BPE tokenizer with one that assigns every Coq identifier its own token ID |
| R6-P0-14 | Provide a CLI command to build the vocabulary from the search index and training data |
| R6-P0-15 | Support training on Apple Silicon Macs using MLX as an alternative to PyTorch, producing checkpoints convertible to PyTorch format for ONNX inference |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R6-P1-1 | Provide a training data validation step that checks extracted `(proof_state, tactic_text)` pairs for completeness, tactic family distribution, and class imbalance before training |
| R6-P1-7 | Provide a CLI command to collapse per-library training data into a single merged file with normalized tactic families mapped to the canonical taxonomy, so that the collapsed output can be regenerated with different parameters without modifying the original extraction output |
| R6-P1-2 | Report training metrics (loss curves, validation accuracy@k) during and after training |
| R6-P1-3 | Provide automated hyperparameter optimization that searches over training hyperparameters (learning rate, batch size, class weight exponent) to maximize validation accuracy@5, with early pruning |
| R6-P1-4 | Normalize SSReflect compound tactics for classification: handle `move=>`, `apply/`, `rewrite !term`, and other SSReflect-specific syntax |
| R6-P1-5 | Report per-family precision and recall in evaluation, identifying which tactic families the model predicts well vs. poorly |
| R6-P1-6 | Support fine-tuning the pre-trained classifier on a user's project-specific extracted data |
| R6-P1-8 | Cap dominant tactic families in the training split to a configurable maximum number of examples per family, reducing head-class redundancy and increasing tail-class exposure per epoch |
| R6-P1-9 | Provide a leave-one-library-out cross-validation mode across vanilla-Coq libraries (excluding MathComp and CoqInterval) that holds out each library in turn as the test set, training on the remaining libraries, to diagnose whether library-level data leakage is the bottleneck for generalization |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R6-P2-1 | Predict full tactic text with arguments (generative model or retrieval+template), not just tactic family |
| R6-P2-2 | Combine tactic family prediction with premise retrieval: predict the tactic family, then retrieve argument candidates for tactics that take lemma arguments (`apply`, `rewrite`, `exact`) |
| R6-P2-3 | Support proof search by iterating tactic prediction: predict -> execute -> predict until the goal is closed or a depth limit is reached |
| R6-P2-4 | Collect prediction telemetry (suggestions accepted/rejected) to enable future model improvement |

---

## 5. Scope Boundaries

**In scope:**
- Training a tactic family classifier on Coq proof trace data
- MLX training backend for Apple Silicon Macs with weight conversion to PyTorch
- Integrating neural tactic predictions into the existing `suggest_tactics` MCP tool
- CLI tools for training, evaluation, and vocabulary building
- CPU-based INT8 quantized inference (no GPU required at inference time)
- Evaluation framework for tactic prediction accuracy

**Out of scope:**
- Adding a neural retrieval channel to Semantic Lemma Search (the original premise selection approach is deprecated due to insufficient training data)
- Full tactic text generation with arguments (P2 future work)
- Automated proof search using tactic prediction (P2 future work)
- Training data extraction (covered by Training Data Extraction initiative)
- GPU hosting infrastructure for inference
- IDE plugin development
- Web interface
