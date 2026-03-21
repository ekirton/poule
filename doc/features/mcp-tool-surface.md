# MCP Tool Surface

The set of MCP tools exposed by the search server, designed to give the LLM maximum flexibility in how it searches Coq libraries. The same search operations are also available as [standalone CLI commands](cli-search.md) for terminal use without an MCP client.

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

## Acceptance Criteria

### Start the MCP Server

**Priority:** P0
**Stability:** Stable

- GIVEN a valid MCP configuration WHEN the server starts via stdio transport THEN it connects to Claude Code successfully
- GIVEN a connected server WHEN the tool list is requested THEN it exposes all 7 tools: `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules`
- GIVEN a connected server WHEN any tool is called THEN it returns well-formed MCP tool responses with typed `SearchResult` or `LemmaDetail` objects

### Search by Name

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN `search_by_name` is called with a glob or regex pattern THEN it returns declarations whose fully qualified names match the pattern
- GIVEN matching results WHEN the response is returned THEN each result includes name, statement, type, module, kind, and relevance score
- GIVEN matching results WHEN the response is returned THEN results are ranked by relevance
- GIVEN no limit is specified WHEN results are returned THEN the default limit is 50
- GIVEN a caller-specified limit WHEN results are returned THEN the result count respects the specified limit

### Search by Type

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN `search_by_type` is called with a Coq type expression THEN the backend parses the expression and retrieves candidates using multiple retrieval channels
- GIVEN candidates from multiple channels WHEN results are fused THEN items appearing in multiple channels rank higher
- GIVEN fused results WHEN the response is returned THEN each result includes the standard `SearchResult` fields

### Search by Structure

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN `search_by_structure` is called with a Coq expression string THEN the backend computes structural similarity between the query and indexed declarations
- GIVEN structural similarity scores WHEN results are returned THEN they are ranked by similarity score

### Search by Symbols

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN `search_by_symbols` is called with an array of symbol names THEN the backend retrieves declarations containing those symbols
- GIVEN retrieved results WHEN results are ranked THEN rare symbols are weighted more heavily
- GIVEN ranked results WHEN the response is returned THEN results are ordered by relevance score
- GIVEN a short symbol name (e.g., `Nat.add`) WHEN `search_by_symbols` is called THEN the name is resolved to its fully qualified kernel name (e.g., `Coq.Init.Nat.add`) before matching against the index
- GIVEN a partially qualified name (e.g., `Init.Nat.add`) WHEN `search_by_symbols` is called THEN the name is resolved by suffix match against indexed FQNs
- GIVEN a fully qualified name (e.g., `Coq.Init.Nat.add`) WHEN `search_by_symbols` is called THEN it is matched directly against the index without further resolution
- GIVEN an ambiguous short name that matches multiple FQNs WHEN `search_by_symbols` is called THEN all matching FQNs are included in the query

### Get Lemma Details

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN `get_lemma` is called with a fully qualified declaration name THEN the response includes all `SearchResult` fields plus: dependencies, dependents, proof sketch (if available), symbols list, and node count
- GIVEN a name that does not exist in the index WHEN `get_lemma` is called THEN a clear error message is returned

### Find Related Declarations

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN `find_related` is called with a declaration name and a relation type (`uses`, `used_by`, `same_module`, or `same_typeclass`) THEN results matching the specified relation are returned
- GIVEN no limit is specified WHEN results are returned THEN the default limit is 20
- GIVEN a caller-specified limit WHEN results are returned THEN the result count respects the specified limit
- GIVEN results WHEN the response is returned THEN each result includes the standard `SearchResult` fields

### List Modules

**Priority:** P0
**Stability:** Stable

- GIVEN an indexed library WHEN `list_modules` is called with a module prefix (e.g., `Coq.Arith`, `mathcomp.algebra`) THEN matching module names and their declaration counts are returned
- GIVEN an empty prefix WHEN `list_modules` is called THEN all top-level modules are returned

### Natural Language Lemma Search

**Priority:** P1
**Stability:** Stable

- GIVEN a user describing a need conversationally (e.g., "find a lemma about commutativity of addition on natural numbers") WHEN the LLM processes the request THEN it formulates one or more tool calls to the MCP server
- GIVEN tool call results WHEN the LLM responds THEN it filters results, selects the most relevant, and explains why each is relevant
- GIVEN the full interaction WHEN the user reads the response THEN they receive a useful answer within one conversational turn

### Iterative Refinement

**Priority:** P1
**Stability:** Stable

- GIVEN initial search results that are insufficient WHEN the LLM evaluates them THEN it issues follow-up tool calls with reformulated queries
- GIVEN reformulation WHEN strategies are applied THEN they include: broadening symbol sets, following dependency links, trying different structural patterns, and name pattern variations
- GIVEN refined results WHEN presented to the user THEN the user sees them without needing to re-prompt

### Missing Index

**Priority:** P0
**Stability:** Stable

- GIVEN no index database at the configured path WHEN the MCP server starts THEN it returns a clear error message indicating the index is missing and how to create it
- GIVEN a missing index WHEN any search tool is called THEN the tool returns an error rather than empty results
