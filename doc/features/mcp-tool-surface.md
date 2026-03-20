# MCP Tool Surface

The set of MCP tools exposed by the search server, designed to give the LLM maximum flexibility in how it searches Coq libraries. The same search operations are also available as [standalone CLI commands](cli-search.md) for terminal use without an MCP client.

**Stories**: [Epic 2: MCP Server and Tool Surface](../requirements/stories/tree-search-mcp.md#epic-2-mcp-server-and-tool-surface), [Epic 5: End-to-End User Experience](../requirements/stories/tree-search-mcp.md#epic-5-end-to-end-user-experience)

---

## Tools

The server exposes 7 tools. The breadth is intentional — the LLM can combine multiple tools in a single reasoning turn: name search to orient, structural search to find similar types, dependency traversal to explore neighborhoods.

### search_by_name

Find declarations by name pattern (glob or regex on fully qualified names). The most common entry point when a user partially remembers a name.

### search_by_type

Find declarations whose type matches a Coq type expression. Engages multiple retrieval channels and fuses results. The most powerful single tool for precise queries.

### search_by_structure

Find declarations structurally similar to a given Coq expression. Discovers lemmas with related logical shapes even when names and symbols differ entirely.

### search_by_symbols

Find declarations sharing constant/inductive/constructor symbols with the query. Catches cases where structural shape differs but the same mathematical objects appear. Accepts symbol names at any level of qualification — short names like `Nat.add`, partial qualifications like `Init.Nat.add`, or fully qualified kernel names like `Coq.Init.Nat.add` — and resolves them against the index before matching.

### get_lemma

Retrieve full details for a specific declaration: dependencies, dependents, proof sketch, and symbol list. Used after initial search to understand a candidate in depth.

### find_related

Navigate the dependency graph from a known declaration. Supports relations: `uses`, `used_by`, `same_module`, `same_typeclass`. Enables exploration of library neighborhoods.

### list_modules

Browse the module hierarchy. Accepts a prefix (e.g., `Coq.Arith`, `mathcomp.algebra`) and returns child modules with declaration counts.

## Design Rationale

### Why 7 tools instead of 1

A single "search" tool with a mode parameter would be simpler, but:
- Each tool has a distinct parameter shape (expression vs. symbol list vs. name pattern vs. qualified name)
- The LLM benefits from semantic tool names when deciding which search strategy to use
- Multiple tools can be called in parallel within a single reasoning turn

### Why 7 tools is near the upper bound

Research on MCP tool overload (EclipseSource, Lunar.dev) shows that tool-calling accuracy degrades after ~20-30 tools, and each tool schema consumes 200-400 tokens of context window. At 7 tools, the schema overhead is ~1,400-2,800 tokens — manageable. Significantly more tools would require dynamic tool loading (Claude's Tool Search pattern) to avoid context bloat.

The Weaviate MCP server's pattern of offering `semantic_search`, `keyword_search`, and `hybrid_search` as separate tools is the closest analogue in the vector database ecosystem — giving the LLM strategic choice without overloading context.

### Why high default limits

All search tools default to returning 50 results. This biases toward recall over precision — the LLM filtering layer is responsible for precision. A user will never see 50 raw results; they see the 3-5 the LLM selects and explains.

## Error Behavior

All tools return structured error responses rather than empty results when something goes wrong. This allows the LLM to relay actionable guidance to the user instead of silently returning nothing.

| Condition | Behavior |
|-----------|----------|
| No index database at configured path | All tools return an error indicating the index is missing, with instructions to run the indexing command |
| Index schema version mismatch (tool updated) | All tools return an error while re-indexing is in progress, or block until re-index completes (see [library-indexing.md](library-indexing.md)) |
| Library version changed (stale index) | Index is rebuilt before returning results; the query may take longer on the first call after a library update |
| `get_lemma` with unknown name | Returns a clear "not found" error with the queried name |
| Malformed query expression | Returns a parse error with the failing input |
