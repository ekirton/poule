# Implementation Guidelines

## Source of Authority

The `specification/*.md` files are the authoritative source for all implementation decisions. When in doubt about behavior, data types, error handling, contracts, or edge cases, consult the relevant specification document — not the tests, not the architecture docs.

Authority chain: `specification/*.md` → `doc/architecture/` → `doc/features/` → `doc/requirements/`

## Upstream Authority Is Immutable

Test files in `test/`, specification documents in `specification/`, architecture documents in `doc/architecture/`, and data model documents in `doc/architecture/data-models/` **must not be modified** when writing implementation code. Tests encode the specification contracts and were written first (TDD). Implementation must conform to all upstream layers — not the other way around.

- If a test fails, fix the implementation — not the test.
- If a test imports from a specific module path, create that module at that path.
- If a test expects a specific function signature, implement that exact signature.
- If a test expects a specific exception type, raise that exact exception.
- If a specification appears ambiguous or incorrect, file feedback in `specification/feedback/` — do not change the spec. Follow the feedback standards defined in `specification/feedback/CLAUDE.md`.
- If a test appears to conflict with its specification, file feedback in `test/feedback/` — do not change the test. Follow the feedback standards defined in `test/feedback/CLAUDE.md`.
- If an architecture or data model document conflicts with a specification, file feedback in `doc/architecture/feedback/`. Follow the feedback standards defined in `doc/architecture/feedback/CLAUDE.md`.

## Import Paths

Tests define the expected package structure. Follow these module paths exactly:

| Package | Location |
|---------|----------|
| `wily_rooster.models.enums` | Enumerations (`SortKind`, `DeclKind`) |
| `wily_rooster.models.labels` | Node label hierarchy (15 concrete types) |
| `wily_rooster.models.tree` | `TreeNode`, `ExprTree`, utility functions |
| `wily_rooster.models.responses` | `SearchResult`, `LemmaDetail`, `Module` |
| `wily_rooster.normalization.constr_node` | `ConstrNode` variant types |
| `wily_rooster.normalization.normalize` | `constr_to_tree`, `coq_normalize` |
| `wily_rooster.normalization.cse` | `cse_normalize` |
| `wily_rooster.normalization.errors` | `NormalizationError` |
| `wily_rooster.storage.writer` | `IndexWriter` |
| `wily_rooster.storage.reader` | `IndexReader` |
| `wily_rooster.storage.errors` | `StorageError`, `IndexNotFoundError`, `IndexVersionError` |
| `wily_rooster.channels.wl_kernel` | WL histogram, cosine, size filter, screening |
| `wily_rooster.channels.mepo` | Symbol weight, relevance, iterative selection |
| `wily_rooster.channels.fts` | FTS5 query preprocessing and search |
| `wily_rooster.channels.ted` | Zhang-Shasha TED, rename cost, similarity |
| `wily_rooster.channels.const_jaccard` | Jaccard similarity, constant extraction |
| `wily_rooster.fusion.fusion` | Score clamping, collapse match, structural score, RRF |
| `wily_rooster.pipeline.context` | `PipelineContext`, `create_context` |
| `wily_rooster.pipeline.search` | `search_by_structure`, `search_by_type`, `search_by_symbols`, `search_by_name`, `score_candidates` |
| `wily_rooster.pipeline.parser` | `CoqParser`, `ParseError` |
| `wily_rooster.extraction.pipeline` | `run_extraction`, `discover_libraries` |
| `wily_rooster.extraction.kind_mapping` | `map_kind` |
| `wily_rooster.extraction.errors` | `ExtractionError` |
| `wily_rooster.server.handlers` | Tool handler functions |
| `wily_rooster.server.validation` | Input validation functions |
| `wily_rooster.server.errors` | Error formatting, error code constants |
