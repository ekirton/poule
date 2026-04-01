# Neural Retrieval

Technical design for the neural retrieval channel: embedding computation, vector storage, similarity search, and integration into the multi-channel retrieval pipeline.

**Feature**: [Neural Retrieval Channel](../features/neural-retrieval-channel.md), [Pre-trained Model](../features/pre-trained-model.md)

---

## Component Diagram

```
Indexing path (offline)                  Query path (online)

Compiled .vo files                       MCP Server / CLI
  │                                        │
  │ coq-lsp / SerAPI                       │ search_by_type(query)
  ▼                                        ▼
Coq Library Extraction                   Retrieval Pipeline
  │                                        │
  │ declarations                           ├─ WL screening    → structural ranked list
  ▼                                        ├─ MePo            → symbol ranked list
Storage (SQLite)                           ├─ FTS5            → lexical ranked list
  │                                        ├─ Neural channel  → neural ranked list
  │ read declarations                      │     │
  ▼                                        │     │ encode query → FAISS search
Embedding Generator                        │     ▼
  │                                        │   Encoder (INT8, CPU)
  │ encode each declaration                │     │
  │ via Encoder (INT8, CPU)                │     │ top-k by inner product (FAISS)
  │                                        │     ▼
  │ write embeddings → build FAISS index   │   FAISS index (from .faiss sidecar file)
  ▼                                        │
Storage (SQLite + FAISS sidecar)           ├─ rrf_fuse([structural, symbol, lexical, neural])
  embeddings table (persistence)           │     │
  index.faiss (vector search) ◄────────────┘     │
                                                 ▼
                                           Fused ranked results
```

## Encoder

### Model Architecture

Bi-encoder (dual-encoder) with shared weights. The same encoder produces embeddings for both proof states/queries and premise declarations. Architecture choice:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Encoder-only transformer | Bi-encoders dominate premise selection; encoder-only is simpler and faster than decoder-as-encoder |
| Parameter count | ~98M (CodeBERT 125M base, reduced by closed-vocabulary embedding layer) | LeanHammer (82M) outperforms ReProver (299M); 100M-class is the efficiency sweet spot |
| Embedding dimension | 768 | Standard for 100M-class encoders; sufficient for 50K-200K item indexes |
| Base model | CodeBERT or equivalent code-pretrained encoder | Code-pretrained tokenizers handle formal syntax; RocqStar validated CodeBERT for Coq |
| Pooling | Mean pooling over final hidden states | Standard for bi-encoder retrieval; matches ReProver, CFR approaches |

### Quantization

The encoder is quantized to INT8 for CPU inference using ONNX Runtime or equivalent framework:

| Property | Full precision | INT8 quantized |
|----------|---------------|----------------|
| Model size on disk | ~400MB | ~100MB |
| Per-item encoding latency (CPU) | ~80ms | <10ms |
| Recall@32 degradation | baseline | ≤ 5% relative |

The quantization command takes a trained PyTorch checkpoint and produces an INT8 ONNX model. The ONNX model is the deployment artifact — the full-precision checkpoint is retained for fine-tuning but not loaded at inference time.

### Encoding Contract

```
encode(text: string) → float[768]
```

Input: serialized proof state or declaration statement (pretty-printed Coq text).

Output: L2-normalized 768-dimensional embedding vector.

The encoder is stateless and thread-safe. Multiple queries can be encoded concurrently.

## Embedding Storage

Embeddings use a dual-storage model: raw vectors are persisted in the SQLite `embeddings` table during the write path, and a FAISS index is serialized to a sidecar `.faiss` file at finalization. The read path loads only the FAISS index. See [storage.md](storage.md) for the SQLite schema.

### Write Path (Indexing)

After the standard indexing pass (declarations, WL vectors, dependencies, FTS5), an embedding pass runs:

```
1. Load INT8 quantized encoder model
2. For each declaration in the database:
     a. Read the pretty-printed statement from declarations.statement
     b. Encode → 768-dim float vector
     c. Serialize vector as raw bytes (768 × 4 bytes = 3,072 bytes per embedding)
     d. Batch-insert into embeddings table
3. Write model checkpoint hash to index_meta ('neural_model_hash')
4. At finalize: read all embeddings from SQLite, build FAISS IndexFlatIP, write to .faiss sidecar file
```

**Batch processing**: Encode declarations in batches of 64 to amortize model loading overhead. On CPU with INT8, a batch of 64 completes in ~500ms. For 50K declarations: ~800 batches × 500ms ≈ 7 minutes.

**Atomicity**: The embedding pass runs within the same database transaction as the rest of indexing. If embedding computation fails partway through, the entire index is discarded (same behavior as any other indexing failure). The FAISS sidecar file is written after SQLite finalization succeeds — if FAISS serialization fails, the SQLite database still contains the embeddings and the sidecar can be regenerated.

**FAISS sidecar convention**: For a database at `path/to/index.db`, the FAISS index is written to `path/to/index.faiss`. The sidecar file is a derived artifact — it can be regenerated from the SQLite `embeddings` table without re-encoding.

### Read Path (Query)

At server startup, the FAISS index is loaded from the sidecar file:

```
faiss_index: faiss.IndexIDMap(faiss.IndexFlatIP(768))   # declaration IDs stored in the index
```

Memory footprint: N × 768 × 4 bytes + FAISS overhead. For 50K declarations: ~150MB. For 200K: ~600MB. This sits alongside the WL histogram memory (~100MB for 100K declarations).

**Startup latency**: Loading a FAISS index from file is faster than reading individual SQLite BLOBs — `faiss.read_index` memory-maps the file and reads in a single I/O operation. For 50K embeddings: <500ms.

**Fallback**: If the `.faiss` file is missing but the `embeddings` table exists, the reader builds the FAISS index from SQLite BLOBs and writes the sidecar file for subsequent startups. This supports migration from pre-FAISS databases without re-encoding.

## Similarity Search

### FAISS IndexFlatIP Search

Vector similarity search uses FAISS `IndexFlatIP` (exact inner product search on L2-normalized vectors, equivalent to cosine similarity):

```
query_embedding = encode(query_text)           # <10ms (INT8 CPU)
scores, ids = faiss_index.search(query, k)     # <5ms (FAISS optimized BLAS)
results = [(int(ids[0][i]), float(scores[0][i])) for i in range(k)]
```

Total neural channel latency: <16ms on CPU. Well within the 100ms budget.

**Why IndexFlatIP rather than HNSW**: `IndexFlatIP` provides exact results — no approximation, no tuning parameters, no index build step beyond insertion. At 50K–200K declarations, exact search is <5ms via FAISS's optimized BLAS kernels. HNSW or IVF should be evaluated if corpus size exceeds 500K declarations; switching index types requires changing only the index construction code, not the search interface.

**Why FAISS rather than brute-force NumPy**: FAISS uses optimized BLAS routines (OpenBLAS/MKL) for the matrix-vector product, provides a standard `read_index`/`write_index` serialization format, and offers a clear upgrade path to approximate nearest neighbor indexes (HNSW, IVF) when needed — all without changing the search interface. The `IndexIDMap` wrapper stores declaration IDs directly in the index, eliminating the separate ID map array.

### Result Format

The neural channel returns results in the same format as other channels: a list of `(declaration_id, score)` pairs, sorted by descending score. The score is the cosine similarity (range [-1, 1]; in practice, [0, 1] for normalized embeddings of related content).

## Integration into Retrieval Pipeline

### Channel Registration

The neural channel is registered alongside existing channels in the retrieval pipeline. It participates in RRF fusion for `search_by_type` and is available for `search_by_structure` and `search_by_symbols`.

### Availability Check

On pipeline initialization, the neural channel checks:

1. Does the model checkpoint exist at the well-known model path?
2. Does the vocabulary file exist at the well-known vocabulary path?
3. Does the `embeddings` table in the database contain rows?
4. Does the `neural_model_hash` in `index_meta` match the current model's hash?

If any check fails, the neural channel marks itself as unavailable. The pipeline proceeds with the remaining channels. No error is raised — this is the expected state for installations without a model checkpoint.

### Query Processing Updates

**search_by_type (updated)**:

```
1. Parse and normalize the type expression
2. Run WL screening pipeline                   → structural ranked list
3. Extract symbols, run MePo                    → symbol ranked list
4. Run FTS5 query                               → lexical ranked list
5. If neural channel available:
     encode query text → neural ranked list      ◄── NEW
6. rrf_fuse([structural, symbol, lexical, neural?], k=60) → final ranked list
7. Return top-N results
```

**search_by_structure (updated)**:

```
1–8. (existing structural scoring pipeline, unchanged)
9. If neural channel available:
     encode query text → neural ranked list      ◄── NEW
10. rrf_fuse([structural_scored, neural?], k=60) → final ranked list
11. Return top-N results
```

**search_by_symbols (updated)**:

```
1–3. (existing MePo pipeline, unchanged)
4. If neural channel available:
     encode symbols as text → neural ranked list  ◄── NEW
5. rrf_fuse([mepo, neural?], k=60) → final ranked list
6. Return top-N results
```

**search_by_name (unchanged)**: Neural channel is not useful for pure name search. No change.

### Neural Query Encoding by Tool

Different search operations produce different query text for the neural encoder:

| Operation | Neural query text |
|-----------|------------------|
| `search_by_type` | The pretty-printed type expression (same string passed by the user) |
| `search_by_structure` | The pretty-printed expression (same string passed by the user) |
| `search_by_symbols` | Space-joined symbol names |

This simple approach works because the encoder was trained on pretty-printed Coq text. Future refinements (e.g., encoding the normalized ExprTree directly) are deferred.

## Model Checkpoint Management

### Pre-trained Model Location

The pre-trained model checkpoint (INT8 ONNX) is stored at a well-known path relative to the tool's data directory:

```
<data_dir>/models/neural-premise-selector.onnx
```

The data directory follows platform conventions (e.g., `~/.local/share/poule/` on Linux, `~/Library/Application Support/poule/` on macOS).

### Model-Index Consistency

The `index_meta` table stores the hash of the model checkpoint used to compute the embeddings (`neural_model_hash`). On server startup, if the current model checkpoint hash differs from the stored hash, the embeddings are stale and the neural channel is unavailable until re-indexing.

This prevents serving results from embeddings computed by a different model version — cosine similarity between vectors from different embedding spaces is meaningless.

## Design Rationale

### Why FAISS IndexFlatIP rather than brute-force NumPy

At 50K declarations, both approaches are <5ms. FAISS provides three advantages: (1) optimized BLAS kernels are marginally faster for the matmul, (2) `read_index`/`write_index` provides a standard serialization format with fast loading, and (3) the index type can be changed to HNSW or IVF for approximate search at larger scales without modifying the search interface. The cost is one additional dependency (`faiss-cpu`).

### Why IndexFlatIP rather than approximate indexes

`IndexFlatIP` is exact — no recall degradation, no tuning parameters. At the current scale (50K–200K declarations), exact search is fast enough. Approximate indexes (HNSW, IVF) add index build complexity and tuning surface for <1ms improvement. The threshold for switching to approximate search is ~500K declarations. The FAISS index type can be changed without modifying the search interface or storage format.

### Why dual storage (SQLite + FAISS sidecar)

The SQLite `embeddings` table persists raw vectors during the write path, providing atomicity within the existing database transaction. The FAISS sidecar file is a derived artifact generated at finalization, optimized for fast read-path loading. This preserves write-path simplicity (SQLite batch inserts) while providing fast read-path performance (FAISS native load). The sidecar can be regenerated from SQLite without re-encoding — supporting migration from pre-FAISS databases and recovery from sidecar corruption.

### Why load all embeddings into memory

The embedding matrix for 50K declarations is ~150MB — comparable to the WL histograms already loaded at startup. Memory-mapped file access would save startup time but add complexity for marginal benefit. The matrix is read-once-at-startup, used-many-times — in-memory is the right trade-off.

### Why shared encoder weights for queries and premises

A shared encoder (same weights for both query and premise) simplifies the architecture: one model to load, one to quantize, one to distribute. Asymmetric encoders (different weights for query vs. premise) can improve quality but double the model management complexity. LeanHammer, ReProver, and CFR all use shared-weight bi-encoders successfully.

### Why mean pooling rather than [CLS] token

Mean pooling over all token positions produces more robust embeddings for variable-length formal expressions than a single [CLS] token. The [CLS] approach can be dominated by the first few tokens; mean pooling distributes attention across the full expression. ReProver uses mean pooling; LeanHammer uses an unspecified encoder pooling; both work well.
