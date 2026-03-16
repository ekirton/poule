# Component Boundaries

System-level view of all components, their boundaries, and the dependency graph.

---

## Component Taxonomy

| Component | Owns | Architecture Doc |
|-----------|------|-----------------|
| Coq Library Extraction | Declaration extraction, tree conversion, normalization, index construction | [coq-extraction.md](coq-extraction.md), [coq-normalization.md](coq-normalization.md) |
| Storage | SQLite schema, index metadata, FTS5 index | [storage.md](storage.md) |
| Retrieval Pipeline | Retrieval channels, metric computation, fusion | [retrieval-pipeline.md](retrieval-pipeline.md) |
| MCP Server | Protocol translation, input validation, error handling, response formatting | [mcp-server.md](mcp-server.md) |
| Claude Code / LLM | Intent interpretation, query formulation, result filtering, explanation | External (not owned by this project) |

## Dependency Graph

```
Claude Code / LLM
  │
  │ MCP tool calls (stdio)
  ▼
MCP Server
  │
  │ Internal function calls
  ▼
Retrieval Pipeline
  │
  │ SQLite queries
  ▼
Storage (SQLite database)
  ▲
  │ Writes during indexing
  │
Coq Library Extraction
  │
  │ coq-lsp / SerAPI
  ▼
Compiled .vo files (external)
```

## Boundary Contracts

### Claude Code → MCP Server

| Property | Value |
|----------|-------|
| Transport | stdio |
| Protocol | MCP (Model Context Protocol) |
| Direction | Request-response |
| Tools | `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules` |
| Response types | `SearchResult`, `LemmaDetail`, `Module`, structured errors |
| Error contract | See [mcp-server.md](mcp-server.md) § Error Contract |

### MCP Server → Retrieval Pipeline

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | Parsed and validated query parameters |
| Output | Ranked result lists with scores |

### Retrieval Pipeline → Storage

| Property | Value |
|----------|-------|
| Mechanism | SQLite queries |
| Direction | Read-only during online queries |
| Tables read | `declarations`, `dependencies`, `wl_vectors`, `symbol_freq`, `declarations_fts` |
| Assumptions | WL histograms loaded into memory at startup; SQLite queries for other data |

### Coq Library Extraction → Storage

| Property | Value |
|----------|-------|
| Mechanism | SQLite writes |
| Direction | Write-only during offline indexing |
| Tables written | All tables including `index_meta` |
| Assumptions | Exclusive write access during indexing; database is replaced atomically |

### MCP Server → Storage (index lifecycle)

| Property | Value |
|----------|-------|
| Mechanism | SQLite read of `index_meta` |
| Direction | Read-only on startup |
| Purpose | Schema version check, library version check |
| Phase 1 behavior | Validates `schema_version` only; library versions stored for informational purposes. Schema mismatch → `INDEX_VERSION_MISMATCH` error directing user to re-index manually. |
| Phase 2 behavior | Additionally validates `coq_version` and `mathcomp_version` against installed versions; mismatch → `INDEX_VERSION_MISMATCH` error. |

## Source-to-Specification Mapping

| Architecture Document | Produces Specifications |
|----------------------|----------------------|
| [data-models/](data-models/) | [specification/data-structures.md](../../specification/data-structures.md) |
| [coq-extraction.md](coq-extraction.md) | [specification/extraction.md](../../specification/extraction.md) |
| [coq-normalization.md](coq-normalization.md) | [specification/coq-normalization.md](../../specification/coq-normalization.md), [specification/cse-normalization.md](../../specification/cse-normalization.md) |
| [storage.md](storage.md) | [specification/storage.md](../../specification/storage.md) |
| [retrieval-pipeline.md](retrieval-pipeline.md) | [specification/pipeline.md](../../specification/pipeline.md), [specification/fusion.md](../../specification/fusion.md), [specification/channel-wl-kernel.md](../../specification/channel-wl-kernel.md), [specification/channel-mepo.md](../../specification/channel-mepo.md), [specification/channel-fts.md](../../specification/channel-fts.md), [specification/channel-ted.md](../../specification/channel-ted.md), [specification/channel-const-jaccard.md](../../specification/channel-const-jaccard.md) |
| [mcp-server.md](mcp-server.md) | [specification/mcp-server.md](../../specification/mcp-server.md) |
