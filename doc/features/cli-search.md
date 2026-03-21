# CLI Search

Standalone command-line access to the same search capabilities exposed by the MCP server, for Coq developers working in a terminal without Claude Code.

---

## Problem

The MCP server requires Claude Code (or another MCP client) to access search results. Coq developers who work in a terminal — scripting, piping results into other tools, or simply preferring the command line — have no way to query the index directly.

## Solution

A set of CLI subcommands that mirror the MCP tool surface: `search-by-name`, `search-by-type`, `search-by-structure`, `search-by-symbols`, `get-lemma`, `find-related`, and `list-modules`. Each command accepts the same logical parameters as its MCP counterpart, queries the same retrieval pipeline, and prints results to stdout.

## Design Rationale

### Why mirror the MCP tools

The MCP tools already represent a well-decomposed, tested API surface. Reusing the same pipeline functions and response types means the CLI is a thin presentation layer — not a second search implementation. Results are identical regardless of whether the query arrives via MCP or CLI.

### Why both human-readable and JSON output

Human-readable output (the default) makes the CLI usable interactively — a developer can scan results at a glance. JSON output (`--json`) makes it composable — results can be piped to `jq`, consumed by scripts, or integrated into CI workflows.

### Why a unified command group

All search commands live under a single entry point (e.g., `poule search-by-name ...`), sharing common options like `--db` and `--json`. This avoids scattering multiple binaries and keeps the interface discoverable via `--help`.

## Scope Boundaries

The CLI is a **presentation layer** over the existing retrieval pipeline. It does not:

- Implement search logic (that is owned by the pipeline)
- Provide interactive or REPL-style search sessions
- Replace the MCP server for Claude Code users
- Support query reformulation or iterative refinement (those are LLM-mediated behaviors)

## Acceptance Criteria

### Search by Name via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed database WHEN the user runs the CLI search-by-name command with a pattern THEN matching declarations are printed to stdout ranked by relevance
- GIVEN a search command WHEN the `--json` flag is provided THEN results are output as a JSON array of `SearchResult` objects
- GIVEN a search command WHEN no format flag is provided THEN results are output in a human-readable tabular format
- GIVEN a search command WHEN a `--limit` option is provided THEN the result count respects the specified limit
- GIVEN a search command WHEN no `--limit` is provided THEN the default limit is 50

### Search by Type via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed database WHEN the user runs the CLI search-by-type command with a Coq type expression THEN matching declarations are printed to stdout ranked by fused score
- GIVEN search results WHEN the `--json` flag is provided THEN results are output as a JSON array
- GIVEN search results WHEN no format flag is provided THEN results are output in human-readable format

### Search by Structure via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed database WHEN the user runs the CLI search-by-structure command with a Coq expression THEN matching declarations are printed to stdout ranked by structural score
- GIVEN search results WHEN the `--json` flag is provided THEN results are output as a JSON array

### Search by Symbols via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed database WHEN the user runs the CLI search-by-symbols command with one or more symbol names THEN matching declarations are printed to stdout ranked by relevance
- GIVEN search results WHEN the `--json` flag is provided THEN results are output as a JSON array

### Get Lemma Details via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed database WHEN the user runs the CLI get-lemma command with a fully qualified name THEN the full declaration details are printed to stdout
- GIVEN a name that does not exist WHEN the get-lemma command is run THEN a clear error message is printed to stderr and the command exits with a non-zero status
- GIVEN the `--json` flag WHEN get-lemma is run THEN the output is a JSON `LemmaDetail` object

### Find Related Declarations via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed database WHEN the user runs the CLI find-related command with a declaration name and relation type THEN related declarations are printed to stdout
- GIVEN search results WHEN the `--json` flag is provided THEN results are output as a JSON array

### List Modules via CLI

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed database WHEN the user runs the CLI list-modules command with a prefix THEN matching modules and their declaration counts are printed to stdout
- GIVEN an empty prefix WHEN list-modules is run THEN all top-level modules are listed
- GIVEN the `--json` flag WHEN list-modules is run THEN the output is a JSON array of module objects

### CLI Error Handling

**Priority:** P0
**Stability:** Stable

- GIVEN no index database at the specified path WHEN any CLI search command is run THEN an error message is printed to stderr indicating the index is missing and how to create it, and the command exits with a non-zero status
- GIVEN a malformed query expression WHEN a CLI search command is run THEN a parse error message is printed to stderr and the command exits with a non-zero status
- GIVEN a successful search WHEN results are empty THEN the command exits with zero status and prints no results (or an empty JSON array with `--json`)
