# Neural Premise Selection for Coq/Rocq — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context and initiative sequencing.

Lineage: Depends on Training Data Extraction for `(proof_state, premises_used)` pairs. Enhances Semantic Lemma Search by adding a neural retrieval channel to its hybrid ranking pipeline. Consumed by Proof Search & Automation for premise-augmented tactic candidate generation.

## 1. Business Goals

Semantic Lemma Search delivers tree-based and symbolic retrieval channels that work without training data or GPU. These channels excel at syntactic and structural matches but miss semantically related premises that lack surface-level overlap — the "semantic gap." Research shows that neural and symbolic selectors make complementary errors: LeanHammer's union of neural and symbolic selection improves results by 21% over either alone. Coq users working with large libraries (MathComp, Iris, CompCert) routinely need lemmas whose relevance depends on mathematical relationships invisible to syntactic matching.

This initiative delivers a neural retrieval channel for the Semantic Lemma Search pipeline. Given a proof state, it retrieves premises from the indexed library ranked by learned semantic relevance, complementing the existing structural and symbolic channels. The neural model is trained on proof trace data produced by Training Data Extraction.

**What this initiative does not do:** It does not replace Semantic Lemma Search's existing retrieval channels, build a separate search interface, or create a standalone premise selection tool. It adds a neural signal to the existing hybrid ranking system. Claude Code continues to be the user interface; the neural channel is invisible to users except through improved search quality.

**Success metrics:**
- ≥ 50% Recall@32 on a held-out evaluation set of Coq proofs with known premise annotations
- Neural+symbolic union achieves ≥ 15% relative improvement in Recall@32 over symbolic-only retrieval
- Neural channel query latency < 100ms on CPU (no GPU required at inference time)
- Index rebuild latency < 10 minutes for libraries up to 50K declarations on a single machine without GPU
- End-to-end search latency (including fusion with existing channels) remains < 1 second

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers using Claude Code | Higher-quality lemma retrieval when working with large libraries where syntactic search misses semantically relevant results | Primary |
| Proof Search & Automation | Premise-augmented tactic candidate generation during automated proof search, improving search success rate | Primary |
| AI researchers | A neural premise selection baseline for Coq that can be evaluated, compared, and extended | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Premise selection and retrieval survey](../background/coq-premise-retrieval.md)
- [Neural retrieval architectures survey](../background/neural-retrieval.md)
- [Neural encoder architectures for premise selection](../background/neural-encoder-architectures-premise-selection.md)

**Lean ecosystem (comparative baseline):**
- LeanHammer: encoder-only transformer (82M params), 72.7% R@32 on Mathlib, ~1-second latency on CPU. The current state of the art for neural premise selection in any proof assistant.
- ReProver: ByT5 dual-encoder (299M params), 38.4% R@10. Established the bi-encoder paradigm for formal math retrieval.
- Lean Finder: 7B decoder-as-encoder with DPO, 81.6% user preference rate. Best user-facing search satisfaction but requires GPU.
- RGCN-augmented retrieval: +26% R@10 over ReProver by adding dependency graph structure to text embeddings.

**Coq ecosystem (current state):**
- CoqHammer: symbol-overlap heuristic. Fast and deterministic but no learned semantic understanding.
- Graph2Tac (Tactician): GNN-based premise selection with online adaptation. Architecturally sophisticated but requires Tactician's infrastructure; niche adoption.
- RocqStar: CodeBERT bi-encoder trained on proof similarity (BigRocq dataset). Open-source model and training code. +28% over Jaccard baseline.
- Rango: BM25 retrieval beats CodeBERT dense embeddings by 46% for in-project Coq proof retrieval (ICSE 2025), demonstrating the critical importance of lexical signal for Coq.
- No system combines neural embeddings with symbolic/structural retrieval for Coq.

**Key research findings informing design:**
- Small models win: LeanHammer (82M) outperforms ReProver (299M) by 150% — better training objectives and data quality matter more than model size
- BM25 beats dense embeddings for Coq in-project retrieval (Rango), so the neural channel must complement, not replace, lexical and structural channels
- Hybrid dense+sparse achieves 20% relative improvement over dense-only (MSMARCO benchmark); nobody has combined all signal types for formal math
- Training a formal math retrieval model costs $50–600 in GPU time; the bottleneck is data preparation, not compute
- 100M-class models with INT8 quantization run at <10ms/item on CPU — no GPU needed at inference time
- Domain-specific tokenization improves retrieval 33% for small models (CFR finding)
- Cross-system transfer works: PROOFWALA shows models trained on both Lean and Coq outperform monolingual models

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R5-P0-1 | Train a bi-encoder retrieval model on `(proof_state, premises_used)` pairs extracted by the Training Data Extraction pipeline |
| R5-P0-2 | Encode proof states and premise declarations into a shared embedding space; retrieve premises by cosine similarity |
| R5-P0-3 | Integrate the neural retrieval channel into the Semantic Lemma Search pipeline as an additional retrieval channel, participating in the existing fusion/ranking mechanism |
| R5-P0-4 | Precompute and store premise embeddings in the search index alongside other retrieval channel data |
| R5-P0-5 | Neural channel query latency < 100ms on CPU without GPU |
| R5-P0-6 | Support INT8 quantized inference for the encoder model on CPU |
| R5-P0-7 | Rebuild premise embeddings when the library index is rebuilt, using the same trigger as existing index rebuilds |
| R5-P0-8 | Achieve ≥ 50% Recall@32 on a held-out evaluation set derived from extracted Coq proof traces |
| R5-P0-9 | Neural+symbolic union achieves ≥ 15% relative improvement in Recall@32 over symbolic-only on the same evaluation set |
| R5-P0-10 | Provide a CLI command to train the retrieval model from extracted training data |
| R5-P0-11 | Provide a CLI command to evaluate retrieval quality (recall@k, MRR) on a held-out test set |
| R5-P0-12 | Ship a pre-trained model checkpoint covering the Coq standard library and MathComp so that users do not need to train a model themselves |
| R5-P0-13 | Model training must complete on a single consumer GPU (≤ 24GB VRAM), Apple Silicon Mac (≥ 32GB unified memory) using MLX, or be offloadable to a cloud GPU within a $200 budget |
| R5-P0-14 | Build a closed-vocabulary tokenizer from the indexed library declarations and extracted proof states, replacing the generic BPE tokenizer with one that assigns every Coq identifier its own token ID |
| R5-P0-15 | Provide a CLI command to build the vocabulary from the search index and training data, producing a JSON file mapping tokens to integer IDs |
| R5-P0-16 | Support training the bi-encoder model on Apple Silicon Macs using MLX as an alternative to PyTorch, producing checkpoints that can be converted to PyTorch format for inference in the Linux container |
| R5-P0-17 | Provide a weight conversion step that transforms MLX-trained checkpoints into PyTorch format compatible with the existing ONNX quantization and inference pipeline |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R5-P1-1 | Support fine-tuning the pre-trained model on a user's project-specific extracted data to improve retrieval quality for that project's declarations |
| R5-P1-2 | Use hard negative mining during training: sample negatives from the set of accessible but unused premises for each proof state |
| R5-P1-3 | Use masked contrastive loss to handle shared premises (premises used in many proofs) without generating false negative training signal |
| R5-P1-4 | When the Semantic Lemma Search index includes dependency graph data, augment text-based embeddings with graph structure signal during retrieval |
| R5-P1-5 | Provide a training data validation step that checks extracted `(proof_state, premises_used)` pairs for completeness and consistency before training |
| R5-P1-6 | Support configurable retrieval budget (top-k) per query, defaulting to 32 |
| R5-P1-7 | Report training metrics (loss curves, validation recall@k) during and after training |
| R5-P1-8 | Provide automated hyperparameter optimization that searches over training hyperparameters (learning rate, temperature, batch size, weight decay, hard negatives per state) to maximize validation Recall@32, with early pruning of underperforming configurations to reduce total compute |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R5-P2-1 | Support cross-system transfer: initialize from a model pre-trained on Lean retrieval data before fine-tuning on Coq data |
| R5-P2-2 | Support two-stage retrieval: bi-encoder first pass followed by cross-encoder reranking of top-k results |
| R5-P2-3 | *(Promoted to R5-P0-14/15)* |
| R5-P2-4 | Support Matryoshka embeddings (variable-dimension) to enable dimension-accuracy tradeoffs for deployment on constrained hardware |
| R5-P2-5 | Collect retrieval telemetry (queries per session, recall feedback from proof success/failure) to enable future model improvement |
| R5-P2-6 | Support BM25+dense hybrid scoring within the neural channel itself, using learned sparse representations (SPLADE) alongside dense embeddings |

---

## 5. Scope Boundaries

**In scope:**
- Training a bi-encoder retrieval model on Coq proof trace data
- MLX training backend for Apple Silicon Macs with weight conversion to PyTorch
- Integrating the neural channel into the existing Semantic Lemma Search MCP server and CLI
- Pre-trained model checkpoint for standard library and MathComp
- CLI tools for training, evaluation, and fine-tuning
- CPU-based INT8 quantized inference (no GPU required at inference time)
- Evaluation framework for retrieval quality

**Out of scope:**
- Replacing or modifying existing symbolic/structural retrieval channels in Semantic Lemma Search
- Building a separate MCP server or search interface for neural retrieval
- Training data extraction (covered by Training Data Extraction initiative)
- Proof search or tactic generation (covered by Proof Search & Automation initiative)
- GPU hosting infrastructure for inference
- IDE plugin development (search is accessed via Claude Code's MCP integration or CLI)
- Web interface for search results
- Real-time online learning (adapting embeddings during interactive proof development)
