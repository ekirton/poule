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
- Symbol set (constants, inductives, constructors referenced, for symbol-based search)
- Dependency edges (what this declaration uses, what uses it)

## Phased Scope

### Phase 1 (MVP)
- Coq standard library and MathComp
- Single SQLite database, offline extraction
- Single command to index

### Phase 2
- User's current project (incremental re-indexing on file save)

## Extraction Method

Declarations are extracted from compiled Coq libraries using available tooling (coq-lsp or SerAPI).

## Index Versioning

The database records an **index schema version** — a version identifier written by the tool at index-creation time. This enables two behaviors:

1. **Tool upgrade → full re-index.** When the tool is updated and the index schema changes, the server detects the version mismatch on startup and triggers a full re-index from scratch. This avoids serving incorrect results from an index whose format no longer matches the tool's expectations.

2. **Library update → immediate rebuild.** The index records the version of each indexed library (e.g., Coq stdlib version, MathComp version). When the server detects that an installed library version has changed since the index was built, it rebuilds the index before serving any queries. This ensures search results always reflect the current state of the user's libraries.

Re-indexing is always a full rebuild. The index is a derived artifact — rebuilding from scratch is simpler and more reliable than migration, and at the scale of Coq libraries (< 50K declarations) completes in acceptable time.

## Missing or Corrupt Index

When the MCP server starts and no index database exists at the configured path, or the database is unreadable, the server returns a clear error message indicating the index is missing and how to create it. Search tools return errors rather than empty results so the LLM can relay actionable guidance to the user.

## Design Rationale

### Why offline indexing

Real-time extraction during search is too slow — parsing and type-checking a Coq file takes seconds. The index is built once (or incrementally updated) and queried many times. This also allows the MCP server to start instantly by loading a pre-built database.

### Why SQLite

Single file, no external services, portable across machines. SQLite provides built-in full-text search. The entire standard library index fits comfortably in a single database file.

### Why zero-config

The target user is a Coq developer who wants search, not a systems administrator. Indexing must work with a single command, no GPU, no network access, no API keys (beyond Claude Code itself).
