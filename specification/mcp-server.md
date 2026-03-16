# MCP Server

Protocol translation layer between Claude Code (or any MCP client) and the retrieval pipeline. Validates inputs, dispatches to retrieval channels, formats responses, and reports errors.

Parent architecture: [doc/architecture/mcp-server.md](../doc/architecture/mcp-server.md)
Component boundaries: [doc/architecture/component-boundaries.md](../doc/architecture/component-boundaries.md)
Response types: [doc/architecture/data-models/response-types.md](../doc/architecture/data-models/response-types.md)
Pipeline: [pipeline.md](pipeline.md)

---

## 1. Purpose

Expose the Coq semantic search system as an MCP server that Claude Code can invoke via tool calls. The server owns input validation, response formatting, and error reporting. It delegates all retrieval logic to the pipeline layer.

---

## 2. Scope

Covers the MCP transport, tool definitions (7 tools), request validation, response shaping, error contract, and startup lifecycle. Does not cover retrieval algorithms (see [pipeline.md](pipeline.md)) or storage details (see [storage.md](storage.md)).

---

## 3. Transport

**Protocol**: Model Context Protocol (MCP) over stdio.

**Compatibility**: The server must be configurable as an MCP server in Claude Code's `~/.claude/mcp_servers.json`:

```json
{
  "coq-search": {
    "command": "python",
    "args": ["-m", "coq_search.server"],
    "env": {}
  }
}
```

The server reads JSON-RPC messages from stdin and writes responses to stdout. All diagnostic logging goes to stderr.

---

## 4. Tool Definitions

### 4.1 `search_by_name`

Search for declarations by name pattern (glob or substring).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | yes | Name pattern — supports `*` glob wildcard and substring matching |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

**REQUIRES**: `pattern` is a non-empty string.

**ENSURES**: Returns a list of `SearchResult` ordered by BM25 relevance score.

**Pipeline**: Dispatches to FTS5 channel (see [channel-fts.md](channel-fts.md)).

### 4.2 `search_by_type`

Multi-channel search for declarations matching a Coq type expression.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type_expr` | string | yes | A Coq type expression (e.g., `forall n : nat, n + 0 = n`) |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

**REQUIRES**: `type_expr` is a syntactically valid Coq expression.

**ENSURES**: Returns a list of `SearchResult` ordered by RRF-fused score across WL, MePo, and FTS5 channels.

**Pipeline**: Dispatches to `search_by_type` flow (see [pipeline.md](pipeline.md)).

### 4.3 `search_by_structure`

Find declarations with structurally similar expressions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `expression` | string | yes | A Coq expression to match structurally |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

**REQUIRES**: `expression` is a syntactically valid Coq expression.

**ENSURES**: Returns a list of `SearchResult` ordered by structural similarity score (WL + TED + collapse-match + Jaccard fusion).

**Pipeline**: Dispatches to `search_by_structure` flow (see [pipeline.md](pipeline.md)).

### 4.4 `search_by_symbols`

Find declarations sharing mathematical symbols with the query.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbols` | list[string] | yes | List of fully qualified symbol names |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

**REQUIRES**: `symbols` is a non-empty list of strings.

**ENSURES**: Returns a list of `SearchResult` ordered by MePo relevance score.

**Pipeline**: Dispatches to MePo channel (see [channel-mepo.md](channel-mepo.md)).

### 4.5 `get_lemma`

Retrieve full details for a specific declaration by name.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Fully qualified declaration name |

**REQUIRES**: `name` is a non-empty string.

**ENSURES**: Returns a single `LemmaDetail` with score=1.0, or a `NOT_FOUND` error.

**Pipeline**: Direct database lookup — no retrieval channels involved.

### 4.6 `find_related`

Navigate the dependency graph from a declaration.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Fully qualified declaration name |
| `relation` | string | yes | Relationship type: `uses`, `used_by`, `same_module`, `same_typeclass` |
| `limit` | integer | no | Max results to return (default: 50, max: 200) |

**REQUIRES**: `name` is a non-empty string. `relation` is one of the four allowed values.

**ENSURES**: Returns a list of `SearchResult` for related declarations.

**Pipeline**: Database queries on `dependencies` table (for `uses`, `used_by`) or `declarations` table (for `same_module`). `same_typeclass` queries declarations that are instances of the same typeclass.

### 4.7 `list_modules`

Browse the module hierarchy.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prefix` | string | no | Module path prefix filter (e.g., `Coq.Arith`) |

**REQUIRES**: None (prefix is optional).

**ENSURES**: Returns a list of `Module` records with declaration counts, ordered alphabetically.

**Pipeline**: Aggregation query on `declarations` table grouped by module.

---

## 5. Response Types

### 5.1 `SearchResult`

Standard response for all search tools.

```python
@dataclass
class SearchResult:
    name: str         # fully qualified declaration name
    statement: str    # pretty-printed statement
    type: str         # pretty-printed type (may be empty for non-typed declarations)
    module: str       # module path
    kind: str         # declaration kind
    score: float      # relevance score in [0.0, 1.0]
```

### 5.2 `LemmaDetail`

Extended response for `get_lemma`.

```python
@dataclass
class LemmaDetail:
    name: str
    statement: str
    type: str
    module: str
    kind: str
    score: float            # always 1.0 (exact match)
    dependencies: list[str] # FQNs of declarations this one uses
    dependents: list[str]   # FQNs of declarations that use this one
    proof_sketch: str       # abbreviated proof term or tactic script
    symbols: list[str]      # fully qualified symbol names
    node_count: int         # expression tree size
```

### 5.3 `Module`

Response for `list_modules`.

```python
@dataclass
class Module:
    name: str         # fully qualified module name
    decl_count: int   # number of declarations in this module
```

---

## 6. Input Validation

The server validates all inputs before dispatching to the pipeline.

| Validation | Tools | Error |
|------------|-------|-------|
| Missing required parameter | All | `PARSE_ERROR` with parameter name |
| Empty string for required string parameter | All | `PARSE_ERROR` with explanation |
| `limit` < 1 or > 200 | All search tools | `PARSE_ERROR`: clamp silently or reject |
| Invalid Coq expression syntax | `search_by_type`, `search_by_structure` | `PARSE_ERROR` with parse error details |
| Invalid `relation` value | `find_related` | `PARSE_ERROR` listing valid values |

**Design choice**: For `limit` out of range, clamp to valid range rather than rejecting — this is more LLM-friendly since the LLM may not know the exact bounds.

---

## 7. Error Contract

All errors are returned as structured MCP error responses, never as empty result lists.

| Error Code | Condition | Returned When |
|------------|-----------|---------------|
| `INDEX_MISSING` | No database file found | Any tool call when index is absent |
| `INDEX_VERSION_MISMATCH` | Schema version or library version mismatch | Any tool call after startup detects mismatch |
| `INDEX_REBUILDING` | Index rebuild in progress | Any tool call during re-indexing |
| `NOT_FOUND` | Named declaration does not exist | `get_lemma`, `find_related` with unknown name |
| `PARSE_ERROR` | Input validation failure | Any tool call with invalid parameters |

**Error response format**:

```python
{
    "error": {
        "code": "INDEX_MISSING",
        "message": "No search index found. Run 'coq-search index' to build the index."
    }
}
```

---

## 8. Server Lifecycle

### 8.1 Startup Sequence

```
1. Parse command-line arguments (database path, log level)
2. Check database file exists
   - Missing → set state to INDEX_MISSING, serve errors for all tool calls
3. Open database read-only
4. Validate index_meta:
   - schema_version mismatch → set state to INDEX_VERSION_MISMATCH
   - coq_version mismatch → set state to INDEX_VERSION_MISMATCH
   - mathcomp_version mismatch → set state to INDEX_VERSION_MISMATCH
5. Load WL histograms (h=3) into memory
6. Build in-memory inverted symbol index
7. Load symbol_freq table into memory
8. Register MCP tool handlers
9. Enter stdio message loop
```

### 8.2 Shutdown

On stdin EOF or SIGTERM: close database connection, exit cleanly.

---

## 9. Non-Functional Requirements

- **Latency**: Tool call response time < 1s for 50K indexed declarations (excluding Coq expression parsing).
- **Memory**: WL histograms for 50K declarations fit in ~200 MB. Symbol inverted index fits in ~50 MB. Total server memory < 500 MB.
- **Concurrency**: Single-threaded event loop. MCP protocol is request-response; no concurrent tool calls.
- **Logging**: All diagnostic output to stderr. Never write non-MCP content to stdout.
- **No external dependencies at runtime**: No GPU, no API keys, no network access. The server is fully self-contained after indexing.

---

## 10. Examples

### Example: `search_by_name` Happy Path

**Given**: Index is loaded with stdlib declarations.

**When**: MCP tool call `search_by_name(pattern="add_comm")`.

**Then**: Server validates pattern is non-empty, dispatches to FTS5 channel with query `"add" AND "comm"`, receives BM25-ranked results, formats as `SearchResult` list, returns MCP response with results including `Coq.Arith.PeanoNat.Nat.add_comm`, `Coq.NArith.BinNat.N.add_comm`, etc.

### Example: `get_lemma` Not Found

**Given**: Index is loaded.

**When**: MCP tool call `get_lemma(name="Nonexistent.foo")`.

**Then**: Server looks up `"Nonexistent.foo"` in `declarations` table, finds no match, returns structured error:
```json
{"error": {"code": "NOT_FOUND", "message": "Declaration 'Nonexistent.foo' not found in index."}}
```

### Example: Missing Index

**Given**: No database file exists.

**When**: Any MCP tool call arrives.

**Then**: Server returns:
```json
{"error": {"code": "INDEX_MISSING", "message": "No search index found. Run 'coq-search index' to build the index."}}
```
