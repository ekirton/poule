# Implementation Plan: Coq Library Extraction

**Specification:** [specification/extraction.md](../specification/extraction.md)
**Architecture:** [doc/architecture/coq-extraction.md](../doc/architecture/coq-extraction.md)
**Feedback:** [specification/feedback/extraction.md](../specification/feedback/extraction.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, NodeLabel, WlHistogram, SymbolSet types
- [storage.md](../specification/storage.md) — Schema DDL, table definitions
- [coq-normalization.md](../specification/coq-normalization.md) — `constr_to_tree`, `coq_normalize`, ConstrNode
- [cse-normalization.md](../specification/cse-normalization.md) — `cse_normalize`
- [channel-wl-kernel.md](../specification/channel-wl-kernel.md) — `wl_histogram`

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, `TreeNode`, `NodeLabel` hierarchy (all 16 concrete subtypes), `WlHistogram`, `SymbolSet`, utility functions (`recompute_depths`, `assign_node_ids`, `node_count`).
2. **Coq normalization** (from coq-normalization.md tasks) must be implemented: `ConstrNode` type, `constr_to_tree()`, `coq_normalize()`.
3. **CSE normalization** (from cse-normalization.md tasks) must be implemented: `cse_normalize()`.
4. **WL kernel computation** (from channel-wl-kernel.md tasks) must be implemented: `wl_histogram(tree, h)`.
5. **Storage schema DDL** is defined in storage.md and can be implemented as part of this plan (Phase E), but the schema itself must be stable.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **ConstrNode parsing is a separate task (T12)** rather than embedded in the backend implementation. The architecture doc shows "Parse Constr.t -> ConstrNode" as an explicit step, but the extraction spec does not specify where this parsing lives. This plan places it in a dedicated parser module with backend-agnostic interface, since coq-lsp (JSON) and SerAPI (S-expression) require distinct parsers that share a common output type.
- **Backend implementations (T4, T5) are parallelizable** since they share only the abstract interface from T3. The plan assumes coq-lsp is the primary target for Phase 1, with SerAPI as fallback.
- **The pipeline orchestrator (T19) implements the two-pass architecture** described in the architecture doc, even though the extraction spec does not explicitly describe two passes. Pass 1 extracts declarations and collects raw dependency names; Pass 2 resolves names to foreign keys after all declarations are inserted.
- **Progress reporting uses per-declaration granularity** following the architecture doc, which is more granular than the per-`.vo` file logging described in the extraction spec Section 7.
- **Kind mapping (T9) is a standalone module** because the extraction spec lacks an explicit mapping table (see feedback Issue 2). The implementer must derive the mapping from the data model's enumeration of valid kinds and Coq's declaration forms. This plan documents the assumed mapping in the task's completion criteria.
- **WL histograms are computed at h=3 only** for Phase 1, following the architecture doc note "Phase 1 computes h=3 only" and the extraction spec. The data model defines h in {1, 3, 5} with 3 rows per declaration, but this plan stores only h=3 until the discrepancy is resolved (see feedback Issue 1).

---

## Tasks

### Phase A: Package Structure

- [ ] **T1: Extraction package scaffolding** — Create the extraction subpackage and test directories
  - **Traces to:** Project setup
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/extraction/__init__.py`, `src/coq_search/extraction/backends/__init__.py`, `tests/extraction/__init__.py`
  - **Done when:** `from coq_search.extraction import run_extraction` works; `from coq_search.extraction.coq_backend import CoqBackend` works; `pytest` discovers tests under `tests/extraction/`; the `__init__.py` exports: `run_extraction`, `CoqBackend`, `ExtractionReport`

### Phase B: Error Types and Models

- [ ] **T2: Extraction error types** — Define all custom exception types for the extraction module
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 6; [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/extraction/errors.py`
  - **Done when:** Exception classes defined: `ExtractionError` (base), `CoqNotInstalledError`, `LibraryNotFoundError`, `CoqBackendError`, `BackendCrashError`, `IndexIntegrityError`, `DeclarationExtractionError`; `CoqNotInstalledError` includes installation instructions in its message; `BackendCrashError` is a subclass of `CoqBackendError`; all are subclasses of `ExtractionError`; each carries relevant context (declaration name, file path, error detail as applicable)

- [ ] **T3: DeclarationResult model** — Define the intermediate result type for per-declaration processing
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.2 (output per declaration)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/extraction/models.py`
  - **Done when:** A `DeclarationResult` dataclass has fields: `name: str`, `module: str`, `kind: str`, `statement: str`, `type_expr: str`, `constr_tree_blob: bytes` (serialized ExprTree per storage.md Section 9.1 — pickle protocol 5), `node_count: int`, `symbol_set: list[str]` (sorted, deduplicated), `wl_histogram: dict[str, int]` (h=3), `dependency_names: list[tuple[str, str]]` (dst_name, relation — resolved to IDs in Pass 2); an `ExtractionReport` dataclass has fields: `total_declarations: int`, `total_skipped: int`, `total_dependencies: int`, `total_symbols: int`, `elapsed_seconds: float`

### Phase C: Backend Interface

- [ ] **T4: Coq backend abstract interface** — Define the abstract interface for communicating with a Coq subprocess
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 5; [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library)
  - **Depends on:** T2
  - **Produces:** `src/coq_search/extraction/coq_backend.py`
  - **Done when:** An abstract base class `CoqBackend` (or Protocol) defines the required operations: `start()`, `stop()`, `load_file(path)`, `enumerate_declarations(file) -> list[tuple[str, str]]` (name and raw Coq form string), `get_constr_t(name) -> RawConstr` (JSON dict or S-expression string), `pretty_print(name) -> str`, `pretty_print_type(name) -> str`, `resolve_fqn(name) -> str`, `get_instance_metadata(name) -> list[str] | None`; a `RawConstr` type alias covers the union of JSON dict and S-expression string; lifecycle contract documented: one `start()`, many operations, one `stop()`; all operations raise `CoqBackendError` on failure; the abstract class cannot be instantiated directly; unit test verifies instantiation of base class raises `TypeError`

- [ ] **T5: coq-lsp backend implementation** — Implement the `CoqBackend` for the coq-lsp LSP-over-stdio subprocess
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 5
  - **Depends on:** T4
  - **Produces:** `src/coq_search/extraction/backends/coqlsp_backend.py`
  - **Done when:** `CoqLspBackend` implements all operations from `CoqBackend`; `start()` spawns a `coq-lsp` subprocess over stdio using LSP protocol; `stop()` sends shutdown/exit and terminates the process; backend crash detection is implemented: if the subprocess exits unexpectedly, subsequent operations raise `BackendCrashError` with exit code and stderr; all operations raise `CoqBackendError` with diagnostic detail on failure; integration test (marked `@pytest.mark.integration`, skipped when coq-lsp is not installed) verifies loading a stdlib `.vo` file and retrieving at least one declaration's name, kind, and Constr.t

- [ ] **T6: SerAPI backend implementation** — Implement the `CoqBackend` for the SerAPI subprocess
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 5
  - **Depends on:** T4
  - **Produces:** `src/coq_search/extraction/backends/serapi_backend.py`
  - **Done when:** `SerAPIBackend` implements all operations from `CoqBackend`; `start()` spawns `sertop`; `stop()` sends `(Quit)` and terminates; backend crash detection implemented; integration test (marked `@pytest.mark.integration`, skipped when sertop is not installed) verifies loading a stdlib `.vo` file

- [ ] **T7: Backend factory and auto-detection** — Create a factory function that selects and instantiates the appropriate backend
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 5.1
  - **Depends on:** T5, T6
  - **Produces:** `src/coq_search/extraction/backend_factory.py`
  - **Done when:** `create_backend(backend_type=None) -> CoqBackend` probes for `coq-lsp` first (via `shutil.which`), then `sertop`; returns the first available backend; raises `CoqNotInstalledError` with installation instructions if neither is found; optional `backend_type` parameter allows explicit override (`"coqlsp"` or `"serapi"`); unit tests cover: auto-detection with mock `shutil.which`, explicit override, and neither-found error

### Phase D: Library Discovery and Version Detection

- [ ] **T8: Library path discovery** — Implement `.vo` file discovery for stdlib and MathComp
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 5.2; [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library), [Story 1.2](../doc/requirements/stories/tree-search-mcp.md#12-index-mathcomp)
  - **Depends on:** T2
  - **Produces:** `src/coq_search/extraction/library_discovery.py`
  - **Done when:** `discover_stdlib_vos() -> list[Path]` runs `coqc -where` to find Coq installation, then recursively collects all `.vo` files under `theories/`; `discover_mathcomp_vos() -> list[Path]` uses `coqc` to resolve the `mathcomp` logical path, then recursively collects `.vo` files; `discover_vos(targets: list[str]) -> list[Path]` dispatches to the appropriate discovery function for each target (`"stdlib"`, `"mathcomp"`); raises `LibraryNotFoundError` listing expected paths if `.vo` files are not found; raises `CoqNotInstalledError` if `coqc` is not found; unit tests mock `subprocess.run` and use `tmp_path` with dummy `.vo` files; discovery also provides a mapping from `.vo` file path to logical module path for use in setting `declarations.module`

- [ ] **T9: Coq and MathComp version detection** — Detect installed Coq and MathComp versions for index_meta
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.1 step 7; [storage.md](../specification/storage.md) Section 3.5; [Story 1.4](../doc/requirements/stories/tree-search-mcp.md#14-detect-and-rebuild-stale-indexes)
  - **Depends on:** T2
  - **Produces:** `src/coq_search/extraction/version_detection.py`
  - **Done when:** `detect_coq_version() -> str` runs `coqc --version` and parses the version string (e.g., `"8.19.0"`); `detect_mathcomp_version() -> str` queries installed MathComp version, returns `"none"` if not installed (matching the NOT NULL constraint on `index_meta.value`); raises `CoqNotInstalledError` if `coqc` is not found; unit tests mock `subprocess.run` and verify parsing of representative version output strings

### Phase E: Database Writer

- [ ] **T10: Schema creation** — Implement SQLite schema creation from storage.md DDL
  - **Traces to:** [storage.md](../specification/storage.md) Section 3; [extraction.md](../specification/extraction.md) Section 4.1 steps 2-3
  - **Depends on:** T2
  - **Produces:** `src/coq_search/extraction/db_schema.py`
  - **Done when:** `create_schema(conn: sqlite3.Connection) -> None` executes all CREATE TABLE and CREATE INDEX statements from storage.md Section 3 in a single transaction; `PRAGMA foreign_keys = ON` set before DDL; FTS5 availability checked before creation (raise error if unavailable); `drop_and_recreate(db_path: Path) -> sqlite3.Connection` deletes existing file if present, creates fresh database, sets pragmas (`journal_mode = DELETE`, `foreign_keys = ON`), calls `create_schema()`; unit test verifies all 6 tables exist (`declarations`, `dependencies`, `wl_vectors`, `symbol_freq`, `index_meta`, `declarations_fts`), column names match spec, indexes are created

- [ ] **T11: Declaration and WL vector batch writer** — Implement batched insertion of declarations with their WL vectors
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.1 step 4d; [storage.md](../specification/storage.md) Section 5.1
  - **Depends on:** T3, T10
  - **Produces:** `src/coq_search/extraction/db_writer.py`
  - **Done when:** `insert_declarations_batch(conn, results: list[DeclarationResult], batch_size=1000) -> dict[str, int]` inserts declaration rows and their corresponding `wl_vectors` rows (decl_id, h=3, histogram JSON) within the same transaction per batch; returns `name -> id` mapping for dependency resolution in Pass 2; on batch `IntegrityError`, falls back to row-by-row insertion, skipping duplicates with log messages; kind values are lowercased before insertion per architecture doc; unit tests verify: batch of 10 inserts correctly, returned mapping is accurate, `wl_vectors` rows present for each declaration, duplicate name skipped gracefully

- [ ] **T12: Dependency resolution and insertion (Pass 2)** — Resolve dependency names to IDs and batch-insert edges
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.4; architecture doc Pass 2
  - **Depends on:** T3, T10, T11
  - **Produces:** `resolve_and_insert_dependencies()` in `src/coq_search/extraction/db_writer.py`
  - **Done when:** `resolve_and_insert_dependencies(conn, results: list[DeclarationResult], name_to_id: dict[str, int], batch_size=1000) -> int` iterates all declarations' `dependency_names`, resolves `dst_name` to `declarations.id` via `name_to_id`, silently skips unresolved names (outside indexed scope) per spec Section 4.4, excludes self-referential edges (where src == dst, per data model constraint), deduplicates `(src, dst, relation)` triples, batch-inserts into `dependencies`; returns count of inserted edges; unit tests verify: resolvable edges inserted, unresolved skipped, self-references excluded, duplicate triples deduplicated

- [ ] **T13: Symbol frequency table builder** — Build the global `symbol_freq` table
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.5
  - **Depends on:** T10, T11
  - **Produces:** `build_symbol_freq()` in `src/coq_search/extraction/db_writer.py`
  - **Done when:** `build_symbol_freq(conn) -> int` queries all `declarations.symbol_set` JSON arrays, aggregates per-symbol counts, inserts `(symbol, freq)` rows into `symbol_freq`; every `freq` >= 1 (invariant from data-structures.md Section 5); returns count of distinct symbols; unit tests verify correct counts for symbols shared across multiple declarations and symbols unique to one declaration

- [ ] **T14: FTS rebuild, metadata, and integrity check** — Finalize the index after all data is inserted
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.1 steps 6-8; [storage.md](../specification/storage.md) Section 3.6, 3.5
  - **Depends on:** T10
  - **Produces:** `finalize_index()` and `run_integrity_check()` in `src/coq_search/extraction/db_writer.py`
  - **Done when:** `finalize_index(conn, coq_version, mathcomp_version) -> None` executes FTS rebuild (`INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')`), inserts 4 required `index_meta` keys (`schema_version` as `"1"`, `coq_version`, `mathcomp_version`, `created_at` as ISO 8601 UTC), runs `PRAGMA integrity_check`; on integrity failure: closes connection, deletes database file, raises `IndexIntegrityError`; unit tests verify: FTS rebuild enables full-text search on inserted declarations, all 4 metadata keys present with correct types, integrity check passes on valid database

### Phase F: Declaration Processing

- [ ] **T15: Declaration kind mapping** — Implement the Coq declaration form to storage kind mapping
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.2; [data model](../doc/architecture/data-models/index-entities.md) `declarations.kind`
  - **Depends on:** None
  - **Produces:** `src/coq_search/extraction/kind_mapping.py`
  - **Done when:** `map_declaration_kind(coq_form: str) -> str | None` maps Coq declaration forms to the 7 storage kinds or `None` for excluded forms; mapping is case-insensitive on input; output kinds are always lowercase; mapping: `Lemma` -> `"lemma"`, `Theorem` -> `"theorem"`, `Definition` -> `"definition"`, `Let` -> `"definition"`, `Inductive` -> `"inductive"`, `Record` -> `"inductive"`, `Class` -> `"inductive"`, `Constructor` -> `"constructor"`, `Instance` -> `"instance"`, `Axiom` -> `"axiom"`, `Parameter` -> `"axiom"`, `Conjecture` -> `"axiom"`, `Coercion` -> `"definition"`, `Canonical Structure` -> `"definition"`, `Notation` -> `None`, `Abbreviation` -> `None`, `Section Variable` -> `None`; unit tests cover every row in the mapping table including all excluded forms; tests verify case-insensitivity

- [ ] **T16: Symbol extraction** — Implement `extract_symbols()` on a normalized ExprTree
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.3
  - **Depends on:** data-structures tasks (ExprTree, NodeLabel types)
  - **Produces:** `src/coq_search/extraction/symbol_extraction.py`
  - **Done when:** `extract_symbols(tree: ExprTree) -> list[str]` performs depth-first traversal, collecting `name` from `LConst`, `LInd`, and `LConstruct` labels; returns sorted, deduplicated list; empty tree returns `[]`; tree with no constant/inductive/constructor nodes returns `[]`; unit tests cover: mixed label types, deduplication, sorted output, empty tree, spec example for `Nat.add_comm` producing `["Coq.Init.Datatypes.nat", "Coq.Init.Logic.eq", "Coq.Init.Nat.add"]`

- [ ] **T17: Dependency extraction** — Implement `extract_dependencies()` collecting raw dependency names
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.4
  - **Depends on:** data-structures tasks, T4
  - **Produces:** `src/coq_search/extraction/dependency_extraction.py`
  - **Done when:** `extract_dependencies(tree: ExprTree, decl_name: str, instance_metadata: list[str] | None) -> list[tuple[str, str]]` returns `(dst_name, relation)` pairs; `uses` edges collected from all `LConst` nodes in the tree, deduplicated, excluding self-references (where `dst_name == decl_name`); `instance_of` edges derived from instance metadata (list of class names the declaration is an instance of); empty tree returns `[]`; unit tests cover: `LConst` nodes produce `uses` edges, self-references excluded, deduplication, instance_of edges from metadata, empty tree

- [ ] **T18: ConstrNode parser** — Implement parsing of raw backend output into ConstrNode
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.2 step 1; [coq-normalization.md](../specification/coq-normalization.md) Section 10
  - **Depends on:** coq-normalization tasks (ConstrNode type), T4
  - **Produces:** `src/coq_search/extraction/constr_parser.py`
  - **Done when:** `parse_constr_json(raw: dict) -> ConstrNode` parses coq-lsp JSON output into a `ConstrNode` with universe instances discarded and FQNs pre-resolved; `parse_constr_sexp(raw: str) -> ConstrNode` parses SerAPI S-expression output; both parsers handle all `Constr.t` variants listed in coq-normalization.md: `Rel`, `Var`, `Sort`, `Prod`, `Lambda`, `LetIn`, `App` (with n-ary args), `Const`, `Ind`, `Construct`, `Case`, `Fix`, `CoFix`, `Proj`, `Cast`, `Int`; raises `DeclarationExtractionError` on malformed input or unrecognized variant; unit tests verify parsing of representative JSON and S-expression terms for at least: `Const`, `Ind`, `Construct`, `App`, `Lambda`, `Prod`, `Case`, `Fix`

- [ ] **T19: Per-declaration processor** — Orchestrate the full per-declaration pipeline
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.2; architecture doc per-declaration processing steps
  - **Depends on:** coq-normalization tasks (`coq_normalize`), cse-normalization tasks (`cse_normalize`), channel-wl-kernel tasks (`wl_histogram`), T3, T4, T15, T16, T17, T18
  - **Produces:** `src/coq_search/extraction/declaration_processor.py`
  - **Done when:** `process_declaration(name: str, coq_form: str, module: str, backend: CoqBackend, parser) -> DeclarationResult | None` performs the full per-declaration pipeline: (1) map kind via `map_declaration_kind` — return `None` for excluded forms, (2) `get_constr_t` from backend, (3) parse raw output into `ConstrNode` via parser, (4) `coq_normalize(constr_node)` -> normalized ExprTree (includes `constr_to_tree`, `recompute_depths`, `assign_node_ids`), (5) `cse_normalize(tree)` -> CSE-reduced tree, (6) `extract_symbols(tree)` -> symbol list, (7) `extract_dependencies(tree, name, instance_metadata)` -> raw dependency name pairs, (8) `wl_histogram(tree, h=3)` -> WL vector, (9) `pretty_print(name)` -> statement via backend, (10) `pretty_print_type(name)` -> type_expr via backend, (11) serialize tree to blob via pickle protocol 5, (12) compute node_count; module field set from the `.vo` file's logical path (passed in, not derived from FQN); returns a `DeclarationResult` with all fields populated; returns `None` on fatal per-declaration errors (Constr.t extraction, parsing, normalization failures — spec Section 6.1); pretty-print failure stores empty string and continues (does not skip the declaration); all error cases from spec Section 6.1 handled with logged warnings; unit tests use a mock backend

### Phase G: Pipeline Orchestrator

- [ ] **T20: Main extraction pipeline** — Orchestrate the two-pass extraction pipeline from discovery through finalization
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.1; [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library), [Story 1.2](../doc/requirements/stories/tree-search-mcp.md#12-index-mathcomp)
  - **Depends on:** T3, T7, T8, T9, T10, T11, T12, T13, T14, T18, T19
  - **Produces:** `src/coq_search/extraction/pipeline.py`
  - **Done when:** `run_extraction(targets: list[str], db_path: Path, backend_type: str | None = None) -> ExtractionReport` implements the two-pass extraction flow: (1) detect Coq/MathComp versions via T9, (2) discover `.vo` files via T8, (3) create fresh database via T10 (`drop_and_recreate`), (4) start backend via T7, (5) Pass 1 — for each `.vo` file: `load_file`, `enumerate_declarations`, `process_declaration` for each non-excluded declaration, batch-insert results every 1,000 declarations via T11, (6) `build_symbol_freq` via T13, (7) Pass 2 — `resolve_and_insert_dependencies` via T12, (8) `finalize_index` via T14 (FTS rebuild, index_meta, integrity check), (9) stop backend; progress logged per-declaration following architecture doc format: "Extracting declarations [N/total]" for Pass 1, "Resolving dependencies [N/total]" for Pass 2; pipeline-level errors from spec Section 6.2 handled: abort, delete partial database file, raise; per-declaration errors logged and skipped per Section 6.1; backend lifetime spans entire run; exactly one backend process at any time; database file deleted on any pipeline-level failure; returns `ExtractionReport` with totals and elapsed time

- [ ] **T21: Backend liveness monitoring** — Implement backend crash/hang detection within the pipeline
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 6.2; architecture doc error handling
  - **Depends on:** T4, T5, T6
  - **Produces:** Crash detection logic within backend implementations (T5, T6) and pipeline abort handling in T20
  - **Done when:** Each backend implementation checks subprocess liveness before each operation; if subprocess has exited, raises `BackendCrashError` with diagnostic info (exit code, stderr snippet); pipeline catches `BackendCrashError`, deletes partial database, stops backend, re-raises; unit tests simulate subprocess exit and verify error propagation

### Phase H: CLI Entry Point

- [ ] **T22: CLI entry point** — Provide command-line interface for running extraction
  - **Traces to:** [Story 1.1](../doc/requirements/stories/tree-search-mcp.md#11-index-the-standard-library); [extraction.md](../specification/extraction.md)
  - **Depends on:** T20
  - **Produces:** `src/coq_search/extraction/cli.py`, entry point in `pyproject.toml`
  - **Done when:** Running `coq-search-index` (or `python -m coq_search.extraction`) invokes the extraction pipeline; CLI accepts `--targets` (default: `stdlib,mathcomp`), `--db-path` (default: platform-appropriate data directory), `--backend` (optional: `coqlsp` or `serapi`); `--help` is informative; exit code 0 on success, 1 on error; progress goes to stderr; summary report to stdout showing `ExtractionReport` fields; unit tests verify argument parsing

### Phase I: Unit Tests

- [ ] **T23: Unit tests — kind mapping** — Test all rows of the declaration kind mapping table
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.2; data model kind enumeration
  - **Depends on:** T15
  - **Produces:** `tests/extraction/test_kind_mapping.py`
  - **Done when:** Tests cover every mapping row: Lemma->`"lemma"`, Theorem->`"theorem"`, Definition->`"definition"`, Let->`"definition"`, Inductive->`"inductive"`, Record->`"inductive"`, Class->`"inductive"`, Constructor->`"constructor"`, Instance->`"instance"`, Axiom->`"axiom"`, Parameter->`"axiom"`, Conjecture->`"axiom"`, Coercion->`"definition"`, `Canonical Structure`->`"definition"`, Notation->`None`, Abbreviation->`None`, `Section Variable`->`None`; tests verify output is lowercase; tests verify case-insensitivity of input

- [ ] **T24: Unit tests — symbol extraction** — Test `extract_symbols()` in isolation
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.3
  - **Depends on:** T16
  - **Produces:** `tests/extraction/test_symbol_extraction.py`
  - **Done when:** Tests cover: tree with `LConst`, `LInd`, `LConstruct` collects all names; duplicates deduplicated; result is sorted; tree with only structural nodes (`LApp`, `LAbs`, etc.) returns empty list; empty tree returns `[]`; spec example: tree for `forall n m : nat, n + m = m + n` produces `["Coq.Init.Datatypes.nat", "Coq.Init.Logic.eq", "Coq.Init.Nat.add"]`

- [ ] **T25: Unit tests — dependency extraction** — Test `extract_dependencies()` in isolation
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.4
  - **Depends on:** T17
  - **Produces:** `tests/extraction/test_dependency_extraction.py`
  - **Done when:** Tests cover: tree with `LConst` nodes produces `uses` edges; self-references excluded; duplicate references to same constant produce one edge; `instance_of` edges from metadata; empty tree returns empty list; spec example: `Nat.add_comm` tree produces `uses` edges to `Coq.Init.Nat.add` and `Coq.Init.Logic.eq`

- [ ] **T26: Unit tests — ConstrNode parser** — Test parsing of raw backend output
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.2 step 1; [coq-normalization.md](../specification/coq-normalization.md) Section 10
  - **Depends on:** T18
  - **Produces:** `tests/extraction/test_constr_parser.py`
  - **Done when:** Tests verify JSON parsing for representative Constr.t variants: `Const`, `Ind`, `Construct` (with universe erasure and FQN resolution), `App` (with args list), `Lambda`, `Prod`, `Case`, `Fix`; tests verify S-expression parsing for the same variants; tests verify `DeclarationExtractionError` raised on malformed input; tests verify `Cast` nodes in input are preserved (stripping happens in normalization, not parsing)

- [ ] **T27: Unit tests — database writer** — Test schema creation, batch insertion, dependency resolution, symbol_freq, and finalization
  - **Traces to:** [storage.md](../specification/storage.md) Section 3, 5; [extraction.md](../specification/extraction.md) Section 4.1
  - **Depends on:** T10, T11, T12, T13, T14
  - **Produces:** `tests/extraction/test_db_writer.py`
  - **Done when:** Tests use in-memory SQLite; tests cover: schema creation produces all 6 tables with correct column names; batch insert of 5 declarations stores correct rows in `declarations` and `wl_vectors` in same transaction; `name_to_id` mapping returned is accurate; duplicate name in batch is skipped gracefully (row-by-row fallback); dependency resolution resolves known names, skips unknown, excludes self-references; `symbol_freq` counts correct with shared and unique symbols; FTS rebuild enables full-text search; `index_meta` has all 4 required keys; integrity check passes on valid database

- [ ] **T28: Unit tests — library discovery** — Test `.vo` file discovery with mocked filesystem
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 5.2
  - **Depends on:** T8
  - **Produces:** `tests/extraction/test_library_discovery.py`
  - **Done when:** Tests mock `subprocess.run` for `coqc -where` and logical path resolution; tests use `tmp_path` with dummy `.vo` files; stdlib discovery finds all `.vo` files under `theories/`; mathcomp discovery finds `.vo` files under resolved path; `LibraryNotFoundError` raised when expected path missing; `CoqNotInstalledError` raised when `coqc` not found; module path mapping correctly associates `.vo` files with their logical paths

- [ ] **T29: Unit tests — version detection** — Test Coq and MathComp version parsing
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.1 step 7
  - **Depends on:** T9
  - **Produces:** `tests/extraction/test_version_detection.py`
  - **Done when:** Tests mock `subprocess.run`; standard `coqc --version` output parses correctly for Coq 8.x and Rocq 9.x version strings; MathComp detection returns version string or `"none"`; `CoqNotInstalledError` raised when `coqc` not found

### Phase J: Integration Tests

- [ ] **T30: Integration test — per-declaration processing** — End-to-end test of `process_declaration()` with mock backend
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 4.2, Section 8 (Nat.add_comm example)
  - **Depends on:** T19
  - **Produces:** `tests/extraction/test_declaration_processor_integration.py`
  - **Done when:** Mock backend returns known Constr.t data for a simple declaration; test verifies full pipeline: `DeclarationResult` has correct name, module, kind, statement, type_expr, non-empty `constr_tree_blob`, `node_count > 0`, `symbol_set` as sorted list, `wl_histogram` as dict with string keys, `dependency_names` as list of tuples; test for excluded kind (e.g., Notation) returns `None`; test for failed Constr.t extraction returns `None` with warning logged; test for pretty-print failure returns result with empty statement

- [ ] **T31: Integration test — full pipeline** — End-to-end test of `run_extraction()` with mock backend and temp database
  - **Traces to:** [extraction.md](../specification/extraction.md) Sections 4.1, 7, 8
  - **Depends on:** T20
  - **Produces:** `tests/extraction/test_pipeline_integration.py`
  - **Done when:** Mock backend yields ~10 synthetic declarations across 2 mock `.vo` files; database file created at specified path; `declarations` has expected row count (excluding excluded kinds); `wl_vectors` has one row per declaration with h=3; `dependencies` has resolved edges (unresolved skipped); `symbol_freq` has correct counts; FTS search on declaration names and statements returns expected results; `index_meta` has all 4 required keys with correct values; `ExtractionReport` fields populated and accurate; idempotency test: running extraction twice on same targets produces identical database content (modulo `created_at` timestamp, per spec Section 7)

- [ ] **T32: Integration test — error scenarios** — Test pipeline-level and per-declaration error handling end-to-end
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 6
  - **Depends on:** T20, T21
  - **Produces:** `tests/extraction/test_error_scenarios.py`
  - **Done when:** Mock backend fails on one declaration — remaining declarations still processed and stored in database; pipeline abort on missing library deletes partial database file and raises `LibraryNotFoundError`; database write failure (simulated via read-only path) deletes partial database; backend crash mid-pipeline triggers cleanup: partial database deleted, `BackendCrashError` raised with diagnostic info; partial extraction produces usable database: all non-failing declarations are present and queryable via FTS

### Phase K: Performance Tests

- [ ] **T33: Performance test — extraction throughput** — Validate extraction throughput target
  - **Traces to:** [extraction.md](../specification/extraction.md) Section 7 (throughput: ~50K declarations in under 10 minutes)
  - **Depends on:** T20
  - **Produces:** `tests/extraction/test_performance.py`
  - **Done when:** Test (marked `@pytest.mark.performance`, skipped in CI by default) measures wall-clock time for extracting a representative subset of declarations using a mock backend that simulates realistic Constr.t sizes and processing delays; extrapolated throughput for 50K declarations is under 10 minutes; batch commit overhead measured separately (batch of 1,000 inserts completes in under 1 second); memory usage stays bounded: no unbounded accumulation of `DeclarationResult` objects across batches (results are inserted and discarded per batch)
