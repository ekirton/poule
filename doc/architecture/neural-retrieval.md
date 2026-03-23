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
  │                                        ├─ Neural channel  → neural ranked list ◄── NEW
  │ read declarations                      │     │
  ▼                                        │     │ encode query → cosine search
Embedding Generator                        │     ▼
  │                                        │   Encoder (INT8, CPU)
  │ encode each declaration                │     │
  │ via Encoder (INT8, CPU)                │     │ top-k by cosine similarity
  │                                        │     ▼
  │ write embeddings                       │   Embedding vectors (from SQLite)
  ▼                                        │
Storage (SQLite)                           ├─ rrf_fuse([structural, symbol, lexical, neural])
  embeddings table ◄───────────────────────┘     │
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

Embeddings are stored in the existing SQLite index database. See [storage.md](storage.md) for the schema addition.

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
```

**Batch processing**: Encode declarations in batches of 64 to amortize model loading overhead. On CPU with INT8, a batch of 64 completes in ~500ms. For 50K declarations: ~800 batches × 500ms ≈ 7 minutes.

**Atomicity**: The embedding pass runs within the same database transaction as the rest of indexing. If embedding computation fails partway through, the entire index is discarded (same behavior as any other indexing failure).

### Read Path (Query)

At server startup, all embeddings are loaded into memory as a contiguous float32 matrix:

```
embedding_matrix: float[N × 768]  where N = number of declarations
decl_id_map: int[N]               mapping matrix row → declaration ID
```

Memory footprint: N × 768 × 4 bytes. For 50K declarations: ~150MB. For 200K: ~600MB. This sits alongside the WL histogram memory (~100MB for 100K declarations).

**Startup latency**: Loading 50K embeddings from SQLite into a contiguous matrix takes <1 second. This is comparable to the existing WL histogram loading.

## Similarity Search

### Brute-Force Cosine Search

At the scale of Coq libraries (50K–200K declarations), brute-force cosine similarity is fast enough:

```
query_embedding = encode(query_text)           # <10ms (INT8 CPU)
scores = embedding_matrix @ query_embedding    # <5ms (50K × 768 matmul)
top_k_indices = argpartition(scores, k)        # <1ms
results = [(decl_id_map[i], scores[i]) for i in top_k_indices]
```

Total neural channel latency: <16ms on CPU. Well within the 100ms budget.

**Why not FAISS HNSW**: At 50K items, brute-force is <5ms. HNSW adds index build complexity and approximate results for no meaningful latency gain. If corpus size exceeds 500K, HNSW should be evaluated.

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

### Why brute-force search rather than ANN index

At 50K declarations, a 768-dim matmul takes <5ms on CPU. FAISS HNSW or IVF would add index construction complexity, tuning parameters (ef_construction, nprobe), and approximate results — all for <1ms improvement at this scale. The brute-force approach is exact, trivially correct, and fast enough. The threshold for switching to ANN is ~500K declarations, which is beyond the current Coq library landscape.

### Why load all embeddings into memory

The embedding matrix for 50K declarations is ~150MB — comparable to the WL histograms already loaded at startup. Memory-mapped file access would save startup time but add complexity for marginal benefit. The matrix is read-once-at-startup, used-many-times — in-memory is the right trade-off.

### Why store embeddings in SQLite rather than a separate file

The index is a single SQLite file — adding embeddings to it preserves the single-file property. A separate embeddings file would require coordinating two files (versioning, copying, deletion). The BLOB storage overhead in SQLite is minimal for fixed-size binary data.

### Why shared encoder weights for queries and premises

A shared encoder (same weights for both query and premise) simplifies the architecture: one model to load, one to quantize, one to distribute. Asymmetric encoders (different weights for query vs. premise) can improve quality but double the model management complexity. LeanHammer, ReProver, and CFR all use shared-weight bi-encoders successfully.

### Why mean pooling rather than [CLS] token

Mean pooling over all token positions produces more robust embeddings for variable-length formal expressions than a single [CLS] token. The [CLS] approach can be dominated by the first few tokens; mean pooling distributes attention across the full expression. ReProver uses mean pooling; LeanHammer uses an unspecified encoder pooling; both work well.
