# Neural Retrieval Channel

Neural embedding-based retrieval channel for the multi-channel search pipeline.

**Architecture**: [neural-retrieval.md](../doc/architecture/neural-retrieval.md), [component-boundaries.md](../doc/architecture/component-boundaries.md)

---

## 1. Purpose

Define the neural retrieval channel: encoder interface, embedding storage and loading, vector similarity search, integration with the retrieval pipeline's fusion mechanism, and model checkpoint management.

## 2. Scope

**In scope**: `NeuralEncoder` interface (encode, load, availability), `EmbeddingIndex` (in-memory vector matrix, cosine search), embedding write path (indexing), embedding read path (query-time loading), neural channel integration into pipeline fusion, model checkpoint lifecycle.

**Out of scope**: Model training, fine-tuning, evaluation (owned by neural-training), individual channel algorithms for existing channels (owned by channel specs), storage schema DDL (owned by storage), MCP protocol handling (owned by mcp-server).

## 3. Definitions

| Term | Definition |
|------|-----------|
| NeuralEncoder | The interface to the INT8-quantized ONNX encoder model that maps text to embedding vectors |
| EmbeddingIndex | An in-memory matrix of precomputed premise embeddings with cosine similarity search |
| Neural channel | The retrieval channel that encodes a query via NeuralEncoder and retrieves nearest premises via EmbeddingIndex |
| Model checkpoint | An INT8-quantized ONNX file at the well-known model path |

## 4. Behavioral Requirements

### 4.1 NeuralEncoder

#### load(model_path, vocabulary_path=None)

- REQUIRES: `model_path` points to an existing INT8 ONNX model file. `vocabulary_path`, when provided, points to a valid vocabulary JSON file (as produced by `VocabularyBuilder.build`).
- ENSURES: The encoder model is loaded and ready for inference. Returns a `NeuralEncoder` instance. When `vocabulary_path` is provided, uses `CoqTokenizer` (whitespace split + dictionary lookup) for tokenization. When `vocabulary_path` is `None`, falls back to CodeBERT's default tokenizer.
- On file not found: raises `ModelNotFoundError`.
- On invalid ONNX format: raises `ModelLoadError`.

#### encode(text)

- REQUIRES: `text` is a non-empty string. Encoder is loaded.
- ENSURES: Returns an L2-normalized float vector of dimension 768. The same input text always produces the same output vector (deterministic).
- On text longer than 512 tokens: input is truncated to 512 tokens before encoding. No error is raised.

> **Given** encoder is loaded
> **When** `encode("forall n m : nat, n + m = m + n")` is called
> **Then** returns a 768-dim float vector with L2 norm = 1.0

> **Given** encoder is loaded
> **When** `encode("forall n m : nat, n + m = m + n")` is called twice
> **Then** both calls return identical vectors

#### encode_batch(texts)

- REQUIRES: `texts` is a non-empty list of non-empty strings. Encoder is loaded.
- ENSURES: Returns a list of L2-normalized float vectors, one per input text. Order is preserved. Each vector is identical to calling `encode` on the corresponding text individually.

> **Given** a batch of 64 declaration statements
> **When** `encode_batch(statements)` is called
> **Then** returns 64 vectors, each 768-dim with L2 norm = 1.0

#### model_hash()

- REQUIRES: Encoder is loaded.
- ENSURES: Returns the SHA-256 hex digest of the model file content.

### 4.2 EmbeddingIndex

#### build(embedding_matrix, decl_id_map)

- REQUIRES: `embedding_matrix` is a 2D float array of shape `[N, 768]`. `decl_id_map` is a 1D integer array of length N mapping row indices to declaration IDs. N > 0.
- ENSURES: Returns an `EmbeddingIndex` ready for search.

#### search(query_vector, k)

- REQUIRES: `query_vector` is a 768-dim L2-normalized float vector. `k` is a positive integer.
- ENSURES: Returns up to `min(k, N)` `(declaration_id, cosine_similarity_score)` pairs, sorted by descending score. Scores are in range [-1, 1].
- MAINTAINS: Search is exact (brute-force); no approximation.

> **Given** an index with 50,000 embeddings
> **When** `search(query_vector, k=32)` is called
> **Then** returns 32 `(decl_id, score)` pairs sorted by descending cosine similarity

> **Given** an index with 10 embeddings
> **When** `search(query_vector, k=32)` is called
> **Then** returns 10 `(decl_id, score)` pairs (min of k and N)

#### Algorithm

```
scores = embedding_matrix @ query_vector     # [N] dot products (= cosine sim for L2-normalized vectors)
top_k_indices = argpartition(scores, k)      # top-k by score
results = [(decl_id_map[i], scores[i]) for i in top_k_indices]
sort results by score descending
return results
```

### 4.3 NeuralChannel

The neural channel integrates into the pipeline as a retrieval function with the same signature pattern as existing channels.

#### neural_retrieve(ctx, query_text, limit)

- REQUIRES: `ctx` is a valid `PipelineContext` with a loaded `EmbeddingIndex` and `NeuralEncoder`. `query_text` is a non-empty string. `limit` is in [1, 200].
- ENSURES: Encodes `query_text` via the encoder. Searches the embedding index for top-`limit` results. Returns a list of `(declaration_id, score)` pairs.

> **Given** a pipeline context with neural channel available
> **When** `neural_retrieve(ctx, "nat -> nat -> nat", limit=32)` is called
> **Then** returns up to 32 `(decl_id, score)` pairs ranked by embedding similarity

### 4.4 Neural Channel Availability

The neural channel is available when all four conditions hold:

1. A model checkpoint exists at the well-known model path
2. A vocabulary file exists at the well-known vocabulary path
3. The `embeddings` table in the index database contains rows
4. The `neural_model_hash` in `index_meta` matches the current model's hash

When any condition fails, the neural channel marks itself as unavailable. The pipeline proceeds with existing channels. No error is raised.

#### check_availability(db_path, model_path, vocabulary_path)

- REQUIRES: `db_path` points to a valid index database. `model_path` is the well-known model checkpoint path. `vocabulary_path` is the well-known vocabulary file path.
- ENSURES: Returns `true` if all four conditions above are met. Returns `false` otherwise.

> **Given** no model checkpoint exists at the well-known path
> **When** `check_availability` is called
> **Then** returns `false` — search operates with existing channels only

> **Given** model checkpoint exists but vocabulary file does not
> **When** `check_availability` is called
> **Then** returns `false` — encoder requires the closed vocabulary for compatible tokenization

> **Given** model checkpoint and vocabulary exist but `neural_model_hash` in index_meta differs
> **When** `check_availability` is called
> **Then** returns `false` — embeddings are stale from a different model version

### 4.5 Embedding Write Path (Indexing)

#### compute_embeddings(reader, encoder, writer)

- REQUIRES: `reader` provides access to all declarations in the index. `encoder` is a loaded `NeuralEncoder`. `writer` provides write access to the `embeddings` table and `index_meta`.
- ENSURES: For each declaration, encodes `declarations.statement` via the encoder and inserts the vector into the `embeddings` table. Writes `neural_model_hash` to `index_meta`. All writes are within a single transaction.
- On encoder failure for a single declaration: skips that declaration, logs a warning, continues. The `embeddings` table may have fewer rows than `declarations` — this is acceptable.

Algorithm:
```
1. Load encoder model
2. Read all declaration (id, statement) pairs from the database
3. For each batch of 64 declarations:
     a. encode_batch(statements) → vectors
     b. Serialize each vector as raw float32 bytes (768 × 4 = 3,072 bytes)
     c. Batch-insert into embeddings table: (decl_id, vector_blob)
4. Write model_hash to index_meta: ('neural_model_hash', encoder.model_hash())
5. Commit transaction
```

> **Given** an index with 50,000 declarations and a loaded encoder
> **When** `compute_embeddings` runs on CPU
> **Then** embeddings are computed in under 10 minutes and stored in the database

### 4.6 Embedding Read Path (Startup)

#### load_embeddings(reader)

- REQUIRES: `reader` provides access to the `embeddings` table.
- ENSURES: Returns `(embedding_matrix, decl_id_map)` where `embedding_matrix` is a contiguous float32 array of shape `[N, 768]` and `decl_id_map` is an integer array mapping row indices to declaration IDs. Returns `(None, None)` if the `embeddings` table is empty or does not exist.

> **Given** an index with 50,000 embeddings
> **When** `load_embeddings` is called
> **Then** returns a `(50000, 768)` matrix and a 50,000-element ID map in under 1 second

### 4.7 Neural Query Text Construction

Different search operations produce different query text for the encoder:

| Pipeline function | Neural query text |
|-------------------|------------------|
| `search_by_type` | The `type_expr` string as provided by the caller |
| `search_by_structure` | The `expression` string as provided by the caller |
| `search_by_symbols` | Space-joined symbol names from the `symbols` list |
| `search_by_name` | Not used — neural channel is skipped |

### 4.8 Model Checkpoint and Vocabulary Paths

The model checkpoint and vocabulary are located at:

```
<data_dir>/models/neural-premise-selector.onnx
<data_dir>/models/coq-vocabulary.json
```

Where `<data_dir>` follows platform conventions:
- Linux: `~/.local/share/poule/`
- macOS: `~/Library/Application Support/poule/`

When both files exist, `NeuralEncoder.load` uses the vocabulary file for tokenization. When only the model exists, it falls back to CodeBERT's tokenizer.

## 5. Data Model

### Embedding Vector

| Property | Constraint |
|----------|-----------|
| Dimensionality | 768 |
| Element type | float32 |
| Normalization | L2-normalized (unit length) |
| Storage format | Raw bytes (768 × 4 = 3,072 bytes per vector) |

### In-Memory Matrix

| Property | Constraint |
|----------|-----------|
| Layout | Contiguous row-major float32 |
| Shape | `[N, 768]` where N = number of declarations with embeddings |
| Memory | N × 768 × 4 bytes (50K → ~150MB, 200K → ~600MB) |

## 6. Interface Contracts

### Neural Channel → Pipeline

| Property | Value |
|----------|-------|
| Input | Query text (string) + limit (integer) |
| Output | List of `(declaration_id, cosine_similarity_score)` pairs, sorted by descending score |
| Guarantees | Results are exact (brute-force search). Scores are cosine similarities in [-1, 1]. |
| Error strategy | If encoder fails on query text, return empty list and log warning. Never propagate encoder errors as user-facing errors. |
| Concurrency | Encoder is stateless and thread-safe. EmbeddingIndex is read-only after construction and thread-safe. |

### Neural Channel → Storage

| Property | Value |
|----------|-------|
| Read | `embeddings` table (all rows at startup), `index_meta` key `neural_model_hash` |
| Write | `embeddings` table (during indexing), `index_meta` key `neural_model_hash` (during indexing) |

## 7. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Model checkpoint not found | `ModelNotFoundError` | Neural channel unavailable; pipeline continues with existing channels |
| Model file corrupted or invalid ONNX | `ModelLoadError` | Neural channel unavailable; pipeline continues with existing channels |
| Model hash mismatch (stale embeddings) | No error | Neural channel unavailable; pipeline continues with existing channels |
| Encoder fails on single declaration during indexing | Warning logged | Declaration skipped; other declarations proceed |
| Encoder fails on query text | Warning logged | Neural channel returns empty list for this query; pipeline continues with other channels |
| Embeddings table missing or empty | No error | Neural channel unavailable; pipeline continues with existing channels |

All neural channel failures are non-fatal. The pipeline always produces results from existing channels.

## 8. Non-Functional Requirements

| Metric | Target |
|--------|--------|
| Single-item encoding latency (CPU, INT8) | < 10ms |
| Batch encoding latency (64 items, CPU, INT8) | < 500ms |
| Cosine search latency (50K items) | < 5ms |
| End-to-end neural channel query (encode + search) | < 100ms |
| Embedding startup loading (50K items) | < 1 second |
| Embedding computation (50K items, CPU) | < 10 minutes |
| In-memory footprint (50K embeddings) | ~150MB |

## 9. Examples

### Pipeline startup with neural channel

```
reader = IndexReader.open("/path/to/index.db")
# ... existing startup (histograms, inverted index, etc.) ...

# Neural channel startup
model_path = "<data_dir>/models/neural-premise-selector.onnx"
vocabulary_path = "<data_dir>/models/coq-vocabulary.json"
if file_exists(model_path) and file_exists(vocabulary_path):
    encoder = NeuralEncoder.load(model_path, vocabulary_path)
    stored_hash = reader.get_meta("neural_model_hash")
    if stored_hash == encoder.model_hash():
        matrix, id_map = load_embeddings(reader)
        if matrix is not None:
            embedding_index = EmbeddingIndex.build(matrix, id_map)
            ctx.neural_encoder = encoder
            ctx.embedding_index = embedding_index
            # Neural channel available
```

### search_by_type with neural channel

```
Given: type_expr = "nat -> nat -> nat", neural channel available

When: search_by_type(ctx, type_expr, limit=20)

Then:
  1. Structural channel: WL screen + fine-rank → structural results
  2. Symbol channel: MePo on {nat} → symbol results
  3. Lexical channel: FTS on "nat" → lexical results
  4. Neural channel: encode("nat -> nat -> nat") → search(vector, 50) → neural results
  5. rrf_fuse([structural, symbol, lexical, neural], k=60) → fused top 20
```

### Graceful degradation

```
Given: no model checkpoint exists

When: search_by_type(ctx, "nat -> nat -> nat", limit=20)

Then:
  1. Structural channel → structural results
  2. Symbol channel → symbol results
  3. Lexical channel → lexical results
  4. Neural channel skipped (not available)
  5. rrf_fuse([structural, symbol, lexical], k=60) → fused top 20
  (identical behavior to pre-neural-channel system)
```

## 10. Language-Specific Notes (Python)

- Use `onnxruntime` for INT8 model inference. `InferenceSession` with `CPUExecutionProvider`.
- Use `numpy` for the embedding matrix and cosine search (`np.dot`, `np.argpartition`).
- Serialize embeddings as `numpy.ndarray.tobytes()` for SQLite BLOB storage. Deserialize with `numpy.frombuffer(blob, dtype=np.float32)`.
- `NeuralEncoder` as a class wrapping `onnxruntime.InferenceSession`.
- `EmbeddingIndex` as a class holding a `numpy.ndarray` and an ID map.
- Thread safety: `onnxruntime.InferenceSession` is thread-safe for concurrent `run()` calls.
- Package location: `src/poule/neural/`.
