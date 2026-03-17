# Neural Retrieval Channel

A learned semantic similarity channel added to the multi-channel retrieval pipeline, trained on Coq proof traces to capture mathematical relationships that structural and symbolic channels miss.

**Stories**: [Epic 3: Index Integration](../requirements/stories/neural-premise-selection.md#epic-3-index-integration), [Epic 4: Inference Performance](../requirements/stories/neural-premise-selection.md#epic-4-inference-performance)

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
