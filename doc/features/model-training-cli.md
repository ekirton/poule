# Model Training CLI

Command-line tools for training, evaluating, and fine-tuning the neural premise selection model from extracted Coq proof trace data.

**Stories**: [Epic 1: Model Training](../requirements/stories/neural-premise-selection.md#epic-1-model-training), [Epic 2: Model Evaluation](../requirements/stories/neural-premise-selection.md#epic-2-model-evaluation), [Epic 5: Pre-trained Model Distribution](../requirements/stories/neural-premise-selection.md#epic-5-pre-trained-model-distribution) (5.2)

---

## Problem

Neural premise selection requires a trained bi-encoder model. Training requires proof trace data (produced by the Training Data Extraction pipeline), compute resources, and expertise in configuring training runs. The project needs to support three distinct workflows:

1. **Project maintainers** train the canonical model on standard library + MathComp data and ship the checkpoint with the tool
2. **AI researchers** train experimental models with different architectures, hyperparameters, or training data and evaluate them against baselines
3. **Coq developers with large custom projects** fine-tune the pre-trained model on their project's proof traces to improve retrieval quality for their specific codebase

## Solution

A set of CLI commands that handle the full training lifecycle:

- **Train**: Given extracted proof trace data, train a bi-encoder retrieval model from scratch or from a pre-trained checkpoint
- **Evaluate**: Given a trained model and a held-out test set, compute retrieval quality metrics (Recall@k, MRR) and comparison statistics (neural vs. symbolic vs. union)
- **Fine-tune**: Given a pre-trained model and project-specific extracted data, adapt the model to a specific codebase
- **Validate**: Given extracted proof trace data, check for completeness and consistency before committing to a training run
- **Quantize**: Given a trained model, produce an INT8 quantized checkpoint for CPU inference

## Training Data Requirements

The training pipeline consumes `(proof_state, premises_used)` pairs in the JSON Lines format produced by the Training Data Extraction pipeline. The minimum viable training set is approximately 10,000 pairs — achievable from the Coq standard library alone (which contains ~15K theorems).

The validation command checks the data before training starts, reporting:
- Count of valid pairs, pairs with empty premise lists, pairs with malformed fields
- Total unique premises and proof states
- Premise frequency distribution (to detect degenerate data where a few premises dominate)

This catches common data quality issues (incomplete extraction, broken premise annotations) before GPU time is committed.

## Evaluation Framework

Evaluation is not just "how good is the model" — it is "how much does the neural channel add to the existing system." The evaluation command computes:

- **Neural-only metrics**: Recall@1, Recall@10, Recall@32, MRR on the held-out test set
- **Symbolic-only metrics**: The same metrics using only the existing structural/symbolic retrieval channels
- **Union metrics**: Recall@32 of the neural+symbolic union — the metric that matters for deployment
- **Overlap and exclusivity**: What percentage of correct retrievals are found by both channels vs. exclusively by one

The deployment threshold is ≥50% Recall@32 for neural-only and ≥15% relative improvement for the union over symbolic-only. If either threshold is not met, the evaluation command emits a warning.

## Compute Constraints

Training must complete on a single consumer GPU (≤24GB VRAM) or be offloadable to a cloud GPU within a $200 budget. This is achievable: RocqStar trained a 125M CodeBERT model in 14 hours on 1x H100 for ~$50–100. LeanHammer's 82M model took 6.5 A6000-days for ~$200–400.

Fine-tuning on a user's project data should complete in under 4 hours on the same hardware, given the smaller dataset size (typically 1K–10K proofs vs. 100K+ for full training).

## Design Rationale

### Why CLI, not a library API

The training workflow is batch-oriented: prepare data, start training, wait for completion, evaluate results. This maps naturally to CLI commands that can be scripted, run in CI, or invoked from cloud GPU instances. A Python library API would be useful for researchers who want to modify the training loop, but it is not the primary interface — researchers comfortable modifying training code can import the underlying modules directly.

### Why separate validate and train steps

Training a retrieval model costs GPU hours and real money. Validating the input data is instant and catches the most common failure modes (incomplete extraction, wrong format, degenerate premise distributions). Separating these steps follows the principle of failing fast and cheaply.

### Why the union metric is the deployment gate

A neural model that achieves high recall but retrieves the same results as existing channels adds latency without value. The union metric captures complementary value — results the neural channel finds that no other channel does. This is what justifies adding the neural channel to the pipeline.

### Why fine-tuning rather than retraining

Fine-tuning from a pre-trained checkpoint on 1K–10K project-specific proofs is vastly more data-efficient and compute-efficient than training from scratch. The pre-trained model already understands Coq's type theory, standard library conventions, and MathComp idioms; fine-tuning adapts it to the user's project-specific definitions and proof patterns. This follows the transfer learning pattern validated by PROOFWALA (cross-system transfer) and standard practice in NLP retrieval.
