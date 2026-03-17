# Component Boundaries

System-level view of all components, their boundaries, and the dependency graph.

---

## Component Taxonomy

| Component | Owns | Architecture Doc |
|-----------|------|-----------------|
| Coq Library Extraction | Declaration extraction, tree conversion, normalization, index construction | [coq-extraction.md](coq-extraction.md), [coq-normalization.md](coq-normalization.md) |
| Storage | SQLite schema, index metadata, FTS5 index | [storage.md](storage.md) |
| Retrieval Pipeline | Retrieval channels, metric computation, fusion | [retrieval-pipeline.md](retrieval-pipeline.md) |
| MCP Server | Protocol translation, input validation, error handling, response formatting, proof state serialization | [mcp-server.md](mcp-server.md) |
| CLI | Command-line interface for indexing, search, and proof replay, output formatting | [cli.md](cli.md) |
| Proof Session Manager | Session lifecycle, Coq backend process management, tactic dispatch, state caching, premise extraction | [proof-session.md](proof-session.md) |
| Claude Code / LLM | Intent interpretation, query formulation, result filtering, explanation | External (not owned by this project) |

### Cross-Cutting Concerns

| Concern | Owns | Architecture Doc |
|---------|------|-----------------|
| Coq Expression Normalization | Tree normalization pipeline, CSE reduction | [coq-normalization.md](coq-normalization.md) |
| Proof Serialization | JSON serialization of proof types, schema versioning, determinism, diff computation | [proof-serialization.md](proof-serialization.md) |

Proof Serialization is used by the MCP Server (for formatting responses) and the Proof Session Manager (for trace export). It is not a standalone runtime component — it is a shared serialization contract.

Coq Backend Processes (one per session) are owned by the Proof Session Manager. They appear as a separate box in the dependency graph because they are separate OS processes, but they are not an independent component — their lifecycle is fully managed by the session manager.

## Dependency Graph

```
Claude Code / LLM          Terminal user
  │                           │
  │ MCP tool calls (stdio)    │ CLI subcommands
  ▼                           ▼
MCP Server                  CLI
  │         │                 │         │
  │ search  │ proof           │ search  │ proof
  │ queries │ session ops     │ queries │ replay
  ▼         ▼                 ▼         ▼
Retrieval   Proof Session   Retrieval  Proof Session
Pipeline    Manager         Pipeline   Manager
  │           │                │
  │ SQLite    │ coq-lsp /      │ SQLite
  │ queries   │ SerAPI         │ queries
  ▼           ▼                ▼
Storage     Coq Backend      Storage
(SQLite)    Processes        (SQLite)
  ▲         (per-session)
  │
  │ Writes during indexing
  │
Coq Library Extraction
  │
  │ coq-lsp / SerAPI
  ▼
Compiled .vo files (external)
```

Note: The Proof Session Manager and the Search Backend (Retrieval Pipeline + Storage) are independent at runtime. Proof interaction does not require a search index, and search does not require proof sessions.

## Boundary Contracts

### Claude Code → MCP Server

| Property | Value |
|----------|-------|
| Transport | stdio |
| Protocol | MCP (Model Context Protocol) |
| Direction | Request-response |
| Search tools | `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules` |
| Proof tools (P0) | `open_proof_session`, `close_proof_session`, `list_proof_sessions`, `observe_proof_state`, `get_proof_state_at_step`, `extract_proof_trace`, `submit_tactic`, `step_backward`, `step_forward`, `get_proof_premises`, `get_step_premises` |
| Proof tools (P1) | `submit_tactic_batch` |
| Search response types | `SearchResult`, `LemmaDetail`, `Module`, structured errors |
| Proof response types | `ProofState`, `ProofTrace`, `PremiseAnnotation`, `Session`, structured errors (see [data-models/proof-types.md](data-models/proof-types.md)) |
| Error contract | See [mcp-server.md](mcp-server.md) § Error Contract |

### CLI → Proof Session Manager

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process), async via `asyncio.run()` |
| Direction | Request-response |
| Input | File path + proof name (replay-proof command) |
| Output | ProofTrace, optionally list[PremiseAnnotation], or structured errors |
| Shared with | MCP Server → Proof Session Manager (same `SessionManager` API) |
| Lifecycle | Session created and closed within a single command invocation |

### CLI → Retrieval Pipeline

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | Parsed and validated query parameters (identical to MCP server) |
| Output | Ranked result lists with scores |
| Shared with | MCP Server → Retrieval Pipeline (same `PipelineContext` and pipeline functions) |

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

### MCP Server → Proof Session Manager

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | Session ID + operation-specific parameters (tactic string, step index, etc.) |
| Output | ProofState, ProofTrace, PremiseAnnotation, Session metadata, or structured errors |
| Statefulness | The session manager is stateful — each session maintains independent state across calls |

### Proof Session Manager → Coq Backend Processes

| Property | Value |
|----------|-------|
| Mechanism | Process-level communication (stdin/stdout) via coq-lsp or SerAPI protocol |
| Direction | Bidirectional, stateful |
| Cardinality | One backend process per active session |
| Lifecycle | Process spawned on session open, terminated on session close or timeout |
| Crash handling | Backend crash is detected and reported as `BACKEND_CRASHED`; other sessions unaffected |

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
| [cli.md](cli.md) | [specification/cli.md](../../specification/cli.md) |
| [proof-session.md](proof-session.md) | *(Phase 2 — specifications not yet created)* |
| [proof-serialization.md](proof-serialization.md) | *(Phase 2 — specifications not yet created)* |
| [data-models/proof-types.md](data-models/proof-types.md) | *(Phase 2 — specifications not yet created)* |
