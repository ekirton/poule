# User Stories: Neural Premise Selection

Derived from [doc/requirements/neural-premise-selection.md](../neural-premise-selection.md).

---

## Epic 1: Model Training

### 1.1 Train a Retrieval Model from Extracted Data

**As an** AI researcher or tool maintainer,
**I want to** train a bi-encoder retrieval model from extracted Coq proof trace data,
**so that** I can produce a neural premise selector tailored to a Coq library corpus.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a directory of JSON Lines proof trace files produced by Training Data Extraction WHEN the train command is run THEN a bi-encoder model checkpoint is produced in the specified output directory
- GIVEN extracted data containing at least 10,000 `(proof_state, premises_used)` pairs WHEN training completes THEN the output includes loss curves and validation Recall@32 computed on a held-out split
- GIVEN the training command is run without specifying a GPU WHEN a CUDA-capable GPU with ≤ 24GB VRAM is available THEN training uses the GPU automatically
- GIVEN the training command is run WHEN no GPU is available THEN training falls back to CPU with a warning about expected duration

### 1.2 Validate Training Data Before Training

**As a** tool maintainer,
**I want to** validate extracted proof trace data for completeness before starting model training,
**so that** I catch data quality issues before investing compute time.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a directory of JSON Lines proof trace files WHEN the validation command is run THEN it reports the count of valid `(proof_state, premises_used)` pairs, pairs with empty premise lists, and pairs with malformed fields
- GIVEN a dataset where more than 10% of pairs have empty premise lists WHEN validation completes THEN a warning is emitted identifying the affected source files
- GIVEN a valid dataset WHEN validation completes THEN it reports the total unique premises, total unique proof states, and the premise frequency distribution (top-10 most referenced premises)

### 1.3 Hard Negative Mining

**As an** AI researcher,
**I want** the training pipeline to use hard negatives sampled from accessible but unused premises,
**so that** the model learns fine-grained distinctions between relevant and irrelevant premises.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a proof state with known used premises and a set of accessible premises WHEN training batches are constructed THEN each positive pair is accompanied by at least 3 hard negatives drawn from the accessible-but-unused premise set
- GIVEN a proof state for which no accessibility information is available WHEN training batches are constructed THEN negatives are drawn from the full premise corpus as a fallback

### 1.4 Masked Contrastive Loss for Shared Premises

**As an** AI researcher,
**I want** the training loss to mask shared premises that appear as positives for other proof states in the same batch,
**so that** commonly used lemmas are not penalized as false negatives.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a training batch where premise P is a positive for proof state A and also appears in the candidate set for proof state B WHEN the contrastive loss is computed for proof state B THEN premise P is masked (excluded from the negative set) rather than treated as a negative
- GIVEN a training run with masked contrastive loss WHEN compared to a training run with standard InfoNCE on the same data THEN the masked variant achieves equal or higher Recall@32 on the validation set

---

## Epic 2: Model Evaluation

### 2.1 Evaluate Retrieval Quality

**As an** AI researcher or tool maintainer,
**I want to** evaluate a trained model's retrieval quality on a held-out test set,
**so that** I can assess whether the model meets quality thresholds before deployment.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a trained model checkpoint and a held-out test set of `(proof_state, premises_used)` pairs WHEN the evaluate command is run THEN it reports Recall@1, Recall@10, Recall@32, and MRR
- GIVEN the evaluation results WHEN Recall@32 is below 50% THEN a warning is emitted indicating the model does not meet the deployment threshold
- GIVEN an evaluation run WHEN it completes THEN it also reports the number of test examples, average premises per proof state, and evaluation latency per query

### 2.2 Compare Neural vs. Symbolic Retrieval

**As an** AI researcher,
**I want to** compare neural-only, symbolic-only, and neural+symbolic union retrieval on the same test set,
**so that** I can quantify the complementary value of the neural channel.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a test set and both neural and symbolic retrieval results WHEN the comparison command is run THEN it reports Recall@32 for neural-only, symbolic-only, and their union
- GIVEN the union results WHEN the relative improvement over symbolic-only is below 15% THEN a warning is emitted indicating the neural channel may not provide sufficient complementary value
- GIVEN the comparison results WHEN they are reported THEN the output includes the overlap percentage (premises retrieved by both channels) and the exclusive contribution of each channel

---

## Epic 3: Index Integration

### 3.1 Embed Premises into the Search Index

**As a** Coq developer using Claude Code,
**I want** premise embeddings to be computed and stored in the search index alongside existing retrieval data,
**so that** neural retrieval is available without a separate setup step.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a pre-trained model checkpoint and a Semantic Lemma Search index WHEN the index rebuild is triggered THEN premise embeddings are computed for all declarations and stored in the SQLite database
- GIVEN a library of 50,000 declarations WHEN premise embeddings are computed on CPU with INT8 quantization THEN the embedding step completes in under 10 minutes
- GIVEN the embeddings are stored WHEN the database is inspected THEN each declaration has a corresponding embedding vector alongside its existing retrieval data

### 3.2 Neural Channel Participates in Hybrid Ranking

**As a** Coq developer using Claude Code,
**I want** neural retrieval results to be fused with existing symbolic and structural results,
**so that** I get improved search quality without changing my workflow.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a search query submitted via the MCP server or CLI WHEN the neural channel is available THEN the neural channel's ranked results are included in the fusion step alongside existing channels
- GIVEN a search query WHEN the neural channel returns results THEN the fused ranking promotes items that appear in multiple channels (neural + symbolic + structural)
- GIVEN a search query WHEN the neural channel is not available (no model checkpoint or embeddings) THEN search operates using only existing channels with no errors or degradation

### 3.3 Configurable Retrieval Budget

**As a** tool builder,
**I want to** configure the number of candidates the neural channel retrieves per query,
**so that** I can tune the trade-off between retrieval quality and latency.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a search query with a retrieval budget parameter WHEN the neural channel executes THEN it returns at most the specified number of candidates (default: 32)
- GIVEN a retrieval budget of 128 on a 50,000-declaration index WHEN the query executes on CPU THEN the neural channel completes in under 100ms

---

## Epic 4: Inference Performance

### 4.1 CPU Inference with INT8 Quantization

**As a** Coq developer,
**I want** neural premise retrieval to run on my laptop CPU without a GPU,
**so that** I can use improved search quality without special hardware.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a pre-trained model checkpoint WHEN the quantize command is run THEN an INT8 quantized model is produced that can be loaded without a GPU
- GIVEN an INT8 quantized model and a 50,000-declaration index WHEN a single proof state is encoded and the top-32 premises are retrieved THEN the total latency is under 100ms on a modern laptop CPU
- GIVEN the INT8 quantized model WHEN Recall@32 is compared to the full-precision model on the same test set THEN the quantized model achieves at least 95% of the full-precision Recall@32

### 4.2 End-to-End Search Latency

**As a** Coq developer using Claude Code,
**I want** end-to-end search latency to remain under 1 second even with the neural channel active,
**so that** adding neural retrieval does not degrade my interactive experience.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a 50,000-declaration index with all channels active (neural, structural, symbolic) WHEN a search query is submitted THEN the end-to-end response time is under 1 second on a modern laptop CPU
- GIVEN multiple concurrent search queries WHEN they are submitted within 1 second THEN each query completes within 1 second (no serialization bottleneck)

---

## Epic 5: Pre-trained Model Distribution

### 5.1 Ship a Pre-trained Model for Standard Library and MathComp

**As a** Coq developer,
**I want** a pre-trained neural premise selection model to be available without training one myself,
**so that** I get improved search quality out of the box.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a fresh installation of the search tool WHEN the user runs the indexing command with the default model THEN the pre-trained model is used to compute premise embeddings without requiring any training step
- GIVEN the pre-trained model WHEN evaluated on a held-out test set from the Coq standard library and MathComp THEN it achieves ≥ 50% Recall@32
- GIVEN the pre-trained model checkpoint WHEN its size is measured THEN the INT8 quantized model is under 500MB

### 5.2 Fine-tune on a User Project

**As a** Coq developer with a large custom project,
**I want to** fine-tune the pre-trained model on my project's extracted proof traces,
**so that** neural retrieval adapts to my project's definitions and proof patterns.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a pre-trained model checkpoint and a user project's extracted proof trace data WHEN the fine-tune command is run THEN a fine-tuned model checkpoint is produced
- GIVEN a fine-tuned model WHEN evaluated on a held-out test set from the user's project THEN it achieves equal or higher Recall@32 compared to the base pre-trained model on the same test set
- GIVEN a user project with at least 1,000 extracted proofs WHEN fine-tuning is run on a consumer GPU (≤ 24GB VRAM) THEN fine-tuning completes in under 4 hours

---

## Epic 6: Cross-System Transfer (Future)

### 6.1 Initialize from Lean Pre-trained Weights

**As an** AI researcher,
**I want to** initialize a Coq premise selector from a model pre-trained on Lean retrieval data,
**so that** I can leverage the larger Lean training corpus to bootstrap Coq retrieval quality.

**Priority:** P2
**Stability:** Volatile

**Acceptance criteria:**
- GIVEN a pre-trained Lean premise selection model (e.g., LeanHammer weights) WHEN the train command is run with the transfer flag THEN training initializes from the Lean weights before fine-tuning on Coq data
- GIVEN a transfer-trained model WHEN evaluated on the Coq test set THEN it achieves equal or higher Recall@32 compared to a model trained from scratch on Coq data only
