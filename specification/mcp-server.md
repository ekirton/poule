# MCP Server

Thin adapter between Claude Code and the retrieval pipeline, exposing search tools via the Model Context Protocol.

**Architecture**: [mcp-server.md](../doc/architecture/mcp-server.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [response-types.md](../doc/architecture/data-models/response-types.md)

---

## 1. Purpose

Define the MCP server that translates MCP tool calls into pipeline queries, validates inputs, formats responses, and manages index lifecycle on startup.

## 2. Scope

**In scope**: 7 tool handlers, input validation, error formatting, index state management, startup checks, response construction.

**Out of scope**: Search logic (owned by pipeline/channels), storage management (owned by storage), Coq expression parsing (owned by pipeline).

## 3. Definitions

| Term | Definition |
|------|-----------|
| MCP | Model Context Protocol — the communication protocol between Claude Code and tool servers |
| Tool handler | A function that processes one MCP tool call and returns a formatted response |
| Index state | The loaded state of the search index (ready, missing, or version-mismatched) |

## 4. Behavioral Requirements

### 4.1 Transport

The server shall communicate via stdio transport, compatible with Claude Code's MCP configuration.

### 4.2 Tool Signatures

#### search_by_name(pattern, limit=50)

- REQUIRES: `pattern` is a non-empty string. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by BM25 relevance.
- Delegates to: `pipeline.search_by_name(ctx, pattern, limit)`

#### search_by_type(type_expr, limit=50)

- REQUIRES: `type_expr` is a non-empty string. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by RRF-fused score.
- Delegates to: `pipeline.search_by_type(ctx, type_expr, limit)`

#### search_by_structure(expression, limit=50)

- REQUIRES: `expression` is a non-empty string. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by structural score.
- Delegates to: `pipeline.search_by_structure(ctx, expression, limit)`

#### search_by_symbols(symbols, limit=50)

- REQUIRES: `symbols` is a non-empty list of strings. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` ranked by MePo relevance.
- Delegates to: `pipeline.search_by_symbols(ctx, symbols, limit)`

#### get_lemma(name)

- REQUIRES: `name` is a non-empty string.
- ENSURES: Returns a `LemmaDetail` for the named declaration.
- On not found: returns `NOT_FOUND` error.
- Constructs `LemmaDetail` by querying: declaration row, outgoing `uses` dependencies, incoming `uses` dependencies, symbol set, node count. `proof_sketch` is always empty string in Phase 1. `score` is always 1.0 (exact match).

#### find_related(name, relation, limit=50)

- REQUIRES: `name` is a non-empty string. `relation` is one of: `"uses"`, `"used_by"`, `"same_module"`, `"same_typeclass"`. `limit` is clamped to [1, 200].
- ENSURES: Returns `SearchResult[]` for related declarations.
- On unknown declaration name: returns `NOT_FOUND` error.

Query strategies:

| Relation | Strategy |
|----------|----------|
| `uses` | `dependencies` where `src = decl_id` and `relation = 'uses'` |
| `used_by` | `dependencies` where `dst = decl_id` and `relation = 'uses'` |
| `same_module` | `declarations` where `module = decl.module` and `id != decl_id` |
| `same_typeclass` | Two-hop: find typeclasses via `instance_of` edges from decl, then find other instances of those typeclasses |

All `find_related` results receive `score = 1.0` (relationship-based, not scored).

#### list_modules(prefix="")

- REQUIRES: `prefix` is a string (may be empty).
- ENSURES: Returns `Module[]` for all modules matching the prefix.

### 4.3 Input Validation

The server shall validate all inputs before delegating to the pipeline:

| Validation | Rule |
|-----------|------|
| String parameters | Must be non-empty after stripping whitespace |
| `limit` parameter | Clamped to [1, 200] (values < 1 become 1, values > 200 become 200) |
| `symbols` list | Must be non-empty; each element must be non-empty after stripping |
| `relation` parameter | Must be one of the four recognized values |

Invalid inputs that cannot be clamped shall return a `PARSE_ERROR` response.

### 4.4 Index State Management

On startup, the server shall check the index in this order:

1. Does the database file exist at the configured path? If not → all tool calls return `INDEX_MISSING`.
2. Does `schema_version` in `index_meta` match the tool's expected version? If not → trigger full re-index (in Phase 1, this translates to `INDEX_VERSION_MISMATCH` directing user to re-index manually).
3. Phase 1: `coq_version` and `mathcomp_version` are stored for informational purposes only. Library version checks are deferred to Phase 2.
4. All checks pass → create `PipelineContext` (loads WL histograms, inverted index, symbol frequencies into memory) → begin serving queries.

### 4.5 Response Formatting

All successful responses shall be formatted as MCP content with `type: "text"` containing a JSON-serialized result.

`SearchResult` serialization:
```json
{"name": "...", "statement": "...", "type": "...", "module": "...", "kind": "...", "score": 0.85}
```

`DeclKind` values are serialized as lowercase strings (e.g., `"lemma"`, `"theorem"`).

## 5. Error Specification

All error responses use MCP's standard error format:

```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"...\", \"message\": \"...\"}}"}],
  "isError": true
}
```

| Condition | Error Code | Message Template |
|-----------|-----------|-----------------|
| No index database | `INDEX_MISSING` | `Index database not found at {path}. Run the indexing command to create it.` |
| Schema version mismatch | `INDEX_VERSION_MISMATCH` | `Index schema version {found} is incompatible with tool version {expected}. Re-indexing from scratch.` |
| Library version mismatch (Phase 2) | `INDEX_VERSION_MISMATCH` | `Installed library versions do not match the index. Re-index manually to update.` |
| Declaration not found | `NOT_FOUND` | `Declaration {name} not found in the index.` |
| Parse failure | `PARSE_ERROR` | `Failed to parse expression: {details}` |

Both server-side validation errors and pipeline-side parse errors use `PARSE_ERROR`. The `message` field distinguishes the origin.

## 6. Non-Functional Requirements

- The server is a thin adapter — it shall not implement search logic, manage storage directly, or parse Coq expressions.
- Startup time includes loading WL histograms into memory (~100MB for 100K declarations).
- Stdio transport for Claude Code compatibility.

## 7. Examples

### Successful search_by_name

Request: `search_by_name(pattern="Nat.add_comm", limit=10)`

Response:
```json
{
  "content": [{"type": "text", "text": "[{\"name\": \"Coq.Arith.PeanoNat.Nat.add_comm\", \"statement\": \"forall n m : nat, n + m = m + n\", \"type\": \"forall n m : nat, n + m = m + n\", \"module\": \"Coq.Arith.PeanoNat\", \"kind\": \"lemma\", \"score\": 0.95}]"}]
}
```

### Error: index missing

Request: any tool call when database does not exist

Response:
```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"INDEX_MISSING\", \"message\": \"Index database not found at /path/to/index.db. Run the indexing command to create it.\"}}"}],
  "isError": true
}
```

### Error: declaration not found

Request: `get_lemma(name="nonexistent.declaration")`

Response:
```json
{
  "content": [{"type": "text", "text": "{\"error\": {\"code\": \"NOT_FOUND\", \"message\": \"Declaration nonexistent.declaration not found in the index.\"}}"}],
  "isError": true
}
```

## 8. Language-Specific Notes (Python)

- Use the `mcp` Python SDK for MCP protocol handling and stdio transport.
- Use `@server.tool()` decorator pattern for tool registration.
- Use `asyncio` for the server event loop.
- JSON serialization via `dataclasses.asdict()` + `json.dumps()` for response types.
- Package location: `src/wily_rooster/server/`.
