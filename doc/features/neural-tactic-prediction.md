# Neural Retrieval Channel

A learned semantic similarity channel added to the multi-channel retrieval pipeline, trained on Coq proof traces to capture mathematical relationships that structural and symbolic channels miss.

---

## Problem

The existing retrieval channels (structural, symbol overlap, lexical, fine structural, constant name) all operate on surface-level properties of declarations. They find lemmas that share tree shape, reference the same constants, or contain matching name fragments. What they cannot find are lemmas whose relevance depends on mathematical relationships invisible to syntactic analysis.

A user looking for a lemma about group commutativity will not find results about ring commutativity through structural search — the proof shapes and symbol sets are different. A user working with `Nat.add` will not discover relevant results about `Z.add` through symbol overlap, even though the mathematical relationship is direct. These "semantic gaps" are precisely where users get stuck: they know a relevant lemma should exist but cannot formulate a syntactic query that finds it.

Research confirms this is a real, measurable problem. In Lean, the union of neural and symbolic selection improves recall by 21% over either alone (LeanHammer). The gains come almost entirely from cases where one channel finds results the other misses — the errors are complementary, not overlapping.

## Solution

A bi-encoder retrieval model maps proof states and premise declarations into a shared embedding space. At index time, every declaration in the library is encoded into a dense vector and stored alongside existing retrieval data in the SQLite index. At query time, the proof state (or search query) is encoded into the same space, and the nearest premises are retrieved by cosine similarity.

The neural channel participates in the existing fusion mechanism. Items that appear in multiple channels (neural + structural, neural + symbolic, etc.) are ranked higher than items from a single channel. The neural channel does not replace any existing channel — it adds a complementary signal.

## How It Fits in the Pipeline

The neural channel is one more input to the existing rank fusion. From the user's perspective, nothing changes about how search is invoked — the same MCP tools and CLI commands work identically. The only observable effect is better search quality: results that were previously missed by all channels now appear when the neural channel retrieves them.

| Search Operation | Channels Used (with neural) |
|------------------|---------------------------|
| `search_by_type` | Structural + Symbol Overlap + Lexical + **Neural** |
| `search_by_structure` | Structural + Fine Structural + Constant Name + **Neural** |
| `search_by_symbols` | Symbol Overlap + Constant Name + **Neural** |
| `search_by_name` | Lexical only (neural not useful for pure name search) |

## Graceful Degradation

The neural channel is optional. When no model checkpoint or premise embeddings are available, search operates using only the existing channels with no errors, no warnings, and no degraded behavior. This means:

- A fresh installation works immediately with structural/symbolic search
- The neural channel activates automatically when a model checkpoint and embeddings are present in the index
- Removing or corrupting the model checkpoint reverts to symbolic-only search

## Inference Constraints

The model runs on CPU with INT8 quantization. No GPU is required at inference time. This is a hard constraint: the target user is a Coq developer on a laptop, not an ML engineer with GPU access. The 100M-class encoder models used in the research literature achieve <10ms per encoding on CPU with INT8 — well within the <100ms budget per neural channel query.

The end-to-end search latency (all channels including neural, plus fusion) remains under 1 second. Adding the neural channel should be imperceptible to the user in terms of response time.

## Design Rationale

### Why a new channel, not a replacement

BM25 beats dense embeddings by 46% for in-project Coq retrieval (Rango, ICSE 2025). Structural methods are competitive with neural methods without training data (tree-based premise selection, NeurIPS 2025). The neural channel fills the semantic gap — it does not dominate the other signals. Replacing existing channels would lose the lexical and structural strengths that the neural channel cannot replicate.

### Why bi-encoder, not cross-encoder

A cross-encoder (jointly encoding query + each candidate) produces higher-quality scores but requires O(K) forward passes — one per candidate. For a 50K-declaration library, this is infeasible at interactive latency. The bi-encoder precomputes all premise embeddings at index time; only the query encoding happens at search time. This gives O(1) retrieval via FAISS or brute-force cosine similarity, which at 50K scale is <5ms even on CPU.

A future two-stage pipeline (bi-encoder → cross-encoder reranking of top-k) is a P2 enhancement that could improve precision on the top-ranked results without affecting the overall latency budget.

### Why parameter-free fusion

The existing fusion mechanism combines channels without learned weights. Adding the neural channel to the same parameter-free fusion avoids the need for a tuning dataset or manual weight selection. If evaluation data becomes available (from retrieval telemetry or curated benchmarks), learned fusion weights can be introduced later as a refinement.

### Why CPU-only inference

The research evidence is clear: 100M-class models with INT8 quantization achieve <10ms per encoding on any modern CPU. At 50K declarations, brute-force FAISS search adds <5ms. Total neural channel latency: ~15ms. Requiring a GPU would exclude most Coq developers and violate the project's zero-config deployment principle. The quality gap between 100M CPU models and 7B GPU models is small when compensated by hybrid ranking (LeanExplore's 109M off-the-shelf model matched or beat 7B fine-tuned models with hybrid ranking).

---

## Acceptance Criteria

### Embed Premises into the Search Index

**Priority:** P0
**Stability:** Stable

- GIVEN a pre-trained model checkpoint and a Semantic Lemma Search index WHEN the index rebuild is triggered THEN premise embeddings are computed for all declarations and stored in the SQLite database
- GIVEN a library of 50,000 declarations WHEN premise embeddings are computed on CPU with INT8 quantization THEN the embedding step completes in under 10 minutes
- GIVEN the embeddings are stored WHEN the database is inspected THEN each declaration has a corresponding embedding vector alongside its existing retrieval data

### Neural Channel Participates in Hybrid Ranking

**Priority:** P0
**Stability:** Stable

- GIVEN a search query submitted via the MCP server or CLI WHEN the neural channel is available THEN the neural channel's ranked results are included in the fusion step alongside existing channels
- GIVEN a search query WHEN the neural channel returns results THEN the fused ranking promotes items that appear in multiple channels (neural + symbolic + structural)
- GIVEN a search query WHEN the neural channel is not available (no model checkpoint or embeddings) THEN search operates using only existing channels with no errors or degradation

### Configurable Retrieval Budget

**Priority:** P1
**Stability:** Stable

- GIVEN a search query with a retrieval budget parameter WHEN the neural channel executes THEN it returns at most the specified number of candidates (default: 32)
- GIVEN a retrieval budget of 128 on a 50,000-declaration index WHEN the query executes on CPU THEN the neural channel completes in under 100ms

### CPU Inference with INT8 Quantization

**Priority:** P0
**Stability:** Stable

- GIVEN a pre-trained model checkpoint WHEN the quantize command is run THEN an INT8 quantized model is produced that can be loaded without a GPU
- GIVEN an INT8 quantized model and a 50,000-declaration index WHEN a single proof state is encoded and the top-32 premises are retrieved THEN the total latency is under 100ms on a modern laptop CPU
- GIVEN the INT8 quantized model WHEN Recall@32 is compared to the full-precision model on the same test set THEN the quantized model achieves at least 95% of the full-precision Recall@32

### End-to-End Search Latency

**Priority:** P0
**Stability:** Stable

- GIVEN a 50,000-declaration index with all channels active (neural, structural, symbolic) WHEN a search query is submitted THEN the end-to-end response time is under 1 second on a modern laptop CPU
- GIVEN multiple concurrent search queries WHEN they are submitted within 1 second THEN each query completes within 1 second (no serialization bottleneck)
