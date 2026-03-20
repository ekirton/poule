# Component Boundaries

System-level view of all components, their boundaries, and the dependency graph.

---

## Component Taxonomy

| Component | Owns | Architecture Doc |
|-----------|------|-----------------|
| Coq Library Extraction | Declaration extraction, tree conversion, normalization, index construction | [coq-extraction.md](coq-extraction.md), [coq-normalization.md](coq-normalization.md) |
| Storage | SQLite schema, index metadata, FTS5 index | [storage.md](storage.md) |
| Retrieval Pipeline | Retrieval channels, metric computation, fusion | [retrieval-pipeline.md](retrieval-pipeline.md) |
| MCP Server | Protocol translation, input validation, error handling, response formatting, proof state serialization, visualization dispatch | [mcp-server.md](mcp-server.md) |
| CLI | Command-line interface for indexing, search, proof replay, and batch extraction, output formatting | [cli.md](cli.md) |
| Proof Session Manager | Session lifecycle, Coq backend process management, tactic dispatch, state caching, premise extraction | [proof-session.md](proof-session.md) |
| Extraction Campaign Orchestrator | Project/file enumeration, per-proof extraction loop, failure isolation, streaming output, summary statistics | [extraction-campaign.md](extraction-campaign.md) |
| Mermaid Renderer | Proof state, proof tree, dependency, and sequence diagram generation as Mermaid syntax | [mermaid-renderer.md](mermaid-renderer.md) |
| Proof Search Engine | Best-first tree search over tactic candidates, candidate generation (LLM + solver + few-shot), state caching, diversity filtering | [proof-search-engine.md](proof-search-engine.md) |
| Fill Admits Orchestrator | Admit location in .v files, per-admit session lifecycle, proof search invocation, script assembly | [fill-admits-orchestrator.md](fill-admits-orchestrator.md) |
| Neural Training Pipeline | Bi-encoder training, evaluation, fine-tuning, quantization from extracted proof traces | [neural-training.md](neural-training.md) |
| Hammer Automation | Multi-strategy CoqHammer invocation (hammer → sauto → qauto) within proof sessions | [hammer-automation.md](hammer-automation.md) |
| Vernacular Introspection | Single `coq_query` tool dispatching Print/Check/About/Locate/Search/Compute/Eval to Coq backends | [vernacular-introspection.md](vernacular-introspection.md) |
| Assumption Auditing | Axiom dependency extraction, classification, batch auditing, and comparison via `Print Assumptions` | [assumption-auditing.md](assumption-auditing.md) |
| Universe Inspection | Universe constraint retrieval, graph construction, inconsistency diagnosis, polymorphic inspection | [universe-inspection.md](universe-inspection.md) |
| Typeclass Debugging | Instance listing, resolution tracing, failure explanation, conflict detection via typeclass debug commands | [typeclass-debugging.md](typeclass-debugging.md) |
| Deep Dependency Analysis | Transitive closure, impact analysis, cycle detection, module-level summaries over dependency graph | [deep-dependency-analysis.md](deep-dependency-analysis.md) |
| Literate Documentation | Alectryon subprocess adapter for interactive proof documentation generation | [literate-documentation.md](literate-documentation.md) |
| Code Extraction Management | Coq code extraction to OCaml/Haskell/Scheme with preview, write, and failure diagnosis | [code-extraction-management.md](code-extraction-management.md) |
| Independent Proof Checking | coqchk subprocess adapter for independent verification of compiled .vo files | [independent-proof-checking.md](independent-proof-checking.md) |
| Build System Integration | Build system detection, project file generation, build execution, package/dependency management via coq_makefile/dune/opam | [build-system-integration.md](build-system-integration.md) |
| Compatibility Analysis | Dependency scanning, opam metadata resolution, constraint parsing, conflict detection, explanation building, resolution suggestion | [compatibility-analysis.md](compatibility-analysis.md) |
| Notation Inspection | Notation lookup, scope inspection, precedence/associativity extraction, ambiguity resolution | [notation-inspection.md](notation-inspection.md) |
| Tactic Documentation | Tactic lookup, comparison, contextual suggestion, hint database inspection | [tactic-documentation.md](tactic-documentation.md) |
| Convoy Pattern Analyzer | Dependent-destruction diagnosis, technique selection, revert-order computation, convoy/Equations boilerplate generation | [convoy-pattern-assistant.md](convoy-pattern-assistant.md) |
| Setoid Rewrite Analyzer | Setoid rewrite error parsing, missing Proper instance identification, instance existence checking, signature generation, binder-rewrite detection | [setoid-rewriting-assistant.md](setoid-rewriting-assistant.md) |
| Claude Code / LLM | Intent interpretation, query formulation, result filtering, explanation | External (not owned by this project) |

### Cross-Cutting Concerns

| Concern | Owns | Architecture Doc |
|---------|------|-----------------|
| Coq Expression Normalization | Tree normalization pipeline, CSE reduction | [coq-normalization.md](coq-normalization.md) |
| Proof Serialization | JSON serialization of proof types, schema versioning, determinism, diff computation | [proof-serialization.md](proof-serialization.md) |
| Extraction Output Format | JSON Lines serialization of extraction records, provenance metadata, record type discrimination | [extraction-output.md](extraction-output.md) |
| Extraction Checkpointing | Incremental re-extraction, campaign resumption, checkpoint file management (P1) | [extraction-checkpointing.md](extraction-checkpointing.md) |
| Extraction Reporting | Quality reports, scope filtering, benchmark generation, ML export (P1/P2) | [extraction-reporting.md](extraction-reporting.md) |
| Extraction Dependency Graph | Theorem-level dependency graph extraction from premise annotations (P1) | [extraction-dependency-graph.md](extraction-dependency-graph.md) |
| Neural Retrieval Channel | Neural embedding computation, vector search, integration into retrieval pipeline | [neural-retrieval.md](neural-retrieval.md) |

Proof Serialization is used by the MCP Server (for formatting responses) and the Proof Session Manager (for trace export). It is not a standalone runtime component — it is a shared serialization contract.

Extraction Output Format extends Proof Serialization concepts to the batch extraction context. It defines the JSON Lines stream structure, record type discrimination, and provenance metadata. It is used by the Extraction Campaign Orchestrator.

Coq Backend Processes (one per session) are owned by the Proof Session Manager. They appear as a separate box in the dependency graph because they are separate OS processes, but they are not an independent component — their lifecycle is fully managed by the session manager.

## Dependency Graph

```
Claude Code / LLM          Terminal user
  │                           │                    │
  │ MCP tool calls (stdio)    │ CLI subcommands    │ CLI (Phase 3)
  ▼                           ▼                    ▼
MCP Server                  CLI                  CLI
  │     │       │     │       │         │          │
  │ src │ proof │ viz │ prf   │ search  │ proof    │ batch
  │ qry │ sess  │     │ srch  │ queries │ replay   │ extraction
  ▼     ▼       ▼     ▼       ▼         ▼          ▼
Retr.  Proof  Merm. Proof   Retr.     Proof    Extraction Campaign
Pipe.  Sess.  Rend. Search  Pipe.     Session  Orchestrator
  │    Mgr     │    Engine    │       Manager     │
  │ SQL  │     │ pure │       │ SQL     │        │ session ops
  │ qry  │     │ fn   │       │ qry     │        │ (reuse)
  ▼      ▼     │      │       ▼         │        │
Stor.  Coq   (no     │      Stor.      │        │
(SQL)  Back.  deps)   │     (SQL)       │        │
  ▲    Procs          │                 ▼        ▼
  │    (per-          │            Proof Session Manager
  │     ses.)         │                  │
  │                   │                  │ coq-lsp / SerAPI
  │                   │                  ▼
  │ Writes during     │            Coq Backend Processes
  │ indexing          │            (per-session)
  │                   │
Coq Library Extr.     ├─ tactic verify → Proof Session Manager
  │                   ├─ premises (opt) → Retrieval Pipeline
  │ coq-lsp/SerAPI    └─ few-shot (opt) → Training Data (Phase 3)
  ▼
Compiled .vo files           Fill Admits Orchestrator
(external)                     ├─ search → Proof Search Engine
                               └─ sessions → Proof Session Manager

                             JSON Lines output
                             (Phase 3 batch output)
```

Note: The four subsystems — search, proof interaction, extraction, and proof search — have distinct dependency patterns. Search and proof interaction are independent of each other. Extraction depends on the Proof Session Manager but not search. Proof search is the first component that bridges search and proof interaction at runtime: it uses the Proof Session Manager for tactic verification and optionally uses the Retrieval Pipeline for premise retrieval. The Fill Admits Orchestrator depends on both the Proof Search Engine and the Proof Session Manager. The Mermaid Renderer is a pure function component with no runtime dependencies.

The Neural Training Pipeline is a batch-mode component invoked via CLI. It reads extracted training data (JSON Lines from Phase 3) and the SQLite index (for premise corpus), and produces model checkpoints. The Neural Retrieval Channel is a cross-cutting concern: at indexing time it computes embeddings (extending Coq Library Extraction → Storage); at query time it provides a retrieval channel (extending the Retrieval Pipeline). Both are optional — all other components function without them.

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
| Visualization tools | `visualize_proof_state`, `visualize_proof_tree`, `visualize_dependencies`, `visualize_proof_sequence` |
| Search response types | `SearchResult`, `LemmaDetail`, `Module`, structured errors |
| Proof response types | `ProofState`, `ProofTrace`, `PremiseAnnotation`, `Session`, structured errors (see [data-models/proof-types.md](data-models/proof-types.md)) |
| Visualization response types | Mermaid syntax strings, node counts, truncation flags, structured errors |
| Proof search tools | `proof_search`, `fill_admits` |
| Proof search response types | `SearchResult` (success/failure with proof script or partial), `FillAdmitsResult` (per-admit outcomes with modified script) |
| Error contract | See [mcp-server.md](mcp-server.md) § Error Contract |

### MCP Server → Proof Search Engine

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response (may be long-running, up to timeout) |
| Input | Session ID + search parameters (timeout, max_depth, max_breadth) |
| Output | SearchResult (success with proof script or failure with partial progress and stats) |
| Dependencies | Proof Session Manager (for tactic verification), Retrieval Pipeline (optional, for premise retrieval), Training Data (optional, for few-shot context) |

### MCP Server → Fill Admits Orchestrator

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response (long-running: timeout_per_admit × number of admits) |
| Input | File path + search parameters (timeout_per_admit, max_depth, max_breadth) |
| Output | FillAdmitsResult (per-admit outcomes, modified script) |
| Dependencies | Proof Search Engine, Proof Session Manager |

### Proof Search Engine → Proof Session Manager

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process), reuses same `SessionManager` API as MCP Server |
| Direction | Request-response |
| Operations used | `observe_proof_state`, `submit_tactic`, `step_backward` (for backtracking during search) |
| Statefulness | Search operates on an existing session; does not create or close sessions |
| Concurrency | Search serializes tactic submissions — one at a time on the session |

### Proof Search Engine → Retrieval Pipeline (optional)

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Operations used | `search_by_type`, `search_by_symbols` (for premise retrieval) |
| Availability | Optional; search proceeds without premises when no index is available |

### Fill Admits Orchestrator → Proof Session Manager

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Operations used | `open_proof_session`, `step_forward`, `close_proof_session` |
| Lifecycle | One session per admit; created and closed within per-admit loop iteration |

### Fill Admits Orchestrator → Proof Search Engine

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | Session ID (positioned at admit) + search parameters |
| Output | SearchResult |

### CLI → Proof Session Manager (proof replay)

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process), async via `asyncio.run()` |
| Direction | Request-response |
| Input | File path + proof name (replay-proof command) |
| Output | ProofTrace, optionally list[PremiseAnnotation], or structured errors |
| Shared with | MCP Server → Proof Session Manager (same `SessionManager` API) |
| Lifecycle | Session created and closed within a single command invocation |

### CLI → Extraction Campaign Orchestrator

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response (blocking, long-running) |
| Input | List of project directories, extraction options (scope filter, output path, incremental flag) |
| Output | JSON Lines file written to output path; exit code 0 on success, 1 on error |
| Lifecycle | Campaign runs to completion within a single CLI invocation |

### Extraction Campaign Orchestrator → Proof Session Manager

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process), reuses same `SessionManager` API as MCP Server and CLI proof replay |
| Direction | Request-response |
| Input | File path + theorem name (per-proof extraction) |
| Output | ProofTrace + list[PremiseAnnotation], or structured errors |
| Shared with | MCP Server → Proof Session Manager, CLI → Proof Session Manager (same API surface) |
| Lifecycle | One session per proof; session created, proof replayed and extracted, session closed within per-proof loop iteration |
| Failure contract | Backend crash, tactic failure, timeout → ExtractionError record; orchestrator continues with next proof |

### CLI → Retrieval Pipeline

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | Parsed and validated query parameters (identical to MCP server) |
| Output | Ranked result lists with scores |
| Shared with | MCP Server → Retrieval Pipeline (same `PipelineContext` and pipeline functions) |

### MCP Server → Mermaid Renderer

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response (pure function, no state) |
| Input | ProofState, ProofTrace, or dependency adjacency list + configuration (detail level, max depth, max nodes) |
| Output | Mermaid syntax string(s) |
| Dependencies | None — the renderer is a pure function with no external dependencies |
| Visualization tools | `visualize_proof_state`, `visualize_proof_tree`, `visualize_dependencies`, `visualize_proof_sequence` |

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
| Phase 2 behavior | Additionally validates `coq_version` and `library_versions` against installed versions; mismatch → `INDEX_VERSION_MISMATCH` error. |

### Retrieval Pipeline → Neural Retrieval Channel (optional)

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response |
| Input | Query text (pretty-printed Coq expression or space-joined symbol names) |
| Output | Ranked list of (declaration_id, cosine_similarity_score) pairs |
| Availability | Optional; pipeline proceeds with existing channels when neural channel is unavailable |
| Latency budget | < 100ms per query on CPU |

### Coq Library Extraction → Neural Retrieval Channel (optional)

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process), runs after standard indexing pass |
| Direction | Write-only (embeddings → Storage) |
| Input | All declaration statements from the SQLite index |
| Output | Embedding vectors written to `embeddings` table; model hash written to `index_meta` |
| Availability | Optional; runs only when a neural model checkpoint is present |

### Slash Command → Compatibility Analysis Engine

| Property | Value |
|----------|-------|
| Mechanism | In-process function calls, invoked by Claude Code during `/check-compat` execution |
| Direction | Request-response (each pipeline stage called independently) |
| Input | Project directory + optional hypothetical additions (Stage 1); intermediate data structures flow between stages |
| Output | DependencySet, ResolvedConstraintTree, ConflictSet or CompatibleSet, Explanations + Resolutions |
| Statefulness | Stateless — no data persists between invocations |

### Compatibility Analysis Engine → opam (subprocess)

| Property | Value |
|----------|-------|
| Mechanism | Subprocess invocation (fresh process per query) |
| Direction | Request-response |
| Commands used | `opam show` (package metadata), `opam list` (installed packages) |
| Read-only | Yes — no switch-modifying commands are ever invoked |
| Timeout | Configurable per subprocess; default 30 seconds |
| Caching | Results cached in-memory within a single analysis run |

### Compatibility Analysis Engine → Build System Adapter (shared logic)

| Property | Value |
|----------|-------|
| Mechanism | Shared build system detection function (in-process) |
| Direction | Call |
| Purpose | Locate `.opam`, `dune-project`, and `_CoqProject` files in the project directory |
| Scope | Detection only — does not invoke build execution or dependency management functions |

### CLI → Neural Training Pipeline

| Property | Value |
|----------|-------|
| Mechanism | Internal function calls (in-process) |
| Direction | Request-response (blocking, long-running) |
| Input | Paths to JSON Lines extraction files, index database, and model checkpoint (for fine-tune/evaluate/compare) |
| Output | Model checkpoint (.pt), quantized model (.onnx), or evaluation report; exit code 0 on success, 1 on error |
| Dependencies | Extracted training data (JSON Lines from Phase 3), SQLite index database (for premise corpus and symbolic comparison) |

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
| [proof-session.md](proof-session.md) | [specification/proof-session.md](../../specification/proof-session.md), [specification/coq-proof-backend.md](../../specification/coq-proof-backend.md) |
| [proof-serialization.md](proof-serialization.md) | [specification/proof-serialization.md](../../specification/proof-serialization.md) |
| [data-models/proof-types.md](data-models/proof-types.md) | [specification/data-structures.md](../../specification/data-structures.md) (proof types section) |
| [extraction-campaign.md](extraction-campaign.md) | [specification/extraction-campaign.md](../../specification/extraction-campaign.md) |
| [extraction-output.md](extraction-output.md) | [specification/extraction-output.md](../../specification/extraction-output.md) |
| [extraction-checkpointing.md](extraction-checkpointing.md) | [specification/extraction-checkpointing.md](../../specification/extraction-checkpointing.md) |
| [extraction-dependency-graph.md](extraction-dependency-graph.md) | [specification/extraction-dependency-graph.md](../../specification/extraction-dependency-graph.md) |
| [extraction-reporting.md](extraction-reporting.md) | [specification/extraction-reporting.md](../../specification/extraction-reporting.md) |
| [mermaid-renderer.md](mermaid-renderer.md) | specification/mermaid-renderer.md (pending) |
| [data-models/extraction-types.md](data-models/extraction-types.md) | [specification/data-structures.md](../../specification/data-structures.md) §4.8 |
| [proof-search-engine.md](proof-search-engine.md) | specification/proof-search-engine.md (pending) |
| [fill-admits-orchestrator.md](fill-admits-orchestrator.md) | specification/fill-admits-orchestrator.md (pending) |
| [neural-retrieval.md](neural-retrieval.md) | [specification/neural-retrieval.md](../../specification/neural-retrieval.md) |
| [neural-training.md](neural-training.md) | [specification/neural-training.md](../../specification/neural-training.md) |
| [hammer-automation.md](hammer-automation.md) | [specification/hammer-automation.md](../../specification/hammer-automation.md) |
| [vernacular-introspection.md](vernacular-introspection.md) | [specification/vernacular-introspection.md](../../specification/vernacular-introspection.md) |
| [assumption-auditing.md](assumption-auditing.md) | [specification/assumption-auditing.md](../../specification/assumption-auditing.md) |
| [universe-inspection.md](universe-inspection.md) | [specification/universe-inspection.md](../../specification/universe-inspection.md) |
| [typeclass-debugging.md](typeclass-debugging.md) | [specification/typeclass-debugging.md](../../specification/typeclass-debugging.md) |
| [deep-dependency-analysis.md](deep-dependency-analysis.md) | [specification/deep-dependency-analysis.md](../../specification/deep-dependency-analysis.md) |
| [literate-documentation.md](literate-documentation.md) | [specification/literate-documentation.md](../../specification/literate-documentation.md) |
| [code-extraction-management.md](code-extraction-management.md) | [specification/code-extraction-management.md](../../specification/code-extraction-management.md) |
| [independent-proof-checking.md](independent-proof-checking.md) | [specification/independent-proof-checking.md](../../specification/independent-proof-checking.md) |
| [build-system-integration.md](build-system-integration.md) | [specification/build-system-integration.md](../../specification/build-system-integration.md) |
| [compatibility-analysis.md](compatibility-analysis.md) | [specification/compatibility-analysis.md](../../specification/compatibility-analysis.md) |
| [notation-inspection.md](notation-inspection.md) | [specification/notation-inspection.md](../../specification/notation-inspection.md) |
| [tactic-documentation.md](tactic-documentation.md) | [specification/tactic-documentation.md](../../specification/tactic-documentation.md) |
| [convoy-pattern-assistant.md](convoy-pattern-assistant.md) | specification/convoy-pattern-assistant.md (pending) |
| [setoid-rewriting-assistant.md](setoid-rewriting-assistant.md) | specification/setoid-rewriting-assistant.md (pending) |
