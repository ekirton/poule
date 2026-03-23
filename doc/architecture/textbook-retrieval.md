# Textbook Retrieval

Technical design for the educational content retrieval system: HTML chunking, embedding computation, vector storage, similarity search, and integration into the MCP server and slash commands.

**Feature**: [Textbook Content Retrieval](../features/textbook-retrieval.md)

---

## Component Diagram

```
Build path (offline, Docker build)          Query path (online)

Software Foundations HTML                   MCP Server
  │ (7 volumes, ~150 pages)                   │
  │                                           │ education_context(query)
  ▼                                           ▼
HTML Chunker                                EducationRAG
  │                                           │
  │ section-based chunks                      ├─ encode query
  ▼                                           │     │
Education Storage (SQLite)                    │     ▼
  │ chunks table                              │   EducationEncoder (all-MiniLM, INT8, CPU)
  │                                           │     │
  │ read chunk texts                          │     │ cosine similarity
  ▼                                           │     ▼
EducationEncoder                              │   EmbeddingIndex (in-memory numpy)
  │                                           │     │
  │ encode each chunk                         │     │ top-k results
  │ via all-MiniLM (INT8, CPU)                │     ▼
  │                                           │   Chunk metadata lookup
  │ write embeddings                          │
  ▼                                           ├─ FTS5 fallback (optional)
Education Storage (SQLite)                    │
  education_embeddings table ◄────────────────┘
                                              ▼
                                        Formatted results
                                        (text, code_blocks, citation, browser_path)
```

## Separate Database

The education system uses its own SQLite database (`education.db`), separate from the Coq declaration index (`index.db`). Rationale:

- Different release cadence: SF versions change independently of Coq library versions.
- Different data model: chunks with prose text, not Coq declarations with type expressions and dependency graphs.
- Simpler lifecycle: the education DB can be rebuilt from HTML without affecting the Coq index.

The education DB is bundled in the Docker container at `/data/education.db`.

## HTML Chunker

### Input

The seven Software Foundations volumes, distributed as coqdoc-generated XHTML files under `software-foundations/{lf,plf,vfa,qc,secf,slf,vc}/`. Content files are identified by excluding non-content pages: `index.html`, `toc.html`, `coqindex.html`, `deps.html`.

### Chunking Strategy

Each HTML page is parsed with BeautifulSoup (available via the `alectryon` dependency). The chunker:

1. Extracts `<div id="main">` and discards `<div id="header">`, `<div id="footer">`, `<div class="togglescript">`, and `<script>` elements.
2. Extracts volume title from `<div class="booktitleinheader">` and chapter name from `<h1 class="libtitle">`.
3. Walks the content, splitting on `<h1-h4 class="section">` boundaries and tracking the section hierarchy.
4. Within each section, accumulates `<div class="doc">` (prose) and `<div class="code">` (Coq code) blocks.
5. Converts prose to plain text (stripping tags, preserving inline code content).
6. Extracts Coq code blocks as separate strings, preserving whitespace structure.

### Chunk Size Control

Target: ~1000 tokens per chunk.

- If a section exceeds ~1000 tokens, split at `<div class="doc">` boundaries (paragraph-level).
- If a section is under 100 tokens, merge with the following section.
- Exercise sections (marked with `<h4 class="section">Exercise:`) are kept as separate chunks even if small, as they are semantically distinct.

### Metadata

Each chunk carries:

| Field | Source |
|-------|--------|
| `volume` | Directory name (`lf`, `plf`, etc.) |
| `volume_title` | `booktitleinheader` text |
| `chapter` | `<h1 class="libtitle">` text |
| `chapter_file` | HTML filename (e.g., `Basics.html`) |
| `section_title` | Most recent `<h1-h4 class="section">` text |
| `section_path` | Breadcrumb of all enclosing section titles |
| `anchor_id` | `<a id="lab##">` preceding the section heading |

## Encoder

### Model

all-MiniLM-L6-v2, INT8 quantized via ONNX Runtime.

| Property | Value |
|----------|-------|
| Architecture | 6-layer MiniLM (distilled from BERT) |
| Embedding dimension | 384 |
| Max sequence length | 256 tokens |
| Model size (INT8 ONNX) | ~23 MB |
| Tokenizer | WordPiece (shipped as `tokenizer.json`) |
| Pooling | Mean pooling over token embeddings |
| Normalization | L2-normalized output vectors |

The encoder is loaded from shipped files (`/data/models/education/encoder.onnx` and `/data/models/education/tokenizer.json`). No network access is required. The `tokenizers` library (pure Rust, ~6MB wheel) provides `Tokenizer.from_file()` for offline tokenizer loading, avoiding the full `transformers` dependency.

### Why all-MiniLM over BGE-large

The corpus is ~1000 chunks. At this scale:
- Brute-force cosine search completes in <10ms regardless of embedding dimension.
- The quality delta between 384-dim and 1024-dim embeddings is marginal for natural language pedagogical text.
- all-MiniLM adds ~23MB to the container; BGE-large adds ~335MB — a 15x size difference with no meaningful retrieval improvement.

## Storage Schema

```sql
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume TEXT NOT NULL,
    volume_title TEXT NOT NULL,
    chapter TEXT NOT NULL,
    chapter_file TEXT NOT NULL,
    section_title TEXT NOT NULL,
    section_path TEXT NOT NULL,    -- JSON array
    anchor_id TEXT,
    text TEXT NOT NULL,
    code_blocks TEXT,              -- JSON array
    token_count INTEGER NOT NULL
);

CREATE TABLE education_embeddings (
    chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    vector BLOB NOT NULL,         -- float32 array, 384 values = 1536 bytes
    PRIMARY KEY (chunk_id)
);

CREATE TABLE education_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, section_title, chapter,
    content=chunks, content_rowid=id,
    tokenize='porter unicode61'
);
```

Metadata keys: `schema_version`, `model_hash`, `sf_version`, `build_date`, `chunk_count`.

## Retrieval

### Vector Search

At server startup, `EducationRAG` loads the embedding matrix and chunk ID map from `education_embeddings` into an in-memory `EmbeddingIndex` (same class used by the neural retrieval channel — dimension-agnostic). Query encoding and cosine search follow the same pattern as `NeuralEncoder.encode()` + `EmbeddingIndex.search()`.

### FTS5 Fallback

The `chunks_fts` table provides keyword search for cases where semantic search misses exact-match queries (e.g., "simpl tactic"). This is a P2 feature; when implemented, results from vector search and FTS5 are combined using simple RRF.

### Volume Filtering

When the user specifies `--volume lf`, the search filters the embedding matrix to rows matching the requested volume before computing cosine similarity.

## MCP Integration

### Tool Definition

```typescript
education_context(
  query: string,              // natural-language query
  limit: number = 3,          // max passages to return (max: 10)
  volume: string | undefined  // optional volume filter
) → EducationResult[]
```

Each `EducationResult` contains: `text`, `code_blocks`, `location` (human-readable breadcrumb), `browser_path` (local file path with anchor), `score`.

### Server Wiring

- `_ServerContext` gains an `education_rag: EducationRAG | None` field.
- `_init_context()` loads the education DB if present; the server starts normally if it is absent.
- `_dispatch_tool()` routes `education_context` to `handle_education_context()`.

## Slash Command Integration

### `/textbook`

The `/textbook` command calls `education_context` and formats results for the user. Each result includes the passage text, Coq code blocks, a source citation, and a browser-openable file path.

### `/explain-proof` and `/explain-error`

After completing their primary workflow, these commands call `education_context` with a query describing the proof strategy or error category. If results are returned, they append a brief annotation (1-2 sentences + citation + "Use `/textbook` to explore this topic in Software Foundations.").

## Docker Deployment

### Build-Time

1. Model files (`encoder.onnx`, `tokenizer.json`) are COPY'd to `/data/models/education/`.
2. SF HTML is COPY'd to `/poule/software-foundations/`.
3. The build pipeline runs to produce `/data/education.db`.

### Runtime

The entrypoint symlinks `/poule/software-foundations` to `$HOME/software-foundations` so the SF HTML is accessible in the user's persistent home directory (same pattern as the examples/ symlink). The host can browse chapters at `~/poule-home/software-foundations/lf/Basics.html`.

## Module Structure

```
src/Poule/education/
    __init__.py       # EducationRAG facade
    models.py         # Chunk, ChunkMetadata, EducationSearchResult
    chunker.py        # HTML → Chunk[]
    encoder.py        # EducationEncoder (all-MiniLM ONNX wrapper)
    storage.py        # SQLite read/write
    build.py          # Offline build pipeline + CLI entry point
    evaluate.py       # Retrieval evaluation harness
```
