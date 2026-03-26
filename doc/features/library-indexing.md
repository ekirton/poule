# Library Indexing

Offline extraction and indexing of Coq/Rocq library declarations into a portable SQLite database.

---

## What Gets Indexed

For each declaration in a Coq library:

- Fully qualified name and module path
- Kind (lemma, theorem, definition, instance, ...)
- Pretty-printed statement and type (for display and full-text search)
- Structural representation (for structural and type-based search)
- Symbol set (fully qualified kernel names of constants, inductives, and constructors referenced, for symbol-based search)
- Dependency edges (what this declaration uses, what uses it)

## Scope

### Library Indexing (implemented)
- Six supported libraries indexed independently into per-library SQLite databases (see [modular-index-distribution](modular-index-distribution.md))
- All 6 libraries always included — no per-library selection needed
- Download-and-merge assembly of per-library indexes into a single search database
- Single command to index each library; build script orchestrates all 6

### User Project Indexing (planned)
- User's current project (incremental re-indexing on file save)

## Extraction Method

Declarations are extracted from compiled Coq libraries using coq-lsp. coq-lsp is the sole supported extraction backend.

### Structural data from type signatures

coq-lsp's `Search` command returns textual type signatures (e.g., `"forall n : nat, n + 0 = n"`) but not kernel terms. To enable structural and type-based search, the extraction pipeline parses these type signature strings into the same intermediate representation used by the normalization pipeline. This text-based parsing produces structural data (expression trees, symbol sets, WL histograms) that is internally consistent: both the index and query-time parsing use the same parser, so structural matching works despite the representations being less precise than kernel terms.

## Index Versioning

The database records an **index schema version** — a version identifier written by the tool at index-creation time. This enables two behaviors:

1. **Tool upgrade → full re-index.** When the tool is updated and the index schema changes, the server detects the version mismatch on startup and triggers a full re-index from scratch. This avoids serving incorrect results from an index whose format no longer matches the tool's expectations.

2. **Library update → immediate rebuild.** The index records the version of each indexed library (e.g., Coq stdlib version, and versions of any additional configured libraries). When the server detects that an installed library version has changed since the index was built, it rebuilds the index before serving any queries. This ensures search results always reflect the current state of the user's libraries.

Re-indexing is always a full rebuild. The index is a derived artifact — rebuilding from scratch is simpler and more reliable than migration, and at the scale of Coq libraries (~120K declarations across all 6 libraries) completes in acceptable time.

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

The text parser initially produces short display names (`Const("nat")`, `Const("+")`) rather than kernel-precise FQNs (`Ind("Corelib.Init.Datatypes.nat")`, `Const("Stdlib.Init.Nat.add")`). A post-parsing symbol resolution step maps these short names to their fully qualified kernel names using coq-lsp `Locate` queries. This ensures that the symbol index uses canonical FQNs, which is essential for the Symbol Overlap retrieval channel to match user queries like `Nat.add` against the correct index entries. Names that cannot be resolved (e.g., user-defined names not in the Coq environment) are stored as-is.

Since both index-time and query-time parsing use the same parser and resolution pipeline, structural representations remain internally consistent.

## Acceptance Criteria

### Index the Standard Library

**Priority:** P0
**Stability:** Stable

- GIVEN a system with Coq installed WHEN the user runs the indexing command targeting stdlib THEN all declarations are extracted and stored in a single SQLite database file
- GIVEN the indexing command is running WHEN no GPU, external API keys, or network access are available THEN the command completes successfully
- GIVEN the indexing command is running WHEN extraction of an individual declaration fails THEN the error is logged and the remaining declarations continue to be indexed
- GIVEN the indexing completes WHEN the database is inspected THEN it contains declarations, dependencies, symbols, and all data required by the retrieval channels
- GIVEN the indexing completes WHEN the `symbol_freq` table is inspected THEN it contains a non-zero number of entries with fully qualified kernel names
- GIVEN the indexing completes WHEN a declaration with a parseable type expression is inspected THEN its `symbol_set` is non-empty
- GIVEN the indexing completes WHEN the database is inspected THEN it contains a recorded index schema version

### Index MathComp

**Priority:** P0
**Stability:** Stable

- GIVEN a system with MathComp installed WHEN the user runs the indexing command targeting MathComp THEN MathComp declarations are stored in the same database as stdlib declarations
- GIVEN the database contains declarations from multiple libraries WHEN a declaration is inspected THEN it is distinguished by its fully qualified module path
- GIVEN MathComp's nested module structure WHEN declarations are indexed THEN fully qualified names and module membership are recorded correctly

### Index a User Project

**Priority:** P1
**Stability:** Stable

- GIVEN a user project directory with compiled `.vo` files WHEN the user runs the indexing command targeting that directory THEN project declarations are indexed into the same database as library declarations
- GIVEN a previously indexed user project WHEN the user re-runs the indexing command after modifying some files THEN only changed declarations are updated without rebuilding the entire index

### Idempotent Re-Indexing

**Priority:** P0
**Stability:** Stable

- GIVEN an existing index database at the output path WHEN the indexing command is run THEN the existing file is deleted before the new index is created
- GIVEN no existing index database at the output path WHEN the indexing command is run THEN the new index is created normally
- GIVEN an existing index database WHEN the indexing command deletes it THEN no confirmation prompt is displayed to the user

### CLI Progress Reporting

**Priority:** P1
**Stability:** Stable

- GIVEN the indexing command is running WHEN a progress flag is enabled THEN the command prints progress messages to stderr for each processing stage
- GIVEN progress reporting is enabled WHEN a stage is in progress THEN messages include an indication of completion such as percent complete or records processed out of total
- GIVEN progress reporting is enabled WHEN the indexing command transitions between stages THEN the stage name is included in the progress output
- GIVEN the indexing command is running WHEN no progress flag is provided THEN no progress messages are printed (quiet by default)

### Detect and Rebuild Stale Indexes

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN the library's installed version changes THEN the system detects the change before serving any queries
- GIVEN a detected library version change WHEN the MCP server receives a query THEN the index is rebuilt before returning results
- GIVEN a stale index is detected WHEN the rebuild completes THEN the new index replaces the old one atomically

### Index Version Compatibility

**Priority:** P0
**Stability:** Stable

- GIVEN a database created by a previous tool version WHEN the current tool version opens it THEN it reads the stored index schema version
- GIVEN an index schema version that does not match the current tool version WHEN the MCP server starts THEN it rejects the index and triggers a full re-index from scratch
- GIVEN a re-index is triggered WHEN it completes THEN the new database records the current index schema version

### Expression Normalization

**Priority:** P1
**Stability:** Stable

- GIVEN a Coq expression at indexing time WHEN it is stored THEN it is normalized to eliminate surface-level syntactic variation
- GIVEN normalization WHEN applied THEN it handles at minimum: application form, type casts, universe annotations, projections, and notation expansion
- GIVEN a declaration with section-local names WHEN it is indexed THEN names are fully qualified
- GIVEN a query expression at search time WHEN it is processed THEN the same normalization is applied as at indexing time

### Symbol FQN Resolution During Indexing

**Priority:** P0
**Stability:** Stable

- GIVEN a declaration whose type mentions `nat` (a short display name) WHEN it is indexed THEN the symbol set stores `Corelib.Init.Datatypes.nat` (the fully qualified kernel name)
- GIVEN a declaration whose type mentions infix `+` (desugared from `Nat.add`) WHEN it is indexed THEN the symbol set stores the FQN of the underlying constant (e.g., `Stdlib.Init.Nat.add`)
- GIVEN a declaration extracted via the metadata-only path (coq-lsp Search output with type signature text) WHEN it is indexed THEN its symbol set is populated by parsing the type signature, normalizing the tree, extracting constants, and resolving each to its FQN
- GIVEN the indexing completes WHEN the `symbol_freq` table is inspected THEN it contains entries keyed by FQN, not short display names
- GIVEN a symbol that cannot be resolved to an FQN (e.g., a user-defined name not in the environment) WHEN it is indexed THEN it is stored as-is without discarding
