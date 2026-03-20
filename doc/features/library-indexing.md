# Library Indexing

Offline extraction and indexing of Coq/Rocq library declarations into a portable SQLite database.

**Stories**: [Epic 1: Library Indexing](../requirements/stories/tree-search-mcp.md#epic-1-library-indexing)

---

## What Gets Indexed

For each declaration in a Coq library:

- Fully qualified name and module path
- Kind (lemma, theorem, definition, instance, ...)
- Pretty-printed statement and type (for display and full-text search)
- Structural representation (for structural and type-based search)
- Symbol set (fully qualified kernel names of constants, inductives, and constructors referenced, for symbol-based search)
- Dependency edges (what this declaration uses, what uses it)

## Phased Scope

### Phase 1 (MVP)
- Coq standard library (default; additional libraries available via configuration)
- Single SQLite database, offline extraction
- Single command to index

### Phase 2
- User's current project (incremental re-indexing on file save)

### Phase 3
- Six supported libraries with per-library distribution (see [modular-index-distribution](modular-index-distribution.md))
- All 6 libraries always included — no per-library selection needed
- Download-and-merge assembly of per-library indexes

## Extraction Method

Declarations are extracted from compiled Coq libraries using coq-lsp. coq-lsp is the sole supported extraction backend.

### Structural data from type signatures

coq-lsp's `Search` command returns textual type signatures (e.g., `"forall n : nat, n + 0 = n"`) but not kernel terms. To enable structural and type-based search, the extraction pipeline parses these type signature strings into the same intermediate representation used by the normalization pipeline. This text-based parsing produces structural data (expression trees, symbol sets, WL histograms) that is internally consistent: both the index and query-time parsing use the same parser, so structural matching works despite the representations being less precise than kernel terms.

## Index Versioning

The database records an **index schema version** — a version identifier written by the tool at index-creation time. This enables two behaviors:

1. **Tool upgrade → full re-index.** When the tool is updated and the index schema changes, the server detects the version mismatch on startup and triggers a full re-index from scratch. This avoids serving incorrect results from an index whose format no longer matches the tool's expectations.

2. **Library update → immediate rebuild.** The index records the version of each indexed library (e.g., Coq stdlib version, and versions of any additional configured libraries). When the server detects that an installed library version has changed since the index was built, it rebuilds the index before serving any queries. This ensures search results always reflect the current state of the user's libraries.

Re-indexing is always a full rebuild. The index is a derived artifact — rebuilding from scratch is simpler and more reliable than migration, and at the scale of Coq libraries (< 50K declarations) completes in acceptable time.

## Idempotent Re-Indexing

The indexing command is safe to run repeatedly. If an index database already exists at the output path, it is deleted automatically before the new index is created. No confirmation is required — the index is a derived artifact that can always be regenerated from the installed Coq libraries, and rebuilding is fast enough that the cost of an accidental re-index is negligible.

## Missing or Corrupt Index

When the MCP server starts and no index database exists at the configured path, or the database is unreadable, the server returns a clear error message indicating the index is missing and how to create it. Search tools return errors rather than empty results so the LLM can relay actionable guidance to the user.

## Design Rationale

### Why offline indexing

Real-time extraction during search is too slow — parsing and type-checking a Coq file takes seconds. The index is built once (or incrementally updated) and queried many times. This also allows the MCP server to start instantly by loading a pre-built database.

### Why SQLite

Single file, no external services, portable across machines. SQLite provides built-in full-text search. The entire standard library index fits comfortably in a single database file.

### Why zero-config

The target user is a Coq developer who wants search, not a systems administrator. Indexing must work with a single command, no GPU, no network access, no API keys (beyond Claude Code itself).

### Why coq-lsp only

SerAPI (coq-serapi) provides deeper access to Coq kernel terms but is version-locked to specific Coq/OCaml combinations, is unmaintained for Rocq 9.x, and adds unsustainable complexity to the container and build process. coq-lsp is actively developed, stable across Coq versions, and provides sufficient metadata for all search channels when combined with text-based type parsing. Supporting a single backend eliminates an entire class of consistency bugs (mixed-backend indexes) and reduces the maintenance surface.

### Why text-based type parsing over kernel terms

coq-lsp does not expose Constr.t kernel terms — it returns type signatures as text strings. Rather than requiring an additional heavy tool (SerAPI) solely for kernel term access, the system parses these text strings into the same ConstrNode intermediate representation.

The text parser initially produces short display names (`Const("nat")`, `Const("+")`) rather than kernel-precise FQNs (`Ind("Coq.Init.Datatypes.nat")`, `Const("Coq.Init.Nat.add")`). A post-parsing symbol resolution step maps these short names to their fully qualified kernel names using coq-lsp `Locate` queries. This ensures that the symbol index uses canonical FQNs, which is essential for the Symbol Overlap retrieval channel to match user queries like `Nat.add` against the correct index entries. Names that cannot be resolved (e.g., user-defined names not in the Coq environment) are stored as-is.

Since both index-time and query-time parsing use the same parser and resolution pipeline, structural representations remain internally consistent.
